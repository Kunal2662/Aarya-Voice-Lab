"""IndicF5 voice generation provider -- a real, local, GPU-accelerated
`pipeline.generation.VoiceGenerator` backend.

Distinct from `LocalNeuralVoiceGenerator` (VLD18), which this module does
NOT modify or replace. That class's `get_capabilities()` never reports
`AVAILABLE` specifically because IndicF5's documented loading path is
`transformers.AutoModel.from_pretrained(repo_id, trust_remote_code=True)`
-- arbitrary code execution from the model repo, which has not undergone
the required security review (see its docstring and
`_INDICF5_ACCESS_NOTE`). That gap is still real and still unaddressed by
this module.

`IndicF5VoiceGenerator` reaches the same model through a different,
already-reviewed path instead: it never sets `trust_remote_code`, and
never imports `transformers.AutoModel` at all. It constructs the DiT/CFM
architecture directly from library code and loads only tensor weights
via `safetensors` (incapable of executing code) -- a materially
different, safer loading strategy, so it is a separate class rather than
a change to `LocalNeuralVoiceGenerator`'s tested, still-accurate
contract.

That "library code" is a small vendored copy of IndicF5's own bundled
F5-TTS source (`scripts/ml_workers/vendor/indicf5_f5tts/`), not the
installed PyPI `f5-tts` package. Checkpoint *loading* works against
either (with the `_orig_mod.` prefix fix), but the installed PyPI
package (currently 1.1.22) has evolved since this checkpoint was
trained -- real generation through it produces unintelligible audio,
confirmed by direct listening and an objective mel/vocoder round-trip
check that ruled out the vocoder. Generation through IndicF5's own
bundled source is verified intelligible (see
`scripts/indicf5_bundled_reference_test.py`), which is what
`indicf5_generation_worker.py` actually imports.

## Process isolation

Mirrors `identity.embeddings.LocalNeuralEmbeddingProvider`: this module
never imports `torch`/`f5_tts` into the base interpreter, which must stay
free of ML dependencies (see that module's docstring). All real work
happens in `scripts/ml_workers/indicf5_generation_worker.py`, run as a
subprocess under the isolated TTS interpreter.

Unlike the embedding provider's worker (one-shot: load, do one thing,
exit -- reloading the model on every call), this provider's worker is a
**persistent subprocess**, started lazily on first use and kept alive
across every subsequent `generate_preview()` call, communicating over
stdin/stdout with one JSON object per line each way. The model and
vocoder are loaded once inside that process and reused for its entire
lifetime -- `close()` ends it explicitly.

## Reference audio (Explicit Future Work)

IndicF5 is a voice-cloning model: every generation needs a reference
audio clip plus its transcript. This codebase has no voice-profile ->
reference-audio resolution mechanism yet (`PreviewRequest.voice_profile_id`
is not linked to a stored audio file anywhere), and building that is out
of scope here. This provider instead ships with exactly one configured
reference voice, defaulting to the exact example the IndicF5 model card
itself documents (`prompts/PAN_F_HAPPY_00001.wav` and its transcript,
resolved from the same HuggingFace cache the checkpoint uses -- offline,
no re-download). A caller may override both via the constructor. Real
per-voice-profile cloning is deliberately not built here.

## Sample rate (Explicit Future Work)

IndicF5 + its vocos vocoder always produce 24000 Hz audio; there is no
resampling step. `PreviewArtifact.sample_rate` always reports this true,
measured rate -- never the request's `sample_rate`, and never a silent
resample. `pipeline.generation.SUPPORTED_SAMPLE_RATES` (16000/22050/44100)
is a different provider's constraint and is deliberately not checked
here.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.data_root import DataRoot, assert_source_writable
from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.identity.preview import PreviewArtifact, PreviewKind
from aarya_voice_lab.identity.runtime import ComputeBackend
from aarya_voice_lab.pipeline.contracts import sha256_file
from aarya_voice_lab.pipeline.generation import (
    MAX_TEXT_LENGTH,
    GenerationBackendState,
    GenerationBlockedError,
    GenerationCapabilities,
    VoiceGenerator,
)
from aarya_voice_lab.pipeline.runner import OFFLINE_ENV, TELEMETRY_OFF_ENV, safe_path_is_file

_WORKER_SCRIPT = PROJECT_ROOT / "scripts" / "ml_workers" / "indicf5_generation_worker.py"

#: Overrides autodetection entirely when set.
TTS_PYTHON_ENV_VAR = "AARYA_TTS_PYTHON"

#: `.envs/<name>` folders tried in order when TTS_PYTHON_ENV_VAR is unset.
#: "env-tts" is environment.specs.EnvironmentId.TTS's canonical name --
#: the one scripts/install_env.sh builds and the one the installer's own
#: Phase E/G smoke tests verified end-to-end (real CUDA generation,
#: human-confirmed intelligible speech; see docs/INDICF5_INSTALLER.md).
#: Tried first so the installer-provisioned environment is what actually
#: gets used by default. "env-tts-windows-gpu" was this project's
#: original, ad hoc Milestone 1-4 development environment (see
#: test_indicf5_direct.py) -- kept second, only as a legacy fallback for
#: machines that still have it and no env-tts yet; the installer itself
#: never creates a directory with that name.
CANDIDATE_ENV_NAMES = ("env-tts", "env-tts-windows-gpu")

DEFAULT_REPO_ID = "ai4bharat/IndicF5"
#: The IndicF5 model card's own documented usage example -- the one
#: reference voice verified working end-to-end by test_indicf5_direct.py.
DEFAULT_REF_AUDIO_REPO_FILENAME = "prompts/PAN_F_HAPPY_00001.wav"
DEFAULT_REF_TEXT = (
    "ਭਹੰਪੀ ਵਿੱਚ ਸਮਾਰਕਾਂ ਦੇ ਭਵਨ ਨਿਰਮਾਣ ਕਲਾ ਦੇ ਵੇਰਵੇ ਗੁੰਝਲਦਾਰ ਅਤੇ ਹੈਰਾਨ ਕਰਨ ਵਾਲੇ ਹਨ, "
    "ਜੋ ਮੈਨੂੰ ਖੁਸ਼ ਕਰਦੇ  ਹਨ।"
)

#: IndicF5's real, measured native output rate (vocos vocoder) -- not a
#: guess, confirmed by test_indicf5_direct.py's generated WAV.
INDICF5_SAMPLE_RATE = 24000

LOAD_TIMEOUT_SECONDS = 180.0
GENERATE_TIMEOUT_SECONDS = 180.0
SHUTDOWN_TIMEOUT_SECONDS = 10.0
_STDERR_TAIL_LINES = 200


class IndicF5WorkerError(RuntimeError):
    """Raised when the worker subprocess cannot be started, times out, or
    reports a failure. Callers of this module see `GenerationBlockedError`
    instead -- this stays internal to the subprocess-management layer."""


def autodetect_tts_python() -> Path | None:
    """The interpreter this provider will launch the worker with, or
    `None` if none can be found. Never raises -- absence is a normal,
    honestly-reportable state (mirrors `LocalNeuralEmbeddingProvider`'s
    `.envs/env-nemo` presence check)."""
    override = os.environ.get(TTS_PYTHON_ENV_VAR)
    if override:
        return Path(override)
    for name in CANDIDATE_ENV_NAMES:
        root = PROJECT_ROOT / ".envs" / name
        for candidate in (root / "Scripts" / "python.exe", root / "bin" / "python"):
            if safe_path_is_file(candidate):
                return candidate
    return None


class _IndicF5Worker:
    """Owns exactly one persistent worker subprocess and its stdin/stdout
    JSON-lines protocol. Two daemon threads pump stdout (into a queue, so
    a response can be waited on with a timeout -- Windows pipes support no
    select()-style readiness check) and stderr (into a bounded tail, for
    honest error messages without ever risking a blocking read)."""

    def __init__(self, python_path: Path, worker_script: Path, *, env: dict[str, str]) -> None:
        self._python_path = python_path
        self._worker_script = worker_script
        self._env = env
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
        self._call_lock = threading.Lock()

    def _pump_stdout(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            self._stdout_queue.put(line)
        self._stdout_queue.put(None)

    def _pump_stderr(self, process: subprocess.Popen[str]) -> None:
        assert process.stderr is not None
        for line in process.stderr:
            self._stderr_tail.append(line.rstrip("\n"))

    def _ensure_started(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        try:
            self._process = subprocess.Popen(  # noqa: S603 -- fixed argv, no shell, no untrusted input in argv itself
                [str(self._python_path), str(self._worker_script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(PROJECT_ROOT),
                env=self._env,
            )
        except OSError as exc:
            raise IndicF5WorkerError(f"failed to start worker process at {self._python_path}: {exc}") from exc
        self._stdout_queue = queue.Queue()
        self._stderr_tail.clear()
        threading.Thread(target=self._pump_stdout, args=(self._process,), daemon=True).start()
        threading.Thread(target=self._pump_stderr, args=(self._process,), daemon=True).start()

    def _stderr_text(self) -> str:
        return "\n".join(self._stderr_tail)

    def call(self, request: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        with self._call_lock:
            self._ensure_started()
            process = self._process
            assert process is not None and process.stdin is not None
            try:
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise IndicF5WorkerError(
                    f"worker is not accepting input: {exc}. stderr: {self._stderr_text()}"
                ) from exc

            try:
                line = self._stdout_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise IndicF5WorkerError(
                    f"worker timed out after {timeout}s waiting for a response. stderr: {self._stderr_text()}"
                ) from exc

            if line is None:
                returncode = process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
                raise IndicF5WorkerError(
                    f"worker exited (code {returncode}) before responding. stderr: {self._stderr_text()}"
                )

            try:
                return json.loads(line)
            except json.JSONDecodeError as exc:
                raise IndicF5WorkerError(f"worker sent a malformed response: {line!r}") from exc

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def close(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            try:
                self.call({"mode": "shutdown"}, timeout=SHUTDOWN_TIMEOUT_SECONDS)
            except IndicF5WorkerError:
                pass
            try:
                self._process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        self._process = None

    def __del__(self) -> None:  # best-effort only -- close() is the real cleanup path
        if self._process is not None and self._process.poll() is None:
            self._process.kill()


class IndicF5VoiceGenerator(VoiceGenerator):
    """Real, local, GPU-accelerated IndicF5 generation. See module
    docstring for the reference-audio and sample-rate limitations."""

    name = "indicf5-local-neural"
    version = "1.0.0"

    def __init__(
        self,
        data_root: DataRoot,
        *,
        tts_python: Path | None = None,
        repo_id: str = DEFAULT_REPO_ID,
        ref_audio_path: Path | str | None = None,
        ref_audio_repo_filename: str = DEFAULT_REF_AUDIO_REPO_FILENAME,
        ref_text: str = DEFAULT_REF_TEXT,
    ) -> None:
        self._data_root = data_root
        self._tts_python = tts_python if tts_python is not None else autodetect_tts_python()
        self._repo_id = repo_id
        self._ref_audio_path = Path(ref_audio_path) if ref_audio_path is not None else None
        self._ref_audio_repo_filename = ref_audio_repo_filename
        self._ref_text = ref_text
        self._worker: _IndicF5Worker | None = None

    def _subprocess_env(self) -> dict[str, str]:
        # Telemetry always off; offline by default since the checkpoint,
        # vocab, vocoder, and default reference audio are all already
        # cached (see docs/REAL_ML_RUNTIME_INTEGRATION.md) -- a stage
        # should fail loudly rather than silently re-download, matching
        # pipeline.runner.build_subprocess_env's own convention.
        return {**os.environ, **TELEMETRY_OFF_ENV, **OFFLINE_ENV}

    def _get_worker(self) -> _IndicF5Worker:
        if self._tts_python is None:
            raise GenerationBlockedError(
                f"{self.name} is not configured: no TTS interpreter found. Checked ${TTS_PYTHON_ENV_VAR} and "
                f"{[f'.envs/{n}' for n in CANDIDATE_ENV_NAMES]}. Build .envs/env-tts "
                "(see docs/INDICF5_INSTALLER.md) or set AARYA_TTS_PYTHON."
            )
        if self._worker is None:
            self._worker = _IndicF5Worker(self._tts_python, _WORKER_SCRIPT, env=self._subprocess_env())
        return self._worker

    def close(self) -> None:
        """End the persistent worker subprocess, if one was started."""
        if self._worker is not None:
            self._worker.close()
            self._worker = None

    def get_capabilities(self) -> GenerationCapabilities:
        """A REAL probe, not a cheap check -- mirrors
        `LocalNeuralEmbeddingProvider.capability_state()`'s "the actual
        model must load successfully" rule. The first call pays the full
        model+vocoder load cost; because the worker persists, every
        subsequent call (and every `generate_preview()`) reuses the
        already-loaded model at effectively no extra cost."""
        if self._tts_python is None:
            return GenerationCapabilities(
                backend_state=GenerationBackendState.NOT_CONFIGURED,
                compute_backend=ComputeBackend.CPU,
                supported_controls=frozenset(),
                missing_requirements=("tts-interpreter",),
                detail=(
                    f"No TTS interpreter found. Checked ${TTS_PYTHON_ENV_VAR} and "
                    f"{[f'.envs/{n}' for n in CANDIDATE_ENV_NAMES]}. Build .envs/env-tts "
                    "(see docs/INDICF5_INSTALLER.md) or set AARYA_TTS_PYTHON."
                ),
            )
        try:
            response = self._get_worker().call({"mode": "load"}, timeout=LOAD_TIMEOUT_SECONDS)
        except IndicF5WorkerError as exc:
            return GenerationCapabilities(
                backend_state=GenerationBackendState.ERROR,
                compute_backend=ComputeBackend.CPU,
                supported_controls=frozenset(),
                detail=f"Worker failed to start: {exc}",
            )
        if not response.get("ok"):
            return GenerationCapabilities(
                backend_state=GenerationBackendState.ERROR,
                compute_backend=ComputeBackend.CPU,
                supported_controls=frozenset(),
                detail=f"Model failed to load: {response.get('error', 'unknown worker failure')}",
            )
        device = response.get("device", "cpu")
        compute_backend = ComputeBackend.CUDA if device == "cuda" else ComputeBackend.CPU
        # peak_allocated_mib/peak_reserved_mib are the same Phase A VRAM
        # instrumentation already in the worker's response -- surfaced
        # here (text only, no new field/contract) so a capability check
        # alone already reports real measured memory use, not just
        # load_seconds. None on CPU, where there is no VRAM figure.
        memory_detail = ""
        if response.get("peak_reserved_mib") is not None:
            memory_detail = (
                f", peak_allocated={response['peak_allocated_mib']}MiB, "
                f"peak_reserved={response['peak_reserved_mib']}MiB"
            )
        return GenerationCapabilities(
            backend_state=GenerationBackendState.AVAILABLE,
            compute_backend=compute_backend,
            supported_controls=frozenset(),
            detail=f"IndicF5 loaded on {device} (load_seconds={response.get('load_seconds')}{memory_detail}).",
        )

    def validate_request(self, request: dict[str, Any]) -> list[str]:
        errors = []
        text = request.get("text", "")
        if not text or not text.strip():
            errors.append("text must not be empty")
        elif len(text) > MAX_TEXT_LENGTH:
            errors.append(f"text exceeds {MAX_TEXT_LENGTH} characters")
        if self._tts_python is None:
            errors.append(f"{self.name} is not configured: no TTS interpreter found")
        return errors

    def estimate_requirements(self, request: dict[str, Any]) -> dict[str, Any]:
        text = request.get("text", "") or ""
        return {
            "word_count": len(text.split()),
            "character_count": len(text),
            "estimate_basis": (
                "no measured duration model exists for this provider yet -- generation wall-clock time "
                "on this GPU is dominated by NFE diffusion steps, not text length alone"
            ),
        }

    def supports_regeneration(self) -> bool:
        return True

    def generate_preview(self, request: dict[str, Any]) -> PreviewArtifact:
        errors = self.validate_request(request)
        if errors:
            raise GenerationBlockedError("; ".join(errors))

        request_id = request["request_id"]
        text = request["text"]

        destination = self._data_root.previews / f"{request_id}.wav"
        assert_source_writable(self._data_root, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise GenerationBlockedError(f"a preview already exists at {destination.name}; refusing to overwrite")

        worker_request: dict[str, Any] = {
            "mode": "generate",
            "text": text,
            "ref_text": self._ref_text,
            "output_path": str(destination),
        }
        if self._ref_audio_path is not None:
            worker_request["ref_audio_path"] = str(self._ref_audio_path)
        else:
            worker_request["ref_audio_repo_filename"] = self._ref_audio_repo_filename
            worker_request["repo_id"] = self._repo_id

        try:
            response = self._get_worker().call(worker_request, timeout=GENERATE_TIMEOUT_SECONDS)
        except IndicF5WorkerError as exc:
            raise GenerationBlockedError(f"{self.name}: {exc}") from exc

        if not response.get("ok"):
            raise GenerationBlockedError(f"{self.name}: {response.get('error', 'unknown worker failure')}")

        return PreviewArtifact(
            preview_id=f"{request_id}-preview",
            kind=PreviewKind.GENERATED_SPEECH,
            relative_path=f"previews/{destination.name}",
            sha256=sha256_file(destination),
            duration_seconds=response["duration_seconds"],
            sample_rate=response["sample_rate"],
            origin_id=request_id,
            model_name=self.name,
            model_version=self.version,
            is_synthetic=False,
        )

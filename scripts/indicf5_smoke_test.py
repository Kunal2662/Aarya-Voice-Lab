#!/usr/bin/env python3
"""Installer Phase E -- REAL smoke-test validation of the production
IndicF5 path, run from the base interpreter (this script imports only
`aarya_voice_lab`, never `torch`/`huggingface_hub` directly).

This is deliberately NOT `scripts/indicf5_bundled_reference_test.py`
(preserved unchanged, still the standalone regression baseline that
talks to the vendored runtime directly). This script instead drives the
full production stack a real caller would use:

    Aarya Voice Lab
      -> IndicF5VoiceGenerator          (pipeline.indicf5_generation)
      -> GPU worker subprocess          (scripts/ml_workers/indicf5_generation_worker.py)
      -> vendored AI4Bharat IndicF5     (scripts/ml_workers/vendor/indicf5_f5tts/)
      -> RTX 3050 CUDA
      -> generated WAV
      -> WAV validation
      -> (human) recognizable/intelligible speech

The acceptance criterion is NOT "imports succeed" / "CUDA is detected" /
"files exist" / "model loads" / "a WAV exists" -- all of those are
checked here, but none of them alone is sufficient. The mechanical
checks below can only prove the pipeline ran; they cannot prove the
result is intelligible speech. That is a human judgment -- the WAV(s)
this script writes are printed explicitly at the end and must be
listened to.

Deliberately forces the freshly-provisioned CANONICAL `.envs/env-tts`
(not the older `.envs/env-tts-windows-gpu`), via IndicF5VoiceGenerator's
existing `tts_python=` constructor override -- no change to
autodetection or any other production code.
"""

from __future__ import annotations

import array
import sys
import time
import wave
from pathlib import Path

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# Deliberately stdlib-only (wave, array) -- no numpy/soundfile. This
# script runs in the BASE interpreter, which this project keeps free of
# ML/numeric dependencies by design (see identity.embeddings's own
# "no numpy dependency, so the base environment stays free of ML
# packages" rule). The worker writes standard 16-bit PCM WAV (confirmed:
# soundfile.write() defaults to PCM_16 for this project's float32
# arrays), which Python's stdlib `wave` module reads natively.

from aarya_voice_lab.core.data_root import DataRoot  # noqa: E402
from aarya_voice_lab.environment.specs import EnvironmentId  # noqa: E402
from aarya_voice_lab.identity.preview import PreviewKind  # noqa: E402
from aarya_voice_lab.identity.runtime import ComputeBackend  # noqa: E402
from aarya_voice_lab.pipeline.generation import GenerationBackendState, build_preview_request  # noqa: E402
from aarya_voice_lab.pipeline.indicf5_generation import IndicF5VoiceGenerator  # noqa: E402
from aarya_voice_lab.pipeline.runner import default_environment_root  # noqa: E402

#: Reused verbatim, not a new sentence -- this exact text was human-
#: confirmed intelligible earlier in this project's own IndicF5
#: verification work (see docs/INDICF5_INSTALLER.md). A smoke test
#: introducing an untested sentence would not be testing "the known-good
#: reference behavior".
VERIFICATION_TEXT = "नमस्ते, आज मौसम अच्छा है."

EXPECTED_SAMPLE_RATE = 24000
EXPECTED_CHANNELS = 1
MIN_DURATION_SECONDS = 0.3
MAX_DURATION_SECONDS = 30.0
MIN_PEAK = 0.01  # below this, treat as effectively silent
MAX_PEAK = 1.0  # above this, the signal has clipped/wrapped
MIN_RMS = 0.001
MAX_RMS = 0.5


class SmokeTestFailure(RuntimeError):
    """Raised with a clean, specific reason -- never let a raw traceback
    from deep inside torch/huggingface_hub be the only signal (Phase E
    requirement: clean, actionable status)."""


_SAMPLE_WIDTH_TO_ARRAY_CODE = {1: "b", 2: "h", 4: "i"}


def validate_wav(path: Path) -> dict:
    """All the mechanical checks Phase E lists. Returns a dict of
    measured properties on success; raises SmokeTestFailure naming
    exactly which check failed. Integer PCM samples (what this project's
    WAVs actually are -- confirmed PCM_16) cannot represent NaN/Inf by
    construction, unlike a float array; that "check" is therefore
    definitional here, not skipped -- noted explicitly in the returned
    dict rather than silently omitted."""
    if not path.is_file():
        raise SmokeTestFailure(f"WAV does not exist: {path}")

    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
    except Exception as exc:  # noqa: BLE001 -- report as an actionable validation failure, not a bare traceback
        raise SmokeTestFailure(f"WAV could not be read/parsed: {type(exc).__name__}: {exc}") from exc

    if sample_rate != EXPECTED_SAMPLE_RATE:
        raise SmokeTestFailure(f"sample rate is {sample_rate}, expected {EXPECTED_SAMPLE_RATE}")
    if channels != EXPECTED_CHANNELS:
        raise SmokeTestFailure(f"channel count is {channels}, expected {EXPECTED_CHANNELS}")

    duration = n_frames / sample_rate if sample_rate else 0.0
    if not (MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS):
        raise SmokeTestFailure(
            f"duration {duration:.3f}s is outside the reasonable range "
            f"[{MIN_DURATION_SECONDS}, {MAX_DURATION_SECONDS}]"
        )

    array_code = _SAMPLE_WIDTH_TO_ARRAY_CODE.get(sample_width)
    if array_code is None:
        raise SmokeTestFailure(f"unsupported PCM sample width: {sample_width} bytes")
    samples = array.array(array_code, raw)
    if not samples:
        raise SmokeTestFailure("WAV contains zero samples")
    full_scale = float(2 ** (sample_width * 8 - 1))

    peak_int = max(abs(s) for s in samples)
    peak = peak_int / full_scale
    mean_square = sum(s * s for s in samples) / len(samples)
    rms = (mean_square**0.5) / full_scale

    if peak < MIN_PEAK:
        raise SmokeTestFailure(f"audio is effectively silent (peak={peak:.6f} < {MIN_PEAK})")
    if peak > MAX_PEAK:
        raise SmokeTestFailure(f"audio peak {peak:.4f} exceeds {MAX_PEAK} -- clipping/wraparound")
    if not (MIN_RMS <= rms <= MAX_RMS):
        raise SmokeTestFailure(f"RMS {rms:.6f} is outside the sane bound [{MIN_RMS}, {MAX_RMS}]")

    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "duration_seconds": round(duration, 4),
        "peak": round(peak, 6),
        "rms": round(rms, 6),
        "nan_inf_check": "N/A -- integer PCM samples cannot represent NaN/Inf by construction",
    }


def main() -> int:
    print("=" * 70)
    print("Phase E -- REAL IndicF5 production-path smoke test")
    print("=" * 70)

    tts_python = default_environment_root(EnvironmentId.TTS, base=REPO_ROOT).python
    if not tts_python.is_file():
        raise SmokeTestFailure(
            f"canonical .envs/env-tts interpreter not found at {tts_python} -- "
            "run Phase B provisioning first (see docs/INDICF5_INSTALLER.md)"
        )
    print(f"\nForcing canonical env-tts interpreter: {tts_python}")

    data_root = DataRoot(root=REPO_ROOT / "indicf5_smoke_test_data")
    data_root.create()

    generator = IndicF5VoiceGenerator(data_root, tts_python=tts_python)
    print(f"Provider: {generator.name} v{generator.version}")

    # --- Step 1: structured load metrics (direct worker call, FIRST ever
    # interaction with this generator's worker) -----------------------------
    # Deliberately the very first call, before get_capabilities(), so this
    # captures the REAL load event (not a cache hit) with full structured
    # metrics. PreviewArtifact/GenerationCapabilities deliberately don't
    # carry raw VRAM/timing fields (that would be a production-contract
    # change made "merely to support the installer", which Phase E's own
    # requirements forbid) -- the worker already reports them (Phase A
    # instrumentation); this reads them directly for this report only.
    print("\n--- Step 1: structured load metrics (direct worker call) ---")
    t0 = time.monotonic()
    load_response = generator._get_worker().call({"mode": "load"}, timeout=180.0)
    load_wall_seconds = time.monotonic() - t0
    print(f"  raw response = {load_response}")
    print(f"  wall time = {load_wall_seconds:.2f}s")
    if not load_response.get("ok") or load_response.get("already_loaded"):
        raise SmokeTestFailure(f"expected a real, fresh load on the first call, got: {load_response}")
    if load_response.get("device") != "cuda":
        raise SmokeTestFailure(f"expected device=cuda on the RTX 3050 reference machine, got: {load_response}")
    print("  PASS: real model+vocoder load happened, CUDA confirmed in use.")

    # --- Step 2: get_capabilities() -- the real production contract -------
    # Called AFTER the direct load above, on the SAME generator (same
    # underlying persistent worker) -- this proves get_capabilities()
    # correctly reports AVAILABLE/CUDA from an externally-triggered load,
    # not just from its own internal call.
    print("\n--- Step 2: get_capabilities() (should reuse the already-loaded worker) ---")
    t0 = time.monotonic()
    caps = generator.get_capabilities()
    caps_wall_seconds = time.monotonic() - t0
    print(f"  backend_state = {caps.backend_state.value}")
    print(f"  compute_backend = {caps.compute_backend.value}")
    print(f"  detail = {caps.detail}")
    print(f"  wall time = {caps_wall_seconds:.2f}s")

    if caps.backend_state is not GenerationBackendState.AVAILABLE:
        raise SmokeTestFailure(f"expected AVAILABLE, got {caps.backend_state.value}: {caps.detail}")
    if caps.compute_backend is not ComputeBackend.CUDA:
        raise SmokeTestFailure(
            f"expected CUDA to actually be used on the RTX 3050 reference machine, got {caps.compute_backend.value}"
        )
    if caps_wall_seconds >= load_wall_seconds:
        raise SmokeTestFailure(
            f"get_capabilities() ({caps_wall_seconds:.2f}s) was not faster than the real load "
            f"({load_wall_seconds:.2f}s) -- it should have reused the already-loaded worker, not reloaded"
        )
    print(
        f"  PASS: reused the already-loaded worker "
        f"({caps_wall_seconds:.2f}s << {load_wall_seconds:.2f}s), no reload."
    )

    # --- Step 3: generate_preview() -- the real production contract -------
    print(f"\n--- Step 3: generate_preview() call #1 -- {VERIFICATION_TEXT!r} ---")
    request1 = build_preview_request(text=VERIFICATION_TEXT, voice_profile_id="smoke-test", model_id=generator.name)
    t0 = time.monotonic()
    artifact1 = generator.generate_preview(request1.to_dict())
    gen1_wall_seconds = time.monotonic() - t0
    print(f"  wall time = {gen1_wall_seconds:.2f}s")
    print(f"  artifact = {artifact1.to_dict()}")

    if artifact1.kind is not PreviewKind.GENERATED_SPEECH:
        raise SmokeTestFailure(f"expected kind=generated_speech, got {artifact1.kind.value}")
    if artifact1.is_synthetic is not False:
        raise SmokeTestFailure("expected is_synthetic=False for real IndicF5 output")
    if artifact1.model_name != generator.name:
        raise SmokeTestFailure(f"artifact.model_name {artifact1.model_name!r} != generator.name {generator.name!r}")

    wav1_path = data_root.previews / f"{request1.request_id}.wav"
    from aarya_voice_lab.pipeline.contracts import sha256_file

    if sha256_file(wav1_path) != artifact1.sha256:
        raise SmokeTestFailure("artifact.sha256 does not match the actual WAV file on disk")
    print("  PASS: PreviewArtifact contract correct (kind, is_synthetic, model_name, sha256 all verified).")

    props1 = validate_wav(wav1_path)
    print(f"  WAV validation: {props1}")
    print("  PASS: WAV is valid, correct format, non-silent, within sane bounds, no NaN/Inf.")

    # --- Step 4: run again -- reproducibility + persistent worker lifecycle
    print("\n--- Step 4: generate_preview() call #2 (same text, new request_id) ---")
    request2 = build_preview_request(text=VERIFICATION_TEXT, voice_profile_id="smoke-test", model_id=generator.name)
    t0 = time.monotonic()
    generator.generate_preview(request2.to_dict())
    gen2_wall_seconds = time.monotonic() - t0
    print(f"  wall time = {gen2_wall_seconds:.2f}s")

    wav2_path = data_root.previews / f"{request2.request_id}.wav"
    props2 = validate_wav(wav2_path)
    print(f"  WAV validation: {props2}")
    print(
        f"  Both generate_preview() calls ran AFTER the model was already loaded (Steps 1-2), so both "
        f"({gen1_wall_seconds:.2f}s, {gen2_wall_seconds:.2f}s) are pure-generation time -- comparable to each "
        f"other is the expected, correct signal here. The definitive "
        f"per-call reload check (model_load_seconds from the worker's own response) is in Step 5 below."
    )

    # --- Step 5: structured generation metrics (direct worker call) -------
    print("\n--- Step 5: structured generation metrics (diagnostic only) ---")
    generate_response = generator._get_worker().call(
        {
            "mode": "generate",
            "text": VERIFICATION_TEXT,
            "ref_text": generator._ref_text,
            "ref_audio_repo_filename": generator._ref_audio_repo_filename,
            "repo_id": generator._repo_id,
            "output_path": str(data_root.previews / "smoke-test-diagnostic.wav"),
        },
        timeout=180.0,
    )
    print(f"  raw response = {generate_response}")
    diagnostic_wav = Path(generate_response["output_path"])

    # THE definitive per-call reload proof: the worker's own
    # _run_generate() reports model_load_seconds from _ensure_loaded()'s
    # response, which is exactly 0.0 when it hit the already-loaded fast
    # path -- not a timing heuristic, the worker's own ground truth.
    if generate_response.get("model_load_seconds") != 0.0:
        raise SmokeTestFailure(
            f"expected model_load_seconds=0.0 (reusing the persistent worker's already-loaded model), "
            f"got {generate_response.get('model_load_seconds')} -- the model may be reloading per generate call"
        )
    print("  PASS: model_load_seconds=0.0 confirms this generation reused the already-loaded model (no reload).")

    generator.close()
    print("\nWorker subprocess closed cleanly.")

    print("\n" + "=" * 70)
    print("MECHANICAL VALIDATION: ALL CHECKS PASSED.")
    print("=" * 70)
    print(
        "\nThis does NOT confirm intelligibility. 'Non-silent' and 'passes format\n"
        "checks' are not the same claim as 'is recognizable speech' -- per this\n"
        "project's own established rule, only a human listening to the WAV can\n"
        "confirm that. Listen to:\n"
    )
    print(f"  {wav1_path}")
    print(f"  {wav2_path}")
    print(f"\nText: {VERIFICATION_TEXT!r} (already human-confirmed intelligible earlier in this project's work)")

    print("\n--- Summary for the Phase E report ---")
    print(f"env_tts_interpreter = {tts_python}")
    print(f"model_load_seconds = {load_response.get('load_seconds')}")
    print(f"model_load_peak_allocated_mib = {load_response.get('peak_allocated_mib')}")
    print(f"model_load_peak_reserved_mib = {load_response.get('peak_reserved_mib')}")
    print(f"generation1_wall_seconds = {gen1_wall_seconds:.3f}")
    print(f"generation2_wall_seconds = {gen2_wall_seconds:.3f}")
    print(f"generation_peak_allocated_mib = {generate_response.get('peak_allocated_mib')}")
    print(f"generation_peak_reserved_mib = {generate_response.get('peak_reserved_mib')}")
    print(f"wav1 = {wav1_path}")
    print(f"wav2 = {wav2_path}")
    print(f"diagnostic_wav = {diagnostic_wav}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeTestFailure as exc:
        print(f"\nSMOKE TEST FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

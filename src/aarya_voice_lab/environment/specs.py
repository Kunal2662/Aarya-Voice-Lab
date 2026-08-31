"""Declarative specifications for the isolated ML environments.

Each spec is data, not behaviour: it names the interpreter, the pinned
packages, the wheel index, whether CPU-only operation is supported, and
which external downloads or credentials the environment would require.

Nothing here installs anything. `scripts/install_env.sh` reads the same
facts, and `aarya-voice nemo-check` / `whisperx-check` verify a built
environment against its spec.

Version choices and the evidence behind the isolation decision are
recorded in docs/COMPATIBILITY.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EnvironmentId(StrEnum):
    BASE = "base"
    NEMO = "env-nemo"
    WHISPERX = "env-whisperx"
    TTS = "env-tts"


class ExternalRequirement(StrEnum):
    """Things an environment needs that are NOT satisfiable from this repo."""

    #: Weights fetched from a public host, no account needed.
    OPEN_MODEL_DOWNLOAD = "open_model_download"
    #: Weights behind an account + acceptance of terms.
    GATED_MODEL_DOWNLOAD = "gated_model_download"
    #: An access token must be supplied by the operator.
    CREDENTIAL = "credential"
    #: A paid/hosted service is involved.
    EXTERNAL_SERVICE = "external_service"
    #: A system package installed outside pip.
    SYSTEM_PACKAGE = "system_package"


@dataclass(frozen=True)
class EnvironmentSpec:
    env_id: EnvironmentId
    purpose: str
    python_version: str
    requirements_file: str
    #: Packages whose versions this env is defined by, for verification.
    expected_packages: dict[str, str] = field(default_factory=dict)
    #: pip index for torch; None means default PyPI.
    torch_index_cpu: str | None = None
    torch_index_cuda: str | None = None
    cpu_supported: bool = True
    cpu_caveat: str = ""
    external_requirements: tuple[ExternalRequirement, ...] = ()
    #: Set when using this environment needs a human decision first.
    requires_approval: str | None = None
    notes: tuple[str, ...] = ()


BASE_SPEC = EnvironmentSpec(
    env_id=EnvironmentId.BASE,
    purpose="Dataset engineering, schemas, manifests, CLI. No ML dependencies.",
    python_version="3.11-3.13 (3.12 recommended)",
    requirements_file="requirements/base.txt",
    expected_packages={"pyyaml": ">=6.0", "jsonschema": ">=4.20", "psutil": ">=5.9"},
    cpu_supported=True,
    notes=("This is the only environment Phase 0/1 actually installs.",),
)

NEMO_SPEC = EnvironmentSpec(
    env_id=EnvironmentId.NEMO,
    purpose="Speaker diarization via NVIDIA NeMo / Sortformer (primary system).",
    python_version="3.12",
    requirements_file="requirements/diarization.txt",
    expected_packages={"nemo_toolkit": "3.0.0", "torch": "2.13.0"},
    torch_index_cpu="https://download.pytorch.org/whl/cpu",
    torch_index_cuda="https://download.pytorch.org/whl/cu130",
    cpu_supported=True,
    cpu_caveat=(
        "Sortformer inference runs on CPU but is substantially slower; "
        "practical for 31 recordings, not for large corpora."
    ),
    external_requirements=(ExternalRequirement.OPEN_MODEL_DOWNLOAD,),
    notes=(
        "Sortformer checkpoints are NOT gated: no token or account required.",
        "Install torch FIRST from the index matching the detected driver.",
        "Telemetry packages ship with NeMo and must be disabled — see "
        "docs/NEMO.md and scripts/disable_telemetry.sh.",
    ),
)

WHISPERX_SPEC = EnvironmentSpec(
    env_id=EnvironmentId.WHISPERX,
    purpose="Transcription and word alignment; candidate independent verification.",
    python_version="3.12",
    requirements_file="requirements/transcription.txt",
    expected_packages={"whisperx": "3.8.6", "torch": "2.8.0"},
    torch_index_cpu="https://download.pytorch.org/whl/cpu",
    torch_index_cuda="https://download.pytorch.org/whl/cu126",
    cpu_supported=True,
    cpu_caveat="Whisper on CPU is slow; use a smaller model size or a GPU machine.",
    external_requirements=(
        ExternalRequirement.OPEN_MODEL_DOWNLOAD,
        ExternalRequirement.GATED_MODEL_DOWNLOAD,
        ExternalRequirement.CREDENTIAL,
        ExternalRequirement.SYSTEM_PACKAGE,
    ),
    requires_approval=(
        "Installing whisperx transitively installs pyannote.audio AND "
        "pyannoteai-sdk (a commercial API client). pyannote's diarization "
        "pipeline is a GATED HuggingFace model requiring a token and "
        "acceptance of a contact-sharing agreement. Transcription-only use "
        "avoids the gate; diarization use does not. Requires sign-off."
    ),
    notes=(
        "Requires FFmpeg (system package).",
        "torch is capped at ~2.8.0 by whisperx; this is why it is isolated.",
    ),
)

TTS_SPEC = EnvironmentSpec(
    env_id=EnvironmentId.TTS,
    purpose=(
        "AI4Bharat IndicF5 text-to-speech — selected and verified end-to-end "
        "(real CUDA generation, human-confirmed intelligible speech). "
        "See docs/INDICF5_INSTALLER.md."
    ),
    python_version="3.12",
    requirements_file="requirements/tts.txt",
    # The two version-sensitive pins verified end-to-end together; the
    # full exact-pinned dependency set lives in requirements/tts.txt.
    expected_packages={"torch": "2.13.0", "torchaudio": "2.11.0", "transformers": "4.49.0"},
    torch_index_cpu="https://download.pytorch.org/whl/cpu",
    # cu126, not cu130 (PyTorch 2.13's own default index) — this is the
    # exact index the verified reference install actually used. cu130 has
    # never been tested against this model and is not assumed equivalent.
    torch_index_cuda="https://download.pytorch.org/whl/cu126",
    cpu_supported=True,
    cpu_caveat=(
        "CPU execution is code-supported (IndicF5's own inference path falls back to CPU when CUDA is "
        "unavailable) but UNVERIFIED for this model and NOT advertised as production-viable — treat as "
        "experimental/very slow until a real CPU timing measurement is performed. See docs/INDICF5_INSTALLER.md."
    ),
    # Confirmed empirically, not assumed: anonymous hf_hub_download against
    # ai4bharat/IndicF5 returns a 401 GatedRepoError. A HuggingFace account
    # with the model's access request approved, and a valid token, are
    # required before the checkpoint can be downloaded.
    external_requirements=(ExternalRequirement.GATED_MODEL_DOWNLOAD, ExternalRequirement.CREDENTIAL),
    # Retired for this environment specifically: the reason this gate
    # existed ("no TTS model has been selected") is no longer true —
    # IndicF5 is selected and verified. Approval semantics are preserved
    # for env-whisperx (WHISPERX_SPEC.requires_approval), which still
    # carries a real, unresolved gate (a third-party account + a gated,
    # contact-sharing-agreement model).
    requires_approval=None,
    notes=(
        "Do NOT `pip install f5-tts` — IndicF5's checkpoint was trained against an older F5-TTS than "
        "PyPI ships today; loading succeeds but generation produces unintelligible audio. The verified "
        "implementation is vendored at scripts/ml_workers/vendor/indicf5_f5tts/ (AI4Bharat's own bundled "
        "source, not the PyPI package) — requirements/tts.txt installs only its underlying dependencies.",
        "trust_remote_code=True is NOT used anywhere in this project's IndicF5 path — the model is built "
        "directly from the vendored library code and loads only tensor weights via safetensors.",
        "ai4bharat/IndicF5 is a GATED HuggingFace repository — see external_requirements above and "
        "docs/INDICF5_INSTALLER.md for the credential flow.",
        "GPU VRAM capability tiers (measured, not guessed) are checked separately — see "
        "environment.audit.check_indicf5_vram_tier() and docs/INDICF5_INSTALLER.md.",
    ),
)

ENVIRONMENT_SPECS: dict[EnvironmentId, EnvironmentSpec] = {
    spec.env_id: spec for spec in (BASE_SPEC, NEMO_SPEC, WHISPERX_SPEC, TTS_SPEC)
}


def get_spec(env_id: EnvironmentId | str) -> EnvironmentSpec:
    return ENVIRONMENT_SPECS[EnvironmentId(env_id)]


def specs_requiring_approval() -> list[EnvironmentSpec]:
    return [spec for spec in ENVIRONMENT_SPECS.values() if spec.requires_approval]


def specs_requiring_credentials() -> list[EnvironmentSpec]:
    return [
        spec
        for spec in ENVIRONMENT_SPECS.values()
        if ExternalRequirement.CREDENTIAL in spec.external_requirements
        or ExternalRequirement.GATED_MODEL_DOWNLOAD in spec.external_requirements
    ]

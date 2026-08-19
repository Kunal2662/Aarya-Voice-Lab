"""TTS candidate matrix with license audit.

Machine-readable so the CLI, tests, and docs share one source of truth
and cannot drift. NO CANDIDATE IS SELECTED — this records evaluation
inputs, not a decision. Selection is deferred beyond Phase 1.

Every entry carries licensing as a first-class field because licensing is
a hard filter here: several capable models are unusable on license terms
alone, regardless of quality. `verdict` reflects that filter, not audio
quality — none of these has been listened to, and no benchmark has run.

Facts verified against PyPI metadata, model cards, and project READMEs on
2026-08-19. Re-verify before acting: licenses and gating change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CandidateVerdict(StrEnum):
    #: Meets the hard filters; worth evaluating further.
    CANDIDATE = "candidate"
    #: Fails a hard filter (license or language). Not to be installed.
    REJECTED = "rejected"
    #: Usable for the Default Voice only (cannot clone).
    DEFAULT_VOICE_ONLY = "default_voice_only"


class CommercialUse(StrEnum):
    PERMITTED = "permitted"
    PROHIBITED = "prohibited"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class TTSCandidate:
    name: str
    code_license: str
    weights_license: str
    commercial_use: CommercialUse
    languages: tuple[str, ...]
    marathi_support: bool
    reference_voice_cloning: bool
    cpu_capable: bool
    gpu_required: bool
    approx_vram_gb: float | None
    approx_model_size: str | None
    verdict: CandidateVerdict
    #: Why the verdict, in one line.
    rationale: str
    attribution_required: bool = False
    redistribution_restricted: bool = False
    training_data_documented: bool = False
    gated_download: bool = False
    known_limitations: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "code_license": self.code_license,
            "weights_license": self.weights_license,
            "commercial_use": self.commercial_use.value,
            "languages": list(self.languages),
            "marathi_support": self.marathi_support,
            "reference_voice_cloning": self.reference_voice_cloning,
            "cpu_capable": self.cpu_capable,
            "gpu_required": self.gpu_required,
            "approx_vram_gb": self.approx_vram_gb,
            "approx_model_size": self.approx_model_size,
            "verdict": self.verdict.value,
            "rationale": self.rationale,
            "attribution_required": self.attribution_required,
            "redistribution_restricted": self.redistribution_restricted,
            "training_data_documented": self.training_data_documented,
            "gated_download": self.gated_download,
            "known_limitations": list(self.known_limitations),
            "notes": list(self.notes),
        }


INDIC_F5 = TTSCandidate(
    name="AI4Bharat IndicF5",
    code_license="MIT",
    weights_license="MIT",
    commercial_use=CommercialUse.PERMITTED,
    languages=("mr", "hi", "bn", "gu", "kn", "ml", "or", "pa", "ta", "te", "as"),
    marathi_support=True,
    reference_voice_cloning=True,
    cpu_capable=True,
    gpu_required=False,
    approx_vram_gb=None,
    approx_model_size="F5-TTS architecture (~300M class)",
    verdict=CandidateVerdict.CANDIDATE,
    rationale="Only audited option combining MIT weights, Marathi, and reference-based cloning.",
    training_data_documented=True,
    gated_download=True,
    known_limitations=(
        "HF repo is gated: requires accepting a contact-sharing agreement (license itself is MIT).",
        "Loads with trust_remote_code=True — executes arbitrary code from the model repo.",
        "Exact dependency pins are not published; resolution untested.",
        "VRAM/latency characteristics not measured by this project.",
    ),
    notes=(
        "Trained on Rasa, IndicTTS, LIMMITS, IndicVoices-R (~1417h).",
        "Model card requires that you only clone voices you have permission to clone.",
    ),
)

INDIC_PARLER_TTS = TTSCandidate(
    name="AI4Bharat Indic Parler-TTS",
    code_license="Apache-2.0",
    weights_license="Apache-2.0",
    commercial_use=CommercialUse.PERMITTED,
    languages=("mr", "hi", "en", "bn", "gu", "kn", "ml", "or", "pa", "ta", "te"),
    marathi_support=True,
    reference_voice_cloning=False,
    cpu_capable=True,
    gpu_required=False,
    approx_vram_gb=None,
    approx_model_size="~880M",
    verdict=CandidateVerdict.DEFAULT_VOICE_ONLY,
    rationale="Cleanest license of any option, but cannot clone a voice — unusable for the Private Voice.",
    training_data_documented=True,
    known_limitations=(
        "Voice is steered by a text description, not a reference sample.",
        "Not published on PyPI: installed from git, so no resolvable version pin.",
    ),
    notes=("21 languages; strongest license position for a distributable Default Voice.",),
)

PIPER = TTSCandidate(
    name="Piper",
    code_license="GPL-3.0-or-later (piper1-gpl)",
    weights_license="per-voice (varies)",
    commercial_use=CommercialUse.UNCLEAR,
    languages=("mr", "hi", "en", "many"),
    marathi_support=True,
    reference_voice_cloning=False,
    cpu_capable=True,
    gpu_required=False,
    approx_vram_gb=0.0,
    approx_model_size="~20-60 MB per voice (ONNX)",
    verdict=CandidateVerdict.DEFAULT_VOICE_ONLY,
    rationale="CPU-only baseline with near-zero dependency risk, but no cloning.",
    attribution_required=True,
    redistribution_restricted=True,
    known_limitations=(
        "Cannot clone; a new voice requires finetuning.",
        "GPL-3.0-or-later on the current package is a distribution consideration.",
        "Per-voice weight licenses vary and must be checked individually.",
        "Specific mr_IN voice names/quality not verified by this project.",
    ),
    notes=("Only option needing no torch at inference — useful as a pipeline smoke test.",),
)

XTTS_V2 = TTSCandidate(
    name="Coqui XTTS-v2",
    code_license="MPL-2.0 (idiap/coqui-ai-TTS fork)",
    weights_license="CPML (non-commercial)",
    commercial_use=CommercialUse.PROHIBITED,
    languages=("hi", "en", "es", "fr", "de", "and 12 more"),
    marathi_support=False,
    reference_voice_cloning=True,
    cpu_capable=True,
    gpu_required=False,
    approx_vram_gb=4.0,
    approx_model_size="~1.8 GB",
    verdict=CandidateVerdict.REJECTED,
    rationale="Non-commercial weights with no licensor able to grant other terms, AND no Marathi.",
    redistribution_restricted=True,
    known_limitations=(
        "Coqui Inc. dissolved in Jan 2024 — no entity can issue a commercial license.",
        "Marathi is absent from its 17 languages (Hindi is present).",
    ),
    notes=("Commonly recommended online; both hard filters fail. Do not reach for it by default.",),
)

F5_TTS_BASE = TTSCandidate(
    name="F5-TTS (base checkpoints)",
    code_license="MIT",
    weights_license="CC-BY-NC-4.0 (non-commercial)",
    commercial_use=CommercialUse.PROHIBITED,
    languages=("en", "zh"),
    marathi_support=False,
    reference_voice_cloning=True,
    cpu_capable=True,
    gpu_required=False,
    approx_vram_gb=None,
    approx_model_size="~1.2 GB",
    verdict=CandidateVerdict.REJECTED,
    rationale="Non-commercial base weights and no Indic coverage; IndicF5 is the MIT-licensed Indic finetune.",
    attribution_required=True,
    known_limitations=("Base model covers English/Chinese only.",),
)

FISH_SPEECH = TTSCandidate(
    name="Fish Speech / OpenAudio",
    code_license="research-only (current release)",
    weights_license="research-only / CC-BY-NC-SA-4.0 (earlier)",
    commercial_use=CommercialUse.PROHIBITED,
    languages=("en", "zh", "ja", "and others"),
    marathi_support=False,
    reference_voice_cloning=True,
    cpu_capable=False,
    gpu_required=True,
    approx_vram_gb=8.0,
    approx_model_size="4B (S2 Pro)",
    verdict=CandidateVerdict.REJECTED,
    rationale="Research-only license covering code AND weights; no Marathi.",
    redistribution_restricted=True,
    known_limitations=(
        "PyPI package is a stale 0.1.0 pinning numpy<=1.26.4, conflicting with the rest of the stack.",
    ),
)

TTS_CANDIDATES: tuple[TTSCandidate, ...] = (
    INDIC_F5,
    INDIC_PARLER_TTS,
    PIPER,
    XTTS_V2,
    F5_TTS_BASE,
    FISH_SPEECH,
)


def private_voice_candidates() -> list[TTSCandidate]:
    """Candidates that could serve the Private Voice: cloning + Marathi + usable license."""
    return [
        c
        for c in TTS_CANDIDATES
        if c.verdict is CandidateVerdict.CANDIDATE
        and c.reference_voice_cloning
        and c.marathi_support
        and c.commercial_use is not CommercialUse.PROHIBITED
    ]


def rejected_candidates() -> list[TTSCandidate]:
    return [c for c in TTS_CANDIDATES if c.verdict is CandidateVerdict.REJECTED]


def candidates_with_unclear_licensing() -> list[TTSCandidate]:
    return [c for c in TTS_CANDIDATES if c.commercial_use is CommercialUse.UNCLEAR]

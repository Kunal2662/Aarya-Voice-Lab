"""Phase E -- real, capability-gated smoke test for the full IndicF5
production path, run through pytest (not just the standalone
`scripts/indicf5_smoke_test.py`, which has the detailed step-by-step
report this file does not duplicate).

Mirrors `test_hf_auth.py`/`test_indicf5_provisioning.py`/
`test_voice_model_engine.py`'s real-integration-test convention exactly:
skips (not fails) when `.envs/env-tts` is not built in this environment,
runs for real against actual CUDA hardware when it is. This is
deliberately forced onto the CANONICAL `.envs/env-tts` (via
`IndicF5VoiceGenerator`'s existing `tts_python=` constructor override),
never the older `.envs/env-tts-windows-gpu`.

This test intentionally does NOT assert intelligibility -- only a human
can confirm that (see `scripts/indicf5_smoke_test.py` and
`docs/INDICF5_INSTALLER.md`'s Phase E record for the human-verified
result). It asserts everything mechanically checkable: the production
contract, WAV validity, and CUDA actually being used.
"""

from __future__ import annotations

import wave

import pytest

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.environment.specs import EnvironmentId
from aarya_voice_lab.identity.preview import PreviewKind
from aarya_voice_lab.identity.runtime import ComputeBackend
from aarya_voice_lab.pipeline.contracts import sha256_file
from aarya_voice_lab.pipeline.generation import GenerationBackendState, build_preview_request
from aarya_voice_lab.pipeline.indicf5_generation import IndicF5VoiceGenerator
from aarya_voice_lab.pipeline.runner import default_environment_root

#: Same sentence scripts/indicf5_smoke_test.py uses -- already
#: human-confirmed intelligible earlier in this project's work, not a
#: new, untested sentence.
VERIFICATION_TEXT = "नमस्ते, आज मौसम अच्छा है."


def _canonical_env_tts_python():
    from aarya_voice_lab.core.paths import PROJECT_ROOT

    paths = default_environment_root(EnvironmentId.TTS, base=PROJECT_ROOT)
    return paths.python if paths.exists() else None


def test_real_production_path_end_to_end(tmp_path):
    tts_python = _canonical_env_tts_python()
    if tts_python is None:
        pytest.skip("`.envs/env-tts` is not built in this environment -- see docs/INDICF5_INSTALLER.md")

    data_root = DataRoot(root=tmp_path / "data")
    data_root.create()
    generator = IndicF5VoiceGenerator(data_root, tts_python=tts_python)
    try:
        caps = generator.get_capabilities()
        assert caps.backend_state is GenerationBackendState.AVAILABLE, caps.detail
        assert caps.compute_backend is ComputeBackend.CUDA, (
            f"expected CUDA on the RTX 3050 reference machine, got {caps.compute_backend.value}"
        )

        request = build_preview_request(
            text=VERIFICATION_TEXT, voice_profile_id="pytest-smoke", model_id=generator.name
        )
        artifact = generator.generate_preview(request.to_dict())

        # Production contract.
        assert artifact.kind is PreviewKind.GENERATED_SPEECH
        assert artifact.is_synthetic is False
        assert artifact.model_name == generator.name
        wav_path = data_root.previews / f"{request.request_id}.wav"
        assert sha256_file(wav_path) == artifact.sha256

        # WAV validity (stdlib wave only -- this test runs in the base
        # interpreter, which stays free of numpy/soundfile by design).
        with wave.open(str(wav_path), "rb") as wf:
            assert wf.getframerate() == 24000
            assert wf.getnchannels() == 1
            n_frames = wf.getnframes()
            duration = n_frames / wf.getframerate()
            assert 0.3 <= duration <= 30.0
            import array

            samples = array.array("h", wf.readframes(n_frames))
        assert samples, "WAV contains zero samples"
        peak = max(abs(s) for s in samples) / 32768.0
        assert peak > 0.01, f"audio is effectively silent (peak={peak})"
        assert peak <= 1.0, f"audio peak {peak} indicates clipping"
    finally:
        generator.close()

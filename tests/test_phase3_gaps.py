"""Phase 3 cases the earlier suites did not cover.

Closes the gaps found in the Phase 3 gap analysis:

* invalid embedding (spec §13.5)
* configuration mismatch (§13.7)
* provenance mismatch (§13.8)
* local-first / no-cloud guarantees (§18, §22)
* hardware-agnostic architecture (§14)
* Claude Code Command Center contracts (§20)

Everything here is synthetic. No real recording, embedding, or model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.identity import command_center, contracts
from aarya_voice_lab.identity.calibration import (
    CalibrationEvidence,
    CalibrationRecord,
    CalibrationState,
    ThresholdConfig,
    uncalibrated,
)
from aarya_voice_lab.identity.embeddings import (
    EmbeddingProviderError,
    EmbeddingStore,
    EmbeddingVector,
    ProviderKind,
    SyntheticEmbeddingProvider,
    cosine_similarity,
)
from aarya_voice_lab.identity.enrollment import EnrollmentEngine, EnrollmentSample, get_strategy
from aarya_voice_lab.identity.profile import ProfileStore, SpeakerRole
from aarya_voice_lab.identity.runtime import (
    ACCELERATOR_BACKENDS,
    AccelerationRequirement,
    ComputeBackend,
    RuntimeCapability,
    describe_portability,
)
from aarya_voice_lab.identity.verification import VerificationEngine
from aarya_voice_lab.testing.synthetic_audio import generate_speech_like

# Modules that must never reach the network or a cloud provider.
LOCAL_FIRST_PACKAGES = ("identity", "pipeline", "audio", "core", "security")


def _provider() -> SyntheticEmbeddingProvider:
    return SyntheticEmbeddingProvider()


def _embed(path: Path, provider=None):
    from aarya_voice_lab.audio.probe import read_wav_mono_samples

    provider = provider or _provider()
    samples, rate = read_wav_mono_samples(path)
    return provider.embed(samples, rate)


def _enrolled(tmp_path: Path, *, role=SpeakerRole.TARGET_SPEAKER, frequency=180.0):
    data = DataRoot(root=tmp_path / "data").create()
    provider = _provider()
    engine = EnrollmentEngine(provider, data)
    from aarya_voice_lab.audio.probe import read_wav_mono_samples

    samples = []
    for index, offset in enumerate((0.0, 2.0)):
        path = generate_speech_like(
            tmp_path / f"enr{index}.wav", frequency_hz=frequency + offset, duration_seconds=3.0
        )
        pcm, rate = read_wav_mono_samples(path)
        samples.append(
            EnrollmentSample(
                sample_id=f"s{index}",
                samples=pcm,
                sample_rate=rate,
                channel_condition="wideband_16000",
            )
        )
    result = engine.enroll(
        profile_id=f"p-{role.value}",
        role=role,
        strategy=get_strategy("direct_recording"),
        samples=samples,
    )
    return data, provider, result


# ==========================================================================
# §13.5 — invalid embedding
# ==========================================================================


def test_empty_signal_cannot_be_embedded():
    with pytest.raises(EmbeddingProviderError, match="empty"):
        _provider().embed([], 16_000)


def test_invalid_sample_rate_is_refused():
    with pytest.raises(EmbeddingProviderError, match="sample rate"):
        _provider().embed([1, 2, 3], 0)


def test_dimension_mismatch_is_refused():
    """Comparing different-length vectors must raise, not silently pad."""
    a = EmbeddingVector((0.1, 0.2, 0.3), "p", "1", ProviderKind.SYNTHETIC, 16_000, 1.0)
    b = EmbeddingVector((0.1, 0.2), "p", "1", ProviderKind.SYNTHETIC, 16_000, 1.0)
    with pytest.raises(EmbeddingProviderError, match="dimension"):
        cosine_similarity(a, b)


def test_cross_provider_comparison_is_refused():
    """Scores from different providers are not comparable; returning a
    number anyway would invite exactly the false confidence to avoid."""
    a = EmbeddingVector((0.1, 0.2), "provider-a", "1", ProviderKind.SYNTHETIC, 16_000, 1.0)
    b = EmbeddingVector((0.1, 0.2), "provider-b", "1", ProviderKind.SYNTHETIC, 16_000, 1.0)
    with pytest.raises(EmbeddingProviderError, match="different providers"):
        cosine_similarity(a, b)


def test_cross_version_comparison_is_refused():
    a = EmbeddingVector((0.1, 0.2), "p", "1.0.0", ProviderKind.SYNTHETIC, 16_000, 1.0)
    b = EmbeddingVector((0.1, 0.2), "p", "2.0.0", ProviderKind.SYNTHETIC, 16_000, 1.0)
    with pytest.raises(EmbeddingProviderError, match="different providers"):
        cosine_similarity(a, b)


def test_missing_embedding_raises(tmp_path):
    store = EmbeddingStore(DataRoot(root=tmp_path / "data").create())
    with pytest.raises(EmbeddingProviderError, match="not found"):
        store.load("does-not-exist")


def test_corrupted_embedding_fails_integrity_check(tmp_path):
    """A tampered vector must be detected on load, not used silently."""
    data = DataRoot(root=tmp_path / "data").create()
    store = EmbeddingStore(data)
    vector = _embed(generate_speech_like(tmp_path / "a.wav", duration_seconds=2.0))
    store.save("victim", vector)

    path = data.root / "embeddings" / "victim.vec"
    raw = bytearray(path.read_bytes())
    raw[0] ^= 0xFF
    path.write_bytes(bytes(raw))

    with pytest.raises(EmbeddingProviderError, match="integrity"):
        store.load("victim")


def test_verification_with_unusable_profile_is_refused(tmp_path):
    """A superseded profile must not be silently used for scoring."""
    from aarya_voice_lab.identity.profile import ProfileError

    data, provider, enrolled = _enrolled(tmp_path)
    superseded = enrolled.profile.supersede("p-target_speaker@v99")
    engine = VerificationEngine(
        embedding_store=EmbeddingStore(data),
        calibration=uncalibrated(provider.name, provider.version, is_synthetic=True),
        target_profile=superseded,
    )
    with pytest.raises(ProfileError, match="superseded"):
        engine.verify(
            verification_id="v1",
            segment_id="s1",
            candidate=_embed(generate_speech_like(tmp_path / "c.wav", duration_seconds=2.0), provider),
            duration_seconds=2.0,
            overlap_status="NO_OVERLAP_DETECTED",
        )


# ==========================================================================
# §13.7 — configuration mismatch
# ==========================================================================


def test_threshold_change_changes_config_hash():
    assert ThresholdConfig().config_hash() != ThresholdConfig(target_acceptance_threshold=0.9).config_hash()


def test_config_hash_is_order_independent():
    """Same values must hash identically regardless of construction order."""
    a = ThresholdConfig(target_acceptance_threshold=0.9, target_review_threshold=0.6)
    b = ThresholdConfig(target_review_threshold=0.6, target_acceptance_threshold=0.9)
    assert a.config_hash() == b.config_hash()


def test_verification_records_the_thresholds_it_used(tmp_path):
    """A result must name its configuration, so a later change invalidates
    it by fingerprint rather than silently reinterpreting the score."""
    data, provider, enrolled = _enrolled(tmp_path)
    calibration = uncalibrated(provider.name, provider.version, is_synthetic=True)
    engine = VerificationEngine(
        embedding_store=EmbeddingStore(data),
        calibration=calibration,
        target_profile=enrolled.profile,
    )
    result = engine.verify(
        verification_id="v1",
        segment_id="s1",
        candidate=_embed(generate_speech_like(tmp_path / "c.wav", duration_seconds=2.0), provider),
        duration_seconds=2.0,
        overlap_status="NO_OVERLAP_DETECTED",
    )
    assert result.thresholds_hash == calibration.config_hash()


def test_changed_configuration_changes_verification_fingerprint(tmp_path):
    data, provider, enrolled = _enrolled(tmp_path)
    store = EmbeddingStore(data)
    candidate = _embed(generate_speech_like(tmp_path / "c.wav", duration_seconds=2.0), provider)

    fingerprints = []
    for threshold in (0.85, 0.95):
        calibration = CalibrationRecord(
            calibration_id="cal",
            state=CalibrationState.PROVISIONAL,
            evidence=CalibrationEvidence.SYNTHETIC_FIXTURES,
            thresholds=ThresholdConfig(target_acceptance_threshold=threshold),
            provider_name=provider.name,
            provider_version=provider.version,
            provider_is_synthetic=True,
            limitations=["synthetic"],
        )
        engine = VerificationEngine(
            embedding_store=store, calibration=calibration, target_profile=enrolled.profile
        )
        result = engine.verify(
            verification_id="v1",
            segment_id="s1",
            candidate=candidate,
            duration_seconds=2.0,
            overlap_status="NO_OVERLAP_DETECTED",
        )
        fingerprints.append(result.fingerprint())
    assert fingerprints[0] != fingerprints[1], "config change must change the fingerprint"


def test_invalid_threshold_configuration_is_refused():
    from aarya_voice_lab.identity.calibration import CalibrationError

    with pytest.raises(CalibrationError, match="review threshold"):
        ThresholdConfig(target_review_threshold=0.95, target_acceptance_threshold=0.5)
    with pytest.raises(CalibrationError, match="within 0..1"):
        ThresholdConfig(operator_rejection_threshold=1.5)


# ==========================================================================
# §13.8 — provenance mismatch
# ==========================================================================


def test_profile_fingerprint_changes_with_embedding(tmp_path):
    """Re-enrolling must change the fingerprint so dependent verifications
    recompute rather than reusing scores from a profile that is gone."""
    _, _, first = _enrolled(tmp_path / "a", frequency=180.0)
    _, _, second = _enrolled(tmp_path / "b", frequency=300.0)
    assert first.profile.fingerprint() != second.profile.fingerprint()


def test_verification_fingerprint_changes_with_profile_version(tmp_path):
    data, provider, enrolled = _enrolled(tmp_path)
    store = EmbeddingStore(data)
    candidate = _embed(generate_speech_like(tmp_path / "c.wav", duration_seconds=2.0), provider)
    calibration = uncalibrated(provider.name, provider.version, is_synthetic=True)

    from dataclasses import replace

    fingerprints = []
    for version in (1, 2):
        profile = replace(enrolled.profile, version=version)
        engine = VerificationEngine(
            embedding_store=store, calibration=calibration, target_profile=profile
        )
        result = engine.verify(
            verification_id="v1",
            segment_id="s1",
            candidate=candidate,
            duration_seconds=2.0,
            overlap_status="NO_OVERLAP_DETECTED",
        )
        fingerprints.append(result.fingerprint())
    assert fingerprints[0] != fingerprints[1]


def test_provenance_records_the_strategy_that_built_the_profile(tmp_path):
    _, _, enrolled = _enrolled(tmp_path)
    provenance = enrolled.profile.provenance
    assert provenance.strategy_name == "direct_recording"
    assert provenance.strategy_version


def test_provenance_chain_links_source_to_decision(tmp_path):
    data, provider, enrolled = _enrolled(tmp_path)
    engine = VerificationEngine(
        embedding_store=EmbeddingStore(data),
        calibration=uncalibrated(provider.name, provider.version, is_synthetic=True),
        target_profile=enrolled.profile,
    )
    result = engine.verify(
        verification_id="v1",
        segment_id="s1",
        candidate=_embed(generate_speech_like(tmp_path / "c.wav", duration_seconds=2.0), provider),
        duration_seconds=2.0,
        overlap_status="NO_OVERLAP_DETECTED",
        source_file_id="src-1",
        source_sha256="a" * 64,
    )
    chain = contracts.provenance_chain(result, enrolled.profile.to_dict())["chain"]
    assert chain["source"]["source_file_id"] == "src-1"
    assert chain["candidate"]["segment_id"] == "s1"
    assert chain["profile"]["fingerprint"] == enrolled.profile.fingerprint()
    assert chain["embedding"]["embedding_sha256"] == enrolled.profile.embedding_sha256
    assert chain["verification"]["verification_id"] == "v1"
    assert chain["decision"]["machine_decision"] == result.decision.value


def test_profile_embedding_hash_matches_stored_vector(tmp_path):
    """Detects a profile pointing at a vector it does not describe."""
    data, _, enrolled = _enrolled(tmp_path)
    stored = EmbeddingStore(data).load(enrolled.profile.embedding_id)
    assert stored.sha256() == enrolled.profile.embedding_sha256


def test_profile_roundtrip_preserves_provenance(tmp_path):
    data, _, enrolled = _enrolled(tmp_path)
    reloaded = ProfileStore(data).load(enrolled.profile.profile_id, enrolled.profile.version)
    assert reloaded.fingerprint() == enrolled.profile.fingerprint()
    assert reloaded.provenance.strategy_name == enrolled.profile.provenance.strategy_name


# ==========================================================================
# §18 / §22 — local-first, no cloud, offline
# ==========================================================================


def test_no_network_or_cloud_imports_in_core_packages():
    """No pipeline or identity module may import a network/cloud client."""
    import ast

    from aarya_voice_lab.core.paths import PROJECT_ROOT

    forbidden = {
        "requests", "urllib", "urllib3", "http", "httpx", "aiohttp", "socket",
        "boto3", "botocore", "google", "azure", "openai", "smtplib", "ftplib",
    }
    offenders = []
    for package in LOCAL_FIRST_PACKAGES:
        for path in (PROJECT_ROOT / "src" / "aarya_voice_lab" / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    if name in forbidden:
                        offenders.append(f"{path.name}: {name}")
    assert not offenders, f"network/cloud imports found: {offenders}"


def test_no_cloud_storage_configuration():
    """Nothing in config may point at a bucket or remote store."""
    from aarya_voice_lab.core.config import load_config

    raw = json.dumps(load_config().raw).lower()
    for marker in ("s3://", "gs://", "azure", "bucket", "https://", "endpoint_url"):
        assert marker not in raw, f"cloud storage marker {marker!r} in config"


def test_data_root_is_entirely_local(tmp_path):
    """Every storage path resolves under the local data root."""
    data = DataRoot(root=tmp_path / "data").create()
    for path in (data.working, data.segments, data.manifests, data.reports,
                 data.review, data.cache, data.embeddings, data.enrollment, data.audit):
        assert str(path).startswith(str(tmp_path))


def test_embedding_store_has_no_export_path():
    """There must be no method that writes a vector outside the data root."""
    exported = [
        name
        for name in dir(EmbeddingStore)
        if any(word in name.lower() for word in ("export", "upload", "publish", "sync", "push"))
    ]
    assert not exported, f"EmbeddingStore exposes export-like methods: {exported}"


def test_offline_defaults_still_intact():
    """Phase 3 must not have weakened the Phase 1 offline guarantees."""
    from aarya_voice_lab.pipeline.runner import OFFLINE_ENV, TELEMETRY_OFF_ENV

    assert OFFLINE_ENV["HF_HUB_OFFLINE"] == "1"
    assert OFFLINE_ENV["TRANSFORMERS_OFFLINE"] == "1"
    assert TELEMETRY_OFF_ENV["WANDB_MODE"] == "offline"
    assert TELEMETRY_OFF_ENV["DO_NOT_TRACK"] == "1"


def test_embedding_directories_are_git_ignored():
    """Behavioural: ask Git, not the .gitignore text."""
    import subprocess

    from aarya_voice_lab.core.paths import PROJECT_ROOT

    for candidate in (
        "data/embeddings/x.vec",
        "data/embeddings/profile.npy",
        "data/enrollment/target.json",
        "data/audit/identity.jsonl",
        "some/embeddings/nested.bin",
    ):
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "check-ignore", "-q", candidate],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"git does NOT ignore {candidate}"


# ==========================================================================
# §14 — hardware-agnostic
# ==========================================================================


def test_no_vendor_or_product_hardcoding_in_core():
    """Core must not branch on a vendor or name a specific GPU product."""
    import re

    from aarya_voice_lab.core.paths import PROJECT_ROOT

    product_pattern = re.compile(r"\b(rtx|gtx|radeon|geforce)\s*\d{3,4}\b", re.IGNORECASE)
    offenders = []
    for package in LOCAL_FIRST_PACKAGES:
        for path in (PROJECT_ROOT / "src" / "aarya_voice_lab" / package).rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if product_pattern.search(line):
                    offenders.append(f"{path.name}:{number}")
    assert not offenders, f"specific GPU products named in Core: {offenders}"


def test_multiple_vendor_backends_are_representable():
    """AMD, Intel, Apple and unanticipated accelerators must be expressible."""
    values = {b.value for b in ComputeBackend}
    assert {"cpu", "cuda", "rocm", "xpu", "metal", "other"} <= values


def test_accelerator_backends_exclude_cpu():
    assert ComputeBackend.CPU not in ACCELERATOR_BACKENDS
    assert ComputeBackend.ROCM in ACCELERATOR_BACKENDS


def test_shipped_components_are_cpu_only():
    payload = contracts.runtime_capabilities()
    for component in payload["components"]:
        assert component["runs_on_cpu"]
        assert not component["requires_accelerator"]
    assert payload["portability"]["cpu_only_viable"]


def test_portability_claim_is_not_overstated():
    """A declaration is not a verified CPU-only run, and must say so."""
    note = contracts.runtime_capabilities()["portability"]["note"].lower()
    assert "not" in note and ("declaration" in note or "verified" in note)


def test_accelerator_bound_component_blocks_cpu_only_claim():
    capability = RuntimeCapability(
        component="hypothetical",
        acceleration=AccelerationRequirement.ACCELERATOR_REQUIRED,
        supported_backends=(ComputeBackend.OTHER,),
    )
    summary = describe_portability([capability])
    assert not summary["cpu_only_viable"]
    assert "hypothetical" in summary["accelerator_bound_components"]


def test_unknown_acceleration_blocks_cpu_only_claim():
    """UNKNOWN must not be optimistically read as CPU-capable."""
    capability = RuntimeCapability(
        component="undetermined", acceleration=AccelerationRequirement.UNKNOWN
    )
    summary = describe_portability([capability])
    assert not summary["cpu_only_viable"]
    assert "undetermined" in summary["undetermined_components"]


# ==========================================================================
# §20 — Claude Code Command Center contracts
# ==========================================================================


def test_command_catalogue_is_annotated():
    payload = command_center.command_catalogue()
    assert payload["count"] > 0
    for command in payload["commands"]:
        assert command["risk"] in {"read_only", "writes_local", "destructive", "gated"}
        assert command["summary"]


def test_destructive_commands_require_confirmation():
    for command in command_center.command_catalogue()["commands"]:
        if command["risk"] == "destructive":
            assert command["requires_confirmation"], f"{command['command']} is unconfirmed"


def test_gated_commands_state_their_reason():
    """A disabled control must explain itself rather than just vanish."""
    gated = [c for c in command_center.command_catalogue()["commands"] if c["risk"] == "gated"]
    assert gated
    for command in gated:
        assert command["gate_reason"]


def test_changed_files_returns_no_diff_content():
    """The contract carries file names and line counts only -- no hunk text,
    no '+'/'-' line content that could echo private material."""
    payload = command_center.changed_files()
    for entry in payload["files"]:
        assert set(entry) == {"path", "added", "removed", "binary"}
        assert isinstance(entry["path"], str)
        assert entry["added"] is None or isinstance(entry["added"], int)


def test_command_center_executes_nothing():
    """The module must expose no run/exec surface."""
    executors = [
        name
        for name in dir(command_center)
        if any(word in name.lower() for word in ("execute", "run_command", "shell", "eval"))
    ]
    assert not executors, f"command_center exposes execution helpers: {executors}"


def test_diagnostics_report_no_real_recordings(tmp_path):
    payload = command_center.diagnostics(DataRoot(root=tmp_path / "data").create())
    assert payload["real_recordings_present"] is False


def test_diagnostics_report_no_real_provider_when_none_is_installed(tmp_path, monkeypatch):
    """Real ML Runtime milestone follow-up (D11 audit): reproducibly
    simulate the not-installed case -- see the matching test in
    test_phase3_e2e.py for why this can no longer be a bare assertion."""
    from aarya_voice_lab.identity import embeddings as embeddings_module

    monkeypatch.setattr(embeddings_module, "_ENV_NEMO_PYTHON", tmp_path / "does-not-exist")
    payload = command_center.diagnostics(DataRoot(root=tmp_path / "data").create())
    assert payload["real_provider_installed"] is False


def test_diagnostics_report_real_provider_state_honestly(tmp_path):
    """`diagnostics()`'s `real_provider_installed` used to be hardcoded
    False unconditionally -- this asserts it now tracks the real,
    current capability state instead."""
    from aarya_voice_lab.identity.embeddings import any_real_provider_available

    payload = command_center.diagnostics(DataRoot(root=tmp_path / "data").create())
    assert payload["real_provider_installed"] == any_real_provider_available()


def test_command_center_snapshot_is_serializable(tmp_path):
    payload = command_center.command_center_snapshot(DataRoot(root=tmp_path / "data").create())
    json.dumps(payload)
    for key in ("repository", "commands", "verification", "activity", "diagnostics"):
        assert key in payload


def test_activity_feed_contains_no_vectors(tmp_path):
    from aarya_voice_lab.identity.audit import AuditEventType, AuditLog

    data = DataRoot(root=tmp_path / "data").create()
    AuditLog(data).append(
        AuditEventType.EMBEDDING_CREATED,
        actor="test",
        subject_id="e1",
        detail={"values": [0.1, 0.2, 0.3], "path": "/absolute/private/x.wav"},
    )
    payload = command_center.activity_feed(data)
    entry_detail = payload["entries"][0]["detail"]
    assert entry_detail["values"] == "<redacted: never logged>"
    assert "/absolute/private" not in json.dumps(entry_detail)
    assert "0.1, 0.2, 0.3" not in json.dumps(entry_detail)

from __future__ import annotations

from aarya_voice_lab.pipeline.public_dataset_gate import evaluate_public_dataset_use
from aarya_voice_lab.registry.dataset_registry import PublicDatasetRegistry
from aarya_voice_lab.schemas.records import build_public_dataset_entry


def _registry(tmp_path):
    return PublicDatasetRegistry(tmp_path / "registry.jsonl")


def _register(registry, **overrides):
    defaults = dict(
        dataset_id="corpus-1",
        dataset_name="Corpus One",
        version="1.0",
        source="https://example.org/corpus-1",
        license="CC BY 4.0",
        permitted_uses=["training-pipeline-development"],
        status="approved",
    )
    defaults.update(overrides)
    registry.add(build_public_dataset_entry(**defaults))


def test_valid_approved_dataset_passes_every_condition(tmp_path):
    registry = _registry(tmp_path)
    _register(registry)
    report = evaluate_public_dataset_use("corpus-1", "training-pipeline-development", registry=registry)
    assert report.allowed is True
    assert report.unsatisfied == []


def test_unregistered_dataset_fails_closed(tmp_path):
    """'Untrusted metadata' case: a dataset_id with no registry entry at
    all must never pass, regardless of the requested use."""
    registry = _registry(tmp_path)
    report = evaluate_public_dataset_use("never-registered", "training-pipeline-development", registry=registry)
    assert report.allowed is False
    names = {c.name for c in report.unsatisfied}
    assert "dataset registered" in names


def test_registered_but_not_approved_dataset_is_denied(tmp_path):
    registry = _registry(tmp_path)
    _register(registry, status="registered")
    report = evaluate_public_dataset_use("corpus-1", "training-pipeline-development", registry=registry)
    assert report.allowed is False
    names = {c.name for c in report.unsatisfied}
    assert "dataset approved" in names


def test_missing_or_unknown_license_is_denied(tmp_path):
    registry = _registry(tmp_path)
    _register(registry, license="unknown")
    report = evaluate_public_dataset_use("corpus-1", "training-pipeline-development", registry=registry)
    assert report.allowed is False
    names = {c.name for c in report.unsatisfied}
    assert "license known and recorded" in names


def test_incompatible_purpose_is_denied(tmp_path):
    registry = _registry(tmp_path)
    _register(registry, permitted_uses=["benchmark-development"])
    report = evaluate_public_dataset_use("corpus-1", "training-pipeline-development", registry=registry)
    assert report.allowed is False
    names = {c.name for c in report.unsatisfied}
    assert "intended use permitted" in names


def test_explicitly_prohibited_use_is_denied_even_if_also_permitted(tmp_path):
    registry = _registry(tmp_path)
    _register(
        registry,
        permitted_uses=["training-pipeline-development"],
        prohibited_uses=["training-pipeline-development"],
    )
    report = evaluate_public_dataset_use("corpus-1", "training-pipeline-development", registry=registry)
    assert report.allowed is False


def test_restricted_identity_use_requires_explicit_acknowledgement(tmp_path):
    registry = _registry(tmp_path)
    _register(registry, speaker_metadata_restrictions="research use only, no redistribution of speaker IDs")
    denied = evaluate_public_dataset_use("corpus-1", "training-pipeline-development", registry=registry)
    assert denied.allowed is False
    names = {c.name for c in denied.unsatisfied}
    assert "speaker/identity restrictions respected" in names

    allowed = evaluate_public_dataset_use(
        "corpus-1",
        "training-pipeline-development",
        registry=registry,
        speaker_restrictions_acknowledged=True,
    )
    assert allowed.allowed is True


def test_no_speaker_restrictions_needs_no_acknowledgement(tmp_path):
    registry = _registry(tmp_path)
    _register(registry, speaker_metadata_restrictions=None)
    report = evaluate_public_dataset_use("corpus-1", "training-pipeline-development", registry=registry)
    assert report.allowed is True


def test_no_special_casing_for_a_dataset_id_named_synthetic(tmp_path):
    """This gate governs only the public-licensed-data track and must
    contain no bypass for anything resembling the synthetic-data track --
    a dataset_id or use string that merely contains 'synthetic' gets no
    special treatment; it is evaluated by the exact same conditions as
    any other unregistered id and is denied the same way."""
    registry = _registry(tmp_path)
    report = evaluate_public_dataset_use("synthetic-fixture", "training-pipeline-development", registry=registry)
    assert report.allowed is False
    names = {c.name for c in report.unsatisfied}
    assert "dataset registered" in names

"""Phase 2 of the 8-phase release plan -- Public Dataset Activation.

No explicitly authorized real public dataset (e.g. VCTK, LibriSpeech) is
available in this session: obtaining one requires both a human licensing
review and the user's explicit download authorization, neither of which
has been given. Per this phase's own instruction, no dataset is
downloaded; instead this strengthens the code-only intake path with an
integration test chaining the three pieces that previously only had
isolated, per-module coverage:

    PublicDatasetRegistry -> public_dataset_gate -> DatasetAdapter

using a repository-controlled fixture manifest -- the synthetic-data
track (see docs/DATA_POLICY.md), never the public-licensed track for
real. Nothing here touches dataset_gate.py or the consented-real-person
track.
"""

from __future__ import annotations

import json

from aarya_voice_lab.pipeline.dataset_adapter import FixtureDatasetAdapter
from aarya_voice_lab.pipeline.public_dataset_gate import evaluate_public_dataset_use
from aarya_voice_lab.registry.dataset_registry import PublicDatasetRegistry
from aarya_voice_lab.schemas.records import build_public_dataset_entry


def _write_fixture_manifest(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for i in range(3):
            fh.write(
                json.dumps(
                    {
                        "record_id": f"utt-{i}",
                        "audio_ref": f"audio/utt-{i}.wav",
                        "language": "en",
                        "transcript": f"sample utterance {i}",
                    }
                )
                + "\n"
            )
    return path


def test_full_intake_chain_registry_gate_adapter(tmp_path):
    """The end-to-end story: a dataset is registered and approved with
    real, documented metadata; the license gate clears it for the
    requested use; only then does the adapter normalize its records."""
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    registry.add(
        build_public_dataset_entry(
            dataset_id="fixture-corpus-v1",
            dataset_name="Fixture Corpus",
            version="1.0",
            source="https://example.org/fixture-corpus",
            license="CC BY 4.0",
            permitted_uses=["training-pipeline-development"],
            status="approved",
            language=["en"],
        )
    )

    gate_report = evaluate_public_dataset_use(
        "fixture-corpus-v1", "training-pipeline-development", registry=registry
    )
    assert gate_report.allowed is True

    manifest_path = _write_fixture_manifest(tmp_path / "fixture-corpus" / "manifest.jsonl")
    registered = registry.get("fixture-corpus-v1")
    adapter = FixtureDatasetAdapter(
        manifest_path, dataset_id=registered["dataset_id"], license=registered["license"]
    )
    records = list(adapter.iter_records())

    assert len(records) == 3
    assert all(r.dataset_id == "fixture-corpus-v1" for r in records)
    assert all(r.license == "CC BY 4.0" for r in records)


def test_unapproved_dataset_never_reaches_the_adapter_stage(tmp_path):
    """The gate must be checked -- and must deny -- before any adapter
    ever touches a dataset's content. This models the real intake
    order: Registry -> Gate -> Adapter, never Adapter first."""
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    registry.add(
        build_public_dataset_entry(
            dataset_id="unreviewed-corpus",
            dataset_name="Unreviewed Corpus",
            version="1.0",
            source="https://example.org/unreviewed",
            license="CC BY 4.0",
            permitted_uses=["training-pipeline-development"],
            status="registered",  # not yet approved
        )
    )

    gate_report = evaluate_public_dataset_use(
        "unreviewed-corpus", "training-pipeline-development", registry=registry
    )
    assert gate_report.allowed is False

    # A well-behaved intake pipeline must stop here. Simulated by simply
    # asserting the caller's own logic: this test documents the required
    # order, not a mechanical enforcement inside the adapter itself (the
    # adapter has no knowledge of the registry by design -- see
    # pipeline.dataset_adapter's module docstring).
    unsatisfied_names = {c.name for c in gate_report.unsatisfied}
    assert "dataset approved" in unsatisfied_names


def test_incremented_dataset_id_is_the_documented_way_to_change_status(tmp_path):
    """Registry entries are refuse-to-overwrite by dataset_id (see
    PublicDatasetRegistry's own docstring) -- re-registering under a
    new id/version is the correct way to record a later, different
    review decision for what is conceptually the same dataset."""
    registry = PublicDatasetRegistry(tmp_path / "registry.jsonl")
    registry.add(
        build_public_dataset_entry(
            dataset_id="corpus-v1",
            dataset_name="Corpus",
            version="1.0",
            source="https://example.org/corpus",
            license="unknown",
            permitted_uses=["training-pipeline-development"],
            status="under_review",
        )
    )
    # A later review reverses the decision -- a NEW entry, not a mutation.
    registry.add(
        build_public_dataset_entry(
            dataset_id="corpus-v2",
            dataset_name="Corpus",
            version="2.0",
            source="https://example.org/corpus",
            license="CC BY 4.0",
            permitted_uses=["training-pipeline-development"],
            status="approved",
        )
    )

    assert registry.get("corpus-v1")["status"] == "under_review"  # original, unchanged
    assert registry.get("corpus-v2")["status"] == "approved"
    assert [r["dataset_id"] for r in registry.list_approved()] == ["corpus-v2"]

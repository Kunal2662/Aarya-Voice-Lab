"""The public dataset intake gate.

Before a registered public dataset may enter the training pipeline for a
given use, every condition below must hold. This is a **separate** gate
from `pipeline.dataset_gate` (the real-recording access gate) -- it
governs the public-licensed-data track only (see docs/DATA_POLICY.md)
and never grants access to the private recordings. It does not modify,
weaken, or share state with `dataset_gate.py`.

Reuses GateCondition/GateReport from dataset_gate.py -- both are already
generic (name/satisfied/detail, fail-closed aggregation) and were not
written with any real-recording-specific assumption baked in.
"""

from __future__ import annotations

from aarya_voice_lab.pipeline.dataset_gate import GateCondition, GateReport
from aarya_voice_lab.registry.dataset_registry import PublicDatasetRegistry

UNKNOWN_LICENSE_VALUES = {"unknown", ""}


def evaluate_public_dataset_use(
    dataset_id: str,
    intended_use: str,
    *,
    registry: PublicDatasetRegistry | None = None,
    speaker_restrictions_acknowledged: bool = False,
) -> GateReport:
    """Evaluate whether `dataset_id` may be used for `intended_use`.

    `speaker_restrictions_acknowledged` is an operator attestation, exactly
    like the attestation-style conditions in `dataset_gate.py` -- it is
    never inferred from the registry entry itself. A dataset with no
    recorded speaker-metadata restrictions does not need it; a dataset
    that does record a restriction requires it regardless of what the
    restriction text says, because this module cannot read intent.
    """
    reg = registry or PublicDatasetRegistry()
    report = GateReport()

    record = reg.get(dataset_id)

    report.conditions.append(
        GateCondition(
            "dataset registered",
            record is not None,
            f"found in public dataset registry: {dataset_id}"
            if record is not None
            else f"no registry entry for dataset_id={dataset_id!r} -- unregistered/untrusted datasets are never usable",
        )
    )

    status = record.get("status") if record is not None else None
    report.conditions.append(
        GateCondition(
            "dataset approved",
            status == "approved",
            f"status={status!r}" if record is not None else "cannot check status -- dataset not registered",
        )
    )

    license_value = (record.get("license") if record is not None else None) or ""
    license_known = license_value.strip().lower() not in UNKNOWN_LICENSE_VALUES and license_value.strip() != ""
    report.conditions.append(
        GateCondition(
            "license known and recorded",
            license_known,
            f"license={license_value!r}"
            if record is not None
            else "cannot check license -- dataset not registered",
        )
    )

    permitted_uses = record.get("permitted_uses", []) if record is not None else []
    prohibited_uses = record.get("prohibited_uses", []) if record is not None else []
    use_permitted = intended_use in permitted_uses and intended_use not in prohibited_uses
    report.conditions.append(
        GateCondition(
            "intended use permitted",
            use_permitted,
            f"permitted_uses={permitted_uses}, prohibited_uses={prohibited_uses}, requested={intended_use!r}"
            if record is not None
            else "cannot check permitted uses -- dataset not registered",
        )
    )

    restrictions = record.get("speaker_metadata_restrictions") if record is not None else None
    restrictions_ok = restrictions is None or speaker_restrictions_acknowledged
    report.conditions.append(
        GateCondition(
            "speaker/identity restrictions respected",
            restrictions_ok,
            "no speaker-metadata restrictions recorded"
            if restrictions is None
            else (
                f"restriction acknowledged: {restrictions!r}"
                if speaker_restrictions_acknowledged
                else f"restriction NOT acknowledged: {restrictions!r} -- cannot be self-satisfied"
            ),
        )
    )

    return report

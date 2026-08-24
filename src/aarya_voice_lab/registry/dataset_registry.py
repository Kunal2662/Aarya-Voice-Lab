"""Public dataset registry: local record of third-party licensed datasets
considered or approved for use in training-pipeline development, model
experimentation, generic voice development, or benchmark development.

See docs/DATA_POLICY.md. Backed by public_datasets/registry.jsonl, which
is git-ignored.

This registry holds ONLY the public-licensed-data track. It must never be
used to record synthetic test fixtures or consented real-person
(target-speaker) data -- those tracks have their own, separate storage
(manifests/templates/, schemas/enrollment_profile.schema.json) and are
governed by dataset_gate.py and docs/PRIVACY.md, which this module does
not touch.
"""

from __future__ import annotations

from typing import Any

from aarya_voice_lab.core.paths import PROJECT_ROOT
from aarya_voice_lab.registry.json_registry import JsonLinesRegistry
from aarya_voice_lab.schemas.base import SchemaName

DEFAULT_PUBLIC_DATASET_REGISTRY_PATH = PROJECT_ROOT / "public_datasets" / "registry.jsonl"


class PublicDatasetRegistry(JsonLinesRegistry):
    def __init__(self, path=DEFAULT_PUBLIC_DATASET_REGISTRY_PATH):
        super().__init__(path=path, schema_name=SchemaName.PUBLIC_DATASET_REGISTRY, id_field="dataset_id")

    def list_by_status(self, status: str) -> list[dict[str, Any]]:
        return [r for r in self.list() if r.get("status") == status]

    def list_approved(self) -> list[dict[str, Any]]:
        """The only method a pipeline stage should read from when deciding
        whether a public dataset may be used. 'registered' or
        'under_review' entries have documented metadata but have not
        cleared review -- excluded here so a caller cannot mistake
        recorded metadata for permission."""
        return self.list_by_status("approved")

    def permits_use(self, dataset_id: str, use: str) -> bool:
        """True only if the dataset is approved AND its own recorded
        permitted_uses explicitly names `use`. Absence of a matching
        entry, or an entry that is not approved, is treated as False --
        this method never infers permission from what is merely present."""
        record = self.get(dataset_id)
        if record is None:
            return False
        if record.get("status") != "approved":
            return False
        return use in record.get("permitted_uses", [])

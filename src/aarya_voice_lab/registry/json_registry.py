"""A minimal local, file-backed registry: one JSON Lines file, one record
per line, validated against a schema on write and on read.

Used for both the experiment registry and the model registry (section 11
and 12 of the Phase 0 spec) since their storage needs are identical --
only the schema and id field differ. Registry files live under
git-ignored directories (experiments/, models/) by design.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from aarya_voice_lab.schemas.base import SchemaName, validate


class JsonLinesRegistry:
    def __init__(self, path: Path, schema_name: SchemaName, id_field: str):
        self.path = path
        self.schema_name = schema_name
        self.id_field = id_field

    def add(self, record: dict[str, Any]) -> None:
        validate(record, self.schema_name)
        existing_ids = {r[self.id_field] for r in self.list()}
        record_id = record[self.id_field]
        if record_id in existing_ids:
            raise ValueError(f"{self.schema_name.value} with {self.id_field}={record_id!r} already exists")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def list(self) -> list[dict[str, Any]]:
        return list(self._iter_records())

    def get(self, record_id: str) -> dict[str, Any] | None:
        for record in self._iter_records():
            if record.get(self.id_field) == record_id:
                return record
        return None

    def _iter_records(self) -> Iterator[dict[str, Any]]:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

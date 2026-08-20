"""Loading and validating records against the JSON Schemas in /schemas.

This module reads schema *definitions* (structure) from the top-level
schemas/ directory. It never reads dataset content from source/ or
datasets/ -- callers pass in-memory dicts (e.g. loaded from
manifests/templates/ or constructed by tests).

Cross-schema `$ref`s are resolved from a registry built exclusively from
local files. Remote resolution is never attempted: this project is
local-first (docs/PRIVACY.md), and a validator that silently reaches out
to the network would violate that guarantee. An unresolvable `$ref`
raises rather than falling back to a fetch.
"""

from __future__ import annotations

import functools
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

from aarya_voice_lab.core.paths import PROJECT_ROOT

SCHEMAS_DIR = PROJECT_ROOT / "schemas"


class SchemaName(StrEnum):
    SEGMENT = "segment"
    DATASET_MANIFEST = "dataset_manifest"
    EXPERIMENT = "experiment"
    MODEL_REGISTRY = "model_registry"
    BENCHMARK = "benchmark"
    MANUAL_REVIEW = "manual_review"
    STAGE_RESULT = "stage_result"
    CANDIDATE_MANIFEST = "candidate_manifest"
    ENROLLMENT_PROFILE = "enrollment_profile"
    VERIFICATION = "verification"
    IDENTITY_REVIEW = "identity_review"
    CALIBRATION = "calibration"
    IMPORT_MANIFEST = "import_manifest"


class ValidationError(ValueError):
    """Raised when a record fails schema validation. Wraps jsonschema errors
    into a single, readable message with a stable exception type for
    callers that don't want a hard dependency on the jsonschema package.
    """


def _schema_path(name: SchemaName) -> Path:
    return SCHEMAS_DIR / f"{name.value}.schema.json"


@functools.cache
def load_schema(name: SchemaName) -> dict[str, Any]:
    path = _schema_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"Schema file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _retrieve_never(uri: str):
    raise NoSuchResource(
        ref=f"Refusing to fetch schema {uri!r}: only schemas bundled in {SCHEMAS_DIR} may be referenced. "
        "AARYA Voice Lab never resolves schemas over the network."
    )


@functools.lru_cache(maxsize=1)
def _registry() -> Registry:
    """Build a referencing Registry containing every local schema.

    Each schema is registered under both its declared `$id` and its bare
    filename, so `$ref`s written either way resolve offline.
    """
    registry = Registry(retrieve=_retrieve_never)
    for name in SchemaName:
        schema = load_schema(name)
        resource = Resource.from_contents(schema)
        filename = f"{name.value}.schema.json"
        registry = resource @ registry
        registry = registry.with_resource(uri=filename, resource=resource)
    return registry


def validate(record: dict[str, Any], schema_name: SchemaName) -> None:
    """Validate `record` against the named schema.

    Raises ValidationError with a readable message on failure; returns
    None (does not return a value) on success.
    """
    schema = load_schema(schema_name)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema, registry=_registry())
    errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
    if errors:
        messages = [f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}" for err in errors]
        raise ValidationError(
            f"{schema_name.value} record failed validation ({len(errors)} error(s)):\n"
            + "\n".join(f"  - {m}" for m in messages)
        )

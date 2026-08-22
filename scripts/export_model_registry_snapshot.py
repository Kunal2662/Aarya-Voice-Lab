#!/usr/bin/env python3
"""Write a live snapshot of the (non-private) model registry for the UI.

VL-D12. Mirrors scripts/export_identity_status_snapshot.py exactly: this
reads live state (models/registry.jsonl) that legitimately changes from
run to run with no code change, so it is NOT committed (see
.gitignore's `frontend/contracts/live/` rule) and NOT part of the
drift-tested contract set. The Models workspace treats a missing/stale
file as an honest "not fetched" state rather than fabricating a model
list.

registry.ModelRegistry.list_non_private_models() itself already does all
the real work AND the one security-critical thing this script depends
on: docs/SECURITY.md requires a private_voice model to have no
frontend-only path to itself, and this script (like the CLI command it
mirrors) calls ONLY that method -- never `.list()`, never
`list_private_voice_models()` -- so a private_voice entry can never
reach this file even if one is ever added to the registry.

Usage:
    python scripts/export_model_registry_snapshot.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from aarya_voice_lab.registry.model_registry import ModelRegistry  # noqa: E402

OUT_FILE = REPO_ROOT / "frontend" / "contracts" / "live" / "model_registry_snapshot.json"


def main() -> int:
    models = ModelRegistry().list_non_private_models()
    envelope = {
        "$generated_by": "scripts/export_model_registry_snapshot.py",
        "$live_snapshot": True,
        "note": (
            "Point-in-time read of models/registry.jsonl, not a frozen contract. "
            "private_voice entries are never included here — see docs/SECURITY.md. "
            "Re-run this script to refresh; a missing file means this hasn't been "
            "fetched in this session, not that anything failed."
        ),
        "contract": "model_registry_snapshot",
        "models": models,
        "count": len(models),
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(envelope, indent=2) + "\n")
    print(f"Wrote {OUT_FILE} ({len(models)} model(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

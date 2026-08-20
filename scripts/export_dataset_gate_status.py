#!/usr/bin/env python3
"""Write a live snapshot of the real-recording access gate for the UI.

Deliberately separate from scripts/export_frontend_contracts.py: that
script exports frozen, backend-enum vocabularies that only change when
the backend enum does, and are drift-tested against a committed file.
`evaluate_gate()` is different — it inspects live Git/config state, so
its output legitimately changes from run to run (branch, working-tree
cleanliness, ...) even with no code change at all. Committing a snapshot
of it and drift-testing it against `--check` would fail on every commit
of any other file, which is not a real drift signal.

So this snapshot is NOT committed (see .gitignore) and NOT part of the
drift-tested contract set. It is safe to run — evaluate_gate() reads
only Git state and directory protection, never audio content — but its
output is a point-in-time read, not a frozen contract. The Import
workspace treats a missing/stale file as an honest "not evaluated" state
rather than assuming access is denied or allowed.

Usage:
    python scripts/export_dataset_gate_status.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from aarya_voice_lab.pipeline.dataset_gate import evaluate_gate  # noqa: E402

OUT_FILE = REPO_ROOT / "frontend" / "contracts" / "live" / "dataset_gate_status.json"


def main() -> int:
    # Every attestation defaults to False: this snapshot never claims an
    # approval nobody gave. explicit_approval in particular can only ever
    # be set by a human, and is never inferred here.
    report = evaluate_gate()
    payload = {
        "$generated_by": "scripts/export_dataset_gate_status.py",
        "$live_snapshot": True,
        "note": (
            "Point-in-time read of Git/config state, not a frozen contract. "
            "Re-run this script to refresh; a missing file means the gate has "
            "not been evaluated in this session, not that access is denied."
        ),
        **report.to_dict(),
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {OUT_FILE} (access_allowed={payload['access_allowed']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

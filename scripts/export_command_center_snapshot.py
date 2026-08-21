#!/usr/bin/env python3
"""Write a live snapshot of the Claude Command Center for the UI.

Deliberately mirrors scripts/export_dataset_gate_status.py: this reads
live state (git branch/HEAD, the identity audit log, a git-safety scan)
that legitimately changes from run to run even with no code change, so
it is NOT committed (see .gitignore's `frontend/contracts/live/` rule)
and NOT part of the drift-tested contract set. The Claude workspace
treats a missing/stale file as an honest "not fetched" state rather than
fabricating a branch name or an empty-but-present activity feed.

command_center_snapshot() itself already does all the real work
(identity/command_center.py) -- this script only calls it and writes the
result. It never invents a field, never fabricates repository state, and
never includes anything command_center_snapshot() didn't already decide
was safe to display (file names/counts/booleans, never audio, never a
vector, never an absolute path into private storage).

Usage:
    python scripts/export_command_center_snapshot.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from aarya_voice_lab.core.data_root import DataRoot  # noqa: E402
from aarya_voice_lab.identity.command_center import command_center_snapshot  # noqa: E402

OUT_FILE = REPO_ROOT / "frontend" / "contracts" / "live" / "command_center_snapshot.json"


def main() -> int:
    payload = command_center_snapshot(DataRoot.default(), REPO_ROOT)
    envelope = {
        "$generated_by": "scripts/export_command_center_snapshot.py",
        "$live_snapshot": True,
        "note": (
            "Point-in-time read of Git/audit-log state, not a frozen contract. "
            "Re-run this script to refresh; a missing file means the Command "
            "Center has not fetched a snapshot in this session, not that "
            "anything failed."
        ),
        **payload,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(envelope, indent=2) + "\n")
    branch = payload.get("repository", {}).get("branch", "?")
    print(f"Wrote {OUT_FILE} (branch={branch})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

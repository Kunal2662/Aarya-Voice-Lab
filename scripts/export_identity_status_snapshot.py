#!/usr/bin/env python3
"""Write a live snapshot of speaker-identity/enrollment status for the UI.

D11 audit follow-up. Mirrors scripts/export_command_center_snapshot.py
exactly: `identity.contracts.desktop_snapshot()` — "one call returning
everything the desktop needs on load" per its own docstring — has
existed, been tested, and been CLI-exposed (`aarya-voice identity-status
--json`) since Phase 3, but nothing in the frontend ever fetched it. This
script writes it to the same gitignored `frontend/contracts/live/`
location every other live snapshot uses, NOT committed and NOT part of
the drift-tested contract set, since profile/enrollment/embedding counts
legitimately change from run to run with no code change.

desktop_snapshot() itself already does all the real work
(identity/contracts.py) -- this script only calls it and writes the
result. It never invents a field and never includes anything
desktop_snapshot() didn't already decide was safe to display (counts,
states, booleans -- never a vector, never audio, never an absolute path
into private storage).

Usage:
    python scripts/export_identity_status_snapshot.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from aarya_voice_lab.core.data_root import DataRoot  # noqa: E402
from aarya_voice_lab.identity.contracts import desktop_snapshot  # noqa: E402

OUT_FILE = REPO_ROOT / "frontend" / "contracts" / "live" / "identity_status_snapshot.json"


def main() -> int:
    payload = desktop_snapshot(DataRoot.default())
    envelope = {
        "$generated_by": "scripts/export_identity_status_snapshot.py",
        "$live_snapshot": True,
        "note": (
            "Point-in-time read of speaker-identity/enrollment/embedding "
            "state, not a frozen contract. Re-run this script to refresh; "
            "a missing file means this hasn't been fetched in this "
            "session, not that anything failed."
        ),
        **payload,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(envelope, indent=2) + "\n")
    real_provider = payload.get("enrollment", {}).get("real_provider_installed")
    print(f"Wrote {OUT_FILE} (real_provider_installed={real_provider})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

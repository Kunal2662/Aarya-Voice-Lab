#!/usr/bin/env python3
"""Write a live snapshot of Real Voice Model Engine provider capabilities.

Deliberately mirrors scripts/export_command_center_snapshot.py: this
reads live, interpreter-specific state (which packages are actually
importable right now) that legitimately changes if the environment
changes, so it is NOT committed (see .gitignore's
`frontend/contracts/live/` rule) and NOT part of the drift-tested
contract set. The Voice Models workspace treats a missing/stale file as
an honest "not fetched" state rather than fabricating AVAILABLE.

Never invents a capability state -- every value below comes from a real
`capability_state()`/`capabilities()` call against this interpreter.

Usage:
    python scripts/export_voice_engine_capabilities.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from aarya_voice_lab.identity.embeddings import available_providers, get_provider  # noqa: E402
from aarya_voice_lab.pipeline.generation import LocalNeuralVoiceGenerator  # noqa: E402
from aarya_voice_lab.pipeline.training import LocalTrainingProvider  # noqa: E402

OUT_FILE = REPO_ROOT / "frontend" / "contracts" / "live" / "voice_engine_capabilities.json"


def main() -> int:
    embedding_providers = []
    for name in available_providers():
        provider = get_provider(name)
        state = provider.capability_state() if hasattr(provider, "capability_state") else None
        embedding_providers.append(
            {
                "name": name,
                "is_synthetic": provider.is_synthetic,
                "state": state["state"] if state else ("SYNTHETIC_ONLY" if provider.is_synthetic else "UNKNOWN"),
                "detail": state.get("detail", "") if state else "",
            }
        )

    generation_capabilities = LocalNeuralVoiceGenerator().get_capabilities().to_dict()
    training_capabilities = LocalTrainingProvider().capabilities().to_dict()

    envelope = {
        "$generated_by": "scripts/export_voice_engine_capabilities.py",
        "$live_snapshot": True,
        "note": (
            "Point-in-time capability detection for THIS interpreter, not a "
            "frozen contract or a promise about any other machine. Re-run "
            "this script to refresh."
        ),
        "embedding_providers": embedding_providers,
        "generation_provider": {"name": LocalNeuralVoiceGenerator.name, **generation_capabilities},
        "training_provider": {"name": LocalTrainingProvider.name, **training_capabilities},
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(envelope, indent=2) + "\n")
    print(f"Wrote {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

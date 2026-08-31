"""Installer-only helper steps `installer/AaryaVoiceLab.iss` shells out to.

These exist for exactly two reasons the existing `aarya-voice` CLI cannot
cover on its own inside a silent installer process:

1. `aarya-voice hf-login`'s token entry uses `getpass.getpass()`, which
   needs a real attached console -- Inno Setup's `Exec()` runs a hidden
   child process with no console for `getpass` to read from. This script
   reads the token from an environment variable the installer sets on
   its own process (inherited by this one child process only, then
   cleared) instead -- same secure destination
   (`pipeline.hf_auth.login_with_token()`, huggingface_hub's own
   credential store), different, non-interactive input path.
2. `aarya-voice indicf5-report` only verifies whether model assets are
   already present; it deliberately never downloads them (see that
   module's own docstring). A fresh install has nothing cached yet, so
   the installer needs an explicit provisioning step before the smoke
   test can run at all.

Both steps call the EXISTING, already-tested `pipeline.hf_auth`/
`pipeline.indicf5_provisioning` functions directly -- nothing here
reimplements authentication or download logic.

Usage:
    _installer_steps.py login       -- reads AARYA_INSTALLER_HF_TOKEN
    _installer_steps.py provision   -- downloads/verifies model assets

Exit code 0 on success, 1 on failure, 2 on "skipped" (login only, when no
token was provided -- not an error, the installer treats it as "continue
unauthenticated, the user will run `aarya-voice hf-login` later").
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _run_login() -> int:
    from aarya_voice_lab.pipeline.hf_auth import HFAuthError, check_existing_login, login_with_token

    token = os.environ.get("AARYA_INSTALLER_HF_TOKEN", "")

    # Phase 4's own requirement: reuse an already-valid credential rather
    # than forcing re-entry. huggingface_hub's credential store is
    # machine-wide, not per-installation -- a fresh env-tts this
    # installer just built can find a token the user configured before
    # (e.g. via `huggingface-cli login` or an earlier install) without
    # the installer's own token page ever being filled in.
    if not token:
        existing = None
        for attempt in range(1, 4):
            try:
                existing = check_existing_login()
                break
            except HFAuthError as exc:
                if "could not reach huggingface" not in str(exc).lower():
                    print(f"WARNING: could not check for an existing login: {exc}")
                    break
                print(f"WARNING: attempt {attempt} hit a network error checking for an existing login, retrying: {exc}")
                time.sleep(2)
        if existing is not None and existing.authenticated:
            print(f"OK: reusing existing login as {existing.username}")
            return 0
        print("SKIP: no token provided and no existing HuggingFace login found")
        return 2

    # Retry only on a network failure -- this session's own repeated,
    # documented evidence (see docs/INDICF5_INSTALLER.md) is that this
    # specific flakiness against huggingface.co is real but transient,
    # usually clearing within a few seconds. A genuine rejection (401,
    # now distinguishable from a network error since the hf_auth_worker.py
    # fix above) is never retried -- retrying it would not change the
    # outcome, and would just delay reporting a real problem.
    last_exc: HFAuthError | None = None
    for attempt in range(1, 4):
        try:
            status = login_with_token(token)
            last_exc = None
            break
        except HFAuthError as exc:
            last_exc = exc
            if "could not reach huggingface" not in str(exc).lower():
                break
            print(f"WARNING: attempt {attempt} hit a network error, retrying: {exc}")
            time.sleep(2)
    if last_exc is not None:
        print(f"ERROR: {last_exc}")
        return 1
    if not status.authenticated:
        print("ERROR: token was rejected")
        return 1
    print(f"OK: authenticated as {status.username}")
    return 0


def _run_provision() -> int:
    from aarya_voice_lab.pipeline.hf_auth import HFAuthError, check_existing_login
    from aarya_voice_lab.pipeline.indicf5_provisioning import ProvisioningError, provision

    login_status = None
    for attempt in range(1, 4):
        try:
            login_status = check_existing_login()
            break
        except HFAuthError as exc:
            if "could not reach huggingface" not in str(exc).lower():
                print(f"ERROR: could not check HuggingFace login: {exc}")
                return 1
            print(f"WARNING: attempt {attempt} hit a network error checking login, retrying: {exc}")
            time.sleep(2)
    if login_status is None or not login_status.authenticated:
        print("ERROR: no authenticated HuggingFace login -- run `aarya-voice hf-login` first")
        return 1

    # Same retry principle as _run_login(): only a genuine "network"
    # failure_kind is retried (this session's own repeated real evidence
    # is that it usually clears within a few seconds) -- gated_access,
    # corruption, authentication, and disk failures are never retried,
    # since retrying would not change a real, stable failure's outcome.
    last_exc: ProvisioningError | None = None
    for attempt in range(1, 4):
        try:
            result = provision()
            last_exc = None
            break
        except ProvisioningError as exc:
            last_exc = exc
            if exc.failure_kind != "network":
                break
            print(f"WARNING: attempt {attempt} hit a network error provisioning, retrying: {exc}")
            time.sleep(2)
    if last_exc is not None:
        print(f"ERROR ({last_exc.failure_kind}): {last_exc}")
        return 1
    for line in result.summary_lines():
        print(line)
    return 0 if result.ok else 1


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("login", "provision"):
        print("usage: _installer_steps.py <login|provision>", file=sys.stderr)
        return 2
    if sys.argv[1] == "login":
        return _run_login()
    return _run_provision()


if __name__ == "__main__":
    raise SystemExit(main())

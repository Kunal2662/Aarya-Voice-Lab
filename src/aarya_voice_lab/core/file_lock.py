"""A minimal, dependency-free cross-process advisory file lock.

Hardening milestone F-2: `JsonLinesRegistry.add()` and batch allocation
both used to read existing state, decide something based on it, then
write -- with no coordination between concurrent callers, so two
processes could both pass the same "is this id free?" check and both
write, corrupting the append-only log with a duplicate id. This module
closes that gap with the smallest mechanism that actually works across
processes: `fcntl.flock` on a dedicated lock file, already in the Python
standard library.

POSIX-only. This project targets Linux/macOS only (see
docs/ENVIRONMENT.md) -- nothing else in the codebase has a Windows
fallback either, so none is added here.
"""

from __future__ import annotations

import contextlib
import fcntl
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def locked(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on `lock_path` for the duration of
    the `with` block, blocking until it is available. The lock file's
    contents are never read or written -- only its existence and `flock`
    state matter -- and it is created on first use.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

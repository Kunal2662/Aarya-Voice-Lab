"""A minimal, dependency-free cross-process advisory file lock.

Hardening milestone F-2: `JsonLinesRegistry.add()` and batch allocation
both used to read existing state, decide something based on it, then
write -- with no coordination between concurrent callers, so two
processes could both pass the same "is this id free?" check and both
write, corrupting the append-only log with a duplicate id. This module
closes that gap with the smallest mechanism that actually works across
processes, on whichever platform this runs on:

- POSIX (Linux/macOS): `fcntl.flock` on a dedicated lock file.
- Windows: `msvcrt.locking`, the Windows-native equivalent already in
  the Python standard library.

Both are real, platform-native locking primitives, part of the standard
library for their respective platform -- neither is emulated, stubbed,
or vendored for the other. `locked()` is the only public name; callers
never touch `fcntl`/`msvcrt` or the platform branch directly, so this
module is the single place that knows which platform it is running on.
"""

from __future__ import annotations

import contextlib
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import IO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


@contextlib.contextmanager
def locked(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on `lock_path` for the duration of
    the `with` block, blocking until it is available. The lock file's
    contents are never read or written -- only its existence and lock
    state matter -- and it is created on first use.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as fh:
        _acquire(fh)
        try:
            yield
        finally:
            _release(fh)


if sys.platform == "win32":
    #: msvcrt.locking() locks a byte RANGE at the file's current position,
    #: not the whole file like flock -- one byte is enough, since the
    #: lock file's content is never read or written and Windows allows
    #: locking a range that doesn't yet exist in a zero-byte file.
    _LOCK_REGION_BYTES = 1
    #: msvcrt.LK_LOCK's own built-in retry (10 attempts, 1s apart) gives
    #: up and raises after ~10s -- too short for "blocking until
    #: available" to be a real promise under real contention. Wrapping
    #: the non-blocking mode (LK_NBLCK) in our own indefinite retry loop
    #: gives true unbounded blocking, with much finer-grained (and so
    #: more responsive) polling than LK_LOCK's 1-second cadence.
    _POLL_INTERVAL_SECONDS = 0.05

    def _acquire(fh: IO[str]) -> None:
        fh.seek(0)
        while True:
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, _LOCK_REGION_BYTES)
                return
            except OSError:
                time.sleep(_POLL_INTERVAL_SECONDS)

    def _release(fh: IO[str]) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, _LOCK_REGION_BYTES)

else:

    def _acquire(fh: IO[str]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _release(fh: IO[str]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

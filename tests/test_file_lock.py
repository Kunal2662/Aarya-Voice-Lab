"""Focused tests for core.file_lock -- the cross-platform advisory file
lock (fcntl.flock on POSIX, msvcrt.locking on Windows). Exercises the
real, unmocked locking mechanism on whichever platform this runs on, the
same way test_allocate_batch_is_race_free_under_concurrent_writers and
the registry concurrency tests already do for its callers -- this file
tests the primitive itself, directly.

Every helper thread is created with daemon=True and every wait/join is
bounded: if a genuine regression reintroduced a deadlock, these tests
must fail (or time out) on their own assertion, never hang the whole
suite waiting for a stuck non-daemon thread at interpreter exit.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from aarya_voice_lab.core.file_lock import locked


def _daemon_thread(target) -> threading.Thread:
    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t


def test_locked_creates_the_lock_file_and_parent_directories(tmp_path):
    lock_path = tmp_path / "nested" / "dir" / "x.lock"
    assert not lock_path.parent.is_dir()
    with locked(lock_path):
        pass
    assert lock_path.is_file()


def test_locked_can_be_reacquired_after_release(tmp_path):
    """A released lock must be genuinely available again -- not left in a
    half-held state that only happens to work once."""
    lock_path = tmp_path / "x.lock"
    with locked(lock_path):
        pass
    with locked(lock_path):
        pass


def test_locked_releases_on_exception_inside_the_with_block(tmp_path):
    """Cleanup must run via the context manager's own finally, not only
    on the happy path -- an exception inside the block must not leave
    the lock held forever."""
    lock_path = tmp_path / "x.lock"

    class _Boom(Exception):
        pass

    try:
        with locked(lock_path):
            raise _Boom("simulated failure inside the critical section")
    except _Boom:
        pass

    # If the lock were still held, this would time out rather than complete.
    acquired = threading.Event()

    def try_acquire():
        with locked(lock_path):
            acquired.set()

    t = _daemon_thread(try_acquire)
    t.join(timeout=10)
    assert acquired.is_set(), "lock was not released after an exception in the with block"


def test_locked_provides_real_mutual_exclusion_under_thread_contention(tmp_path):
    """Exercises the real, unmocked locking primitive -- not a mocked
    stand-in. 30 threads race to enter the same critical section; at
    most one may be inside it at any instant, verified by an explicit
    concurrent-entry counter (not just an absence-of-crash check)."""
    lock_path = tmp_path / "contention.lock"
    worker_count = 30
    barrier = threading.Barrier(worker_count)
    state_guard = threading.Lock()
    state = {"active": 0, "max_concurrent": 0, "violations": 0}

    def worker():
        barrier.wait()
        with locked(lock_path):
            with state_guard:
                state["active"] += 1
                state["max_concurrent"] = max(state["max_concurrent"], state["active"])
            time.sleep(0.01)  # widen the window so a real race would show up
            with state_guard:
                if state["active"] > 1:
                    state["violations"] += 1
                state["active"] -= 1

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        list(pool.map(lambda _: worker(), range(worker_count)))

    assert state["max_concurrent"] == 1, "more than one thread was inside the locked section at once"
    assert state["violations"] == 0


def test_locked_blocks_a_second_acquirer_until_the_first_releases(tmp_path):
    """Direct ordering proof: a second acquire attempt must not proceed
    until the first explicitly releases -- not merely "usually" true
    under contention, but true for one controlled interleaving."""
    lock_path = tmp_path / "ordering.lock"
    events: list[str] = []
    first_holds = threading.Event()
    second_may_release_first = threading.Event()

    def first():
        with locked(lock_path):
            events.append("first-acquired")
            first_holds.set()
            second_may_release_first.wait(timeout=10)
            events.append("first-released")

    def second():
        first_holds.wait(timeout=10)
        events.append("second-waiting")
        with locked(lock_path):
            events.append("second-acquired")

    t1 = _daemon_thread(first)
    t2 = _daemon_thread(second)
    time.sleep(0.2)  # let `second` genuinely block on the held lock
    assert events == ["first-acquired", "second-waiting"], "second acquired before first released"
    second_may_release_first.set()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert events == ["first-acquired", "second-waiting", "first-released", "second-acquired"]


def test_locked_on_different_paths_does_not_contend(tmp_path):
    """The lock is scoped to its specific path -- two distinct lock files
    must be independently, simultaneously acquirable. Both waits are
    bounded, so a real regression (lock_b blocking on lock_a) fails the
    assertion below rather than hanging the test."""
    lock_a = tmp_path / "a.lock"
    lock_b = tmp_path / "b.lock"
    release_a = threading.Event()
    b_acquired = threading.Event()

    def hold_a():
        with locked(lock_a):
            release_a.wait(timeout=10)

    def acquire_b():
        with locked(lock_b):
            b_acquired.set()

    t_a = _daemon_thread(hold_a)
    t_b = _daemon_thread(acquire_b)
    t_b.join(timeout=5)
    release_a.set()
    t_a.join(timeout=10)

    assert b_acquired.is_set(), "acquiring an unrelated lock path blocked on a held, different lock"

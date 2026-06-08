"""The advisory write lock (.kb/lock). Hermetic: no network; staleness is tested
with a real reaped child pid (dead on this host) rather than a guessed number."""

import json
import os
import socket
import subprocess

import pytest

from scrip import cli, errors, lock, lock_path


def _dead_pid() -> int:
    """A pid that is definitely not alive on this host (spawned then reaped)."""
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def _write_lock_file(root, pid):
    p = lock_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"pid": pid, "host": socket.gethostname(), "acquired_at": "2000-01-01T00:00:00Z"}
        ),
        encoding="utf-8",
    )
    return p


# --- acquire / release ------------------------------------------------------
def test_acquire_writes_holder_info(tmp_path):
    info = lock.acquire(tmp_path)
    try:
        data = json.loads(lock_path(tmp_path).read_text())
        assert data["pid"] == os.getpid()
        assert data["host"] == socket.gethostname()
        assert "acquired_at" in data
        assert info["pid"] == os.getpid()
    finally:
        lock.release(tmp_path, info)


def test_second_acquire_is_blocked_exit_2(tmp_path):
    info = lock.acquire(tmp_path)
    try:
        with pytest.raises(errors.LockError) as ei:
            lock.acquire(tmp_path)
        assert ei.value.exit_code == 2
    finally:
        lock.release(tmp_path, info)


def test_write_lock_releases_and_is_reacquirable(tmp_path):
    with lock.write_lock(tmp_path):
        assert lock_path(tmp_path).exists()
    assert not lock_path(tmp_path).exists()
    with lock.write_lock(tmp_path):  # no leftover lock blocks us
        assert lock_path(tmp_path).exists()


def test_release_only_removes_our_own_lock(tmp_path):
    # If another holder replaced the lock, releasing with our stale info is a no-op.
    ours = lock.acquire(tmp_path)
    lock_path(tmp_path).write_text(
        json.dumps({"pid": 999999, "host": socket.gethostname(), "acquired_at": "x"})
    )
    lock.release(tmp_path, ours)
    assert lock_path(tmp_path).exists()  # we did not clobber the other holder
    lock_path(tmp_path).unlink()


# --- staleness --------------------------------------------------------------
def test_leftover_temp_from_recycled_pid_does_not_block_acquire(tmp_path, monkeypatch):
    """A temp file left by a crashed process must not be mistaken for a held lock
    when a later process reuses its pid. The temp name must be unique, not keyed
    on pid, so it never collides and only a real `.kb/lock` blocks acquisition."""
    d = lock_path(tmp_path).parent
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(lock.os, "getpid", lambda: 4242)
    (d / "lock.4242.tmp").write_text("leftover from a crashed acquire")
    info = lock.acquire(tmp_path)  # must succeed: no real lock is held
    try:
        assert lock_path(tmp_path).exists()
    finally:
        lock.release(tmp_path, info)


def test_stale_lock_is_reclaimed_on_acquire(tmp_path):
    _write_lock_file(tmp_path, _dead_pid())
    info = lock.acquire(tmp_path)  # breaks the dead lock and takes it
    try:
        assert json.loads(lock_path(tmp_path).read_text())["pid"] == os.getpid()
    finally:
        lock.release(tmp_path, info)


def test_lock_from_other_host_is_not_stale():
    assert lock.is_stale({"pid": 1, "host": "some-other-host", "acquired_at": "x"}) is False


def test_unreadable_lock_is_stale():
    assert lock.is_stale(None) is True


def test_empty_lock_is_not_reclaimed_on_acquire(tmp_path):
    """A lock that exists but is not yet readable may be a competing writer caught
    between exclusive-create and payload-write. ``acquire`` must refuse it, not
    reclaim it — otherwise two writers could both proceed. (``unlock`` may still
    clear it as junk, since that is an explicit user action.)"""
    p = lock_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")  # empty -> _read returns None
    with pytest.raises(errors.LockError):
        lock.acquire(tmp_path)
    assert p.exists()  # not silently reclaimed out from under the other writer
    assert lock.unlock(tmp_path) is True  # explicit cleanup still works


# --- unlock -----------------------------------------------------------------
def test_unlock_refuses_live_lock_without_force(tmp_path):
    info = lock.acquire(tmp_path)
    try:
        with pytest.raises(errors.UsageError):
            lock.unlock(tmp_path, force=False)
        assert lock.unlock(tmp_path, force=True) is True
        assert not lock_path(tmp_path).exists()
    finally:
        lock.release(tmp_path, info)


def test_unlock_removes_stale_lock_without_force(tmp_path):
    _write_lock_file(tmp_path, _dead_pid())
    assert lock.unlock(tmp_path) is True
    assert not lock_path(tmp_path).exists()


def test_unlock_absent_is_noop(tmp_path):
    assert lock.unlock(tmp_path) is False


# --- CLI integration --------------------------------------------------------
def test_cmd_stamp_releases_lock(kb):
    kb.add_raw("a", "# A\n\nAlpha content.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    assert cli.main(["stamp", "--root", str(kb.root)]) == 0
    assert not lock_path(kb.root).exists()  # lock released after the write


def test_cmd_stamp_blocked_when_locked_exit_2(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    info = lock.acquire(kb.root)
    try:
        assert cli.main(["stamp", "--root", str(kb.root)]) == 2
    finally:
        lock.release(kb.root, info)

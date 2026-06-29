"""Advisory multi-writer lock for mutating commands (``.kb/lock``).

scriptorium is single-writer by contract: ``facts/`` and ``wiki/`` are compiled
from ``raw/`` by one agent at a time. This makes that *advisory* — it guards the
write commands (``stamp``, and later ``ingest``/``new``) so two concurrent
writers don't interleave stamps and edits. Reads (``status``, ``verify``,
``query``, ``search``) never lock.

The lock is a small JSON file created atomically with ``O_CREAT|O_EXCL`` holding
``{pid, host, acquired_at}``. A lock whose holder is a dead process *on this
host* is **stale** and is reclaimed automatically on acquire. A lock that looks
live is **waited on**: ``acquire`` polls (with backoff) up to a timeout —
``SCRIP_LOCK_TIMEOUT`` seconds, default 10 — so two agents serialize cooperatively
rather than one failing immediately. If the lock is still held when the wait
elapses it fails (exit 2) and points the user at ``scrip unlock``; ``timeout=0``
keeps the old fail-fast behavior. A lock from another host is treated as live (we
can't prove the process dead), so it is waited on but never reclaimed.

It is advisory, not a kernel mutex: a tiny TOCTOU window remains when reclaiming
a stale lock, and waiting is best-effort polling, not a fair queue. That is
acceptable for the single-machine workflow this guards; it is a guardrail against
accidental concurrent writes, not a distributed lock manager.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import lock_path
from .errors import LockError, UsageError

# How long ``acquire`` waits for a busy lock before giving up (seconds). The default
# is cooperative: concurrent writers serialize rather than failing fast. ``0`` keeps
# the old fail-fast behavior; ``SCRIP_LOCK_TIMEOUT`` overrides it. The poll interval
# backs off from _POLL_MIN to _POLL_MAX so a freed lock is taken promptly without
# busy-spinning.
_DEFAULT_LOCK_TIMEOUT = 10.0
_POLL_MIN = 0.025
_POLL_MAX = 0.25


def _lock_timeout(explicit: float | None) -> float:
    """Seconds ``acquire`` should wait for a busy lock. An explicit argument wins;
    otherwise read ``SCRIP_LOCK_TIMEOUT`` (default :data:`_DEFAULT_LOCK_TIMEOUT`). A
    missing or unparseable env value falls back to the default; negatives clamp to 0
    (fail fast)."""
    if explicit is not None:
        return max(0.0, explicit)
    raw = os.environ.get("SCRIP_LOCK_TIMEOUT")
    if raw is None or not raw.strip():
        return _DEFAULT_LOCK_TIMEOUT
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_LOCK_TIMEOUT


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _holder_info() -> dict:
    return {"pid": os.getpid(), "host": socket.gethostname(), "acquired_at": _now()}


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _pid_alive(pid: int) -> bool:
    """Whether ``pid`` is a live process on this host. ``signal 0`` probes
    existence without delivering a signal."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user
    except OSError:
        return True  # unknown error: assume live (don't reclaim on a guess)
    return True


def is_stale(info: dict | None) -> bool:
    """True iff this lock is safe for an *explicit* ``unlock`` to remove.

    An unreadable/empty lock is removable junk here. A lock from another host is
    *not* stale (we cannot prove its process dead). Otherwise it is stale exactly
    when its pid is no longer alive here. Note ``acquire`` uses the stricter
    :func:`_reclaimable` instead — it must never reclaim an empty lock, which may
    be a competing writer caught mid-creation.
    """
    if not info:
        return True
    if info.get("host") != socket.gethostname():
        return False
    pid = info.get("pid")
    if not isinstance(pid, int):
        return True
    return not _pid_alive(pid)


def _reclaimable(info: dict | None) -> bool:
    """Whether ``acquire`` may auto-break this lock. Stricter than
    :func:`is_stale`: only a *fully-readable* lock whose holder is a dead process
    on this host. An unreadable/empty lock is NOT reclaimable — it may be another
    writer between exclusive-create and payload-write — so it requires an explicit
    ``scrip unlock``."""
    if not info or info.get("host") != socket.gethostname():
        return False
    pid = info.get("pid")
    if not isinstance(pid, int):
        return False
    return not _pid_alive(pid)


def _describe(info: dict | None) -> str:
    if not info:
        return "an unreadable lock file"
    return f"pid {info.get('pid')} on {info.get('host')} since {info.get('acquired_at')}"


def _create(path: Path, payload: bytes) -> None:
    """Atomically publish a fully-written lock file. Write the payload to a
    *uniquely-named* temp file in the lock directory, then hard-link it into
    place: ``os.link`` is atomic and raises ``FileExistsError`` iff the lock is
    already held, so the lock is never observed empty or half-written.

    The temp name comes from ``mkstemp`` (random, never reused), so a temp left by
    a crashed process can never collide with a new acquire — and the only
    ``FileExistsError`` that escapes is the genuine ``os.link`` "lock held" case,
    not a temp-creation clash."""
    fd, tmpname = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(tmpname)
    try:
        # mkstemp creates the inode 0600; os.link publishes that same inode as the
        # lock, so restore the 0644 the lock had before mkstemp — otherwise another
        # user on a shared checkout can't read a dead holder to reclaim it.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.link(tmp, path)  # atomic exclusive publish; raises iff lock held
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def acquire(root: Path, *, timeout: float | None = None) -> dict:
    """Take the lock, returning the holder info. Reclaims a *provably-dead* lock
    immediately. If the lock looks live (or is mid-creation by another writer),
    *waits* — polling with backoff — up to ``timeout`` seconds for it to free, then
    raises :class:`LockError` (exit 2) if it is still held. ``timeout`` defaults to
    ``SCRIP_LOCK_TIMEOUT`` (``10`` s); ``timeout=0`` fails fast (the old behavior).
    A holder that dies *during* the wait is reclaimed on the next poll."""
    p = lock_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    info = _holder_info()
    payload = (json.dumps(info, ensure_ascii=False) + "\n").encode("utf-8")
    wait = _lock_timeout(timeout)
    deadline = time.monotonic() + wait
    poll = _POLL_MIN
    while True:
        try:
            _create(p, payload)
            return info
        except FileExistsError:
            pass

        existing = _read(p)
        if _reclaimable(existing):
            # A provably-dead lock on this host: break it and retry immediately.
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            try:
                _create(p, payload)
                return info
            except FileExistsError:
                pass  # raced with another writer; re-evaluate (and wait if time left)
            existing = _read(p)

        # Live, other-host, or not-yet-readable. Wait for it to free if the budget
        # has time left; otherwise give up with the appropriate diagnostic.
        if time.monotonic() >= deadline:
            waited = f" after waiting {wait:g}s" if wait else ""
            if existing is None:
                raise LockError(
                    ".kb/lock is held but not yet readable (another writer may be "
                    f"acquiring it){waited}. Retry; run `scrip unlock --force` if it "
                    "is stuck."
                ) from None
            raise LockError(
                f"vault is locked by another writer ({_describe(existing)}){waited}. "
                f"Wait for it to finish, or run `scrip unlock --force` if it is stuck."
            ) from None
        time.sleep(min(poll, deadline - time.monotonic()))
        poll = min(poll * 2, _POLL_MAX)


def release(root: Path, info: dict | None = None) -> None:
    """Remove the lock if we still hold it. When ``info`` is given, only remove a
    lock whose pid matches, so we never clobber a lock another writer took after
    we reclaimed a stale one."""
    p = lock_path(root)
    existing = _read(p)
    if existing is None:
        return
    if info is not None and existing.get("pid") != info.get("pid"):
        return
    try:
        p.unlink()
    except FileNotFoundError:
        pass


@contextmanager
def write_lock(root: Path, *, timeout: float | None = None):
    info = acquire(root, timeout=timeout)
    try:
        yield info
    finally:
        release(root, info)


def unlock(root: Path, force: bool = False) -> bool:
    """Remove ``.kb/lock``. Without ``force`` only a stale (or unreadable) lock is
    removed and a live-looking lock is refused (exit 2). Returns whether a lock
    was removed."""
    p = lock_path(root)
    if not p.exists():
        return False
    info = _read(p)
    if not force and not is_stale(info):
        raise UsageError(
            f"refusing to remove a live lock ({_describe(info)}); pass --force to "
            f"override."
        )
    try:
        p.unlink()
    except FileNotFoundError:
        return False
    return True

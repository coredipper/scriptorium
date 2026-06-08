"""Advisory multi-writer lock for mutating commands (``.kb/lock``).

scriptorium is single-writer by contract: ``facts/`` and ``wiki/`` are compiled
from ``raw/`` by one agent at a time. This makes that *advisory* — it guards the
write commands (``stamp``, and later ``ingest``/``new``) so two concurrent
writers don't interleave stamps and edits. Reads (``status``, ``verify``,
``query``, ``search``) never lock.

The lock is a small JSON file created atomically with ``O_CREAT|O_EXCL`` holding
``{pid, host, acquired_at}``. A lock whose holder is a dead process *on this
host* is **stale** and is reclaimed automatically on acquire; a lock that looks
live fails fast (exit 2) and points the user at ``scrip unlock``. A lock from
another host is treated as live (we can't prove the process dead).

It is advisory, not a kernel mutex: a tiny TOCTOU window remains when reclaiming
a stale lock. That is acceptable for the single-machine, single-agent workflow
this guards; it is a guardrail against accidental concurrent writes, not a
distributed lock manager.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import lock_path
from .errors import LockError, UsageError


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


def acquire(root: Path) -> dict:
    """Take the lock, returning the holder info. Reclaims a *provably-dead* lock
    once; raises :class:`LockError` (exit 2) if the lock looks live or is being
    created by another writer."""
    p = lock_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    info = _holder_info()
    payload = (json.dumps(info, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        _create(p, payload)
        return info
    except FileExistsError:
        pass

    existing = _read(p)
    if not _reclaimable(existing):
        if existing is None:
            raise LockError(
                ".kb/lock is held but not yet readable (another writer may be "
                "acquiring it). Retry; run `scrip unlock --force` if it is stuck."
            ) from None
        raise LockError(
            f"vault is locked by another writer ({_describe(existing)}). Wait for "
            f"it to finish, or run `scrip unlock --force` if it is stuck."
        ) from None

    # Reclaim a clearly-dead lock and retry once.
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    try:
        _create(p, payload)
    except FileExistsError:
        raise LockError(
            "could not acquire .kb/lock (raced with another writer); retry, or "
            "`scrip unlock` if it is stuck."
        ) from None
    return info


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
def write_lock(root: Path):
    info = acquire(root)
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

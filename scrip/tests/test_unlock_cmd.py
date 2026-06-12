"""`scrip unlock` at the CLI level: stale locks clear, live locks need --force."""

import json
import subprocess

from scrip import cli, lock, lock_path


def _dead_pid() -> int:
    """A pid that provably belonged to a process that has exited (spawn + wait)."""
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


def test_unlock_with_no_lock_is_a_noop(kb, capsys):
    rc = cli.main(["unlock", "--json", "--root", str(kb.root)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"removed": False}


def test_unlock_removes_a_dead_holders_lock(kb):
    import socket

    lock_path(kb.root).write_text(
        json.dumps({"pid": _dead_pid(), "host": socket.gethostname(), "acquired_at": "x"}),
        encoding="utf-8",
    )
    assert cli.main(["unlock", "--root", str(kb.root)]) == 0
    assert not lock_path(kb.root).exists()


def test_unlock_refuses_a_live_lock_without_force(kb):
    info = lock.acquire(kb.root)  # held by our own live pid
    try:
        assert cli.main(["unlock", "--root", str(kb.root)]) == 2
        assert lock_path(kb.root).exists()
        assert cli.main(["unlock", "--force", "--root", str(kb.root)]) == 0
        assert not lock_path(kb.root).exists()
    finally:
        lock.release(kb.root, info)

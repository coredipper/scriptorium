"""The per-cycle summary behind `scrip watch`, plus the poll loop itself
(driven for one cycle by making `time.sleep` deliver the Ctrl-C)."""

import time

from scrip import cli


def test_watch_summary_clean_vault(kb):
    kb.add_raw("a", "# A\n\nAlpha content.\n")
    kb.add_wiki("x", ["raw/a"])
    assert cli._watch_summary(kb.root) == {
        "stale": 0,
        "ok": 1,
        "broken": 0,
        "ambiguous": 0,
    }


def test_watch_summary_reports_stale(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    summary = cli._watch_summary(kb.root)
    assert summary["stale"] == 1
    assert summary["ok"] == 0


def test_watch_loop_runs_a_cycle_and_exits_0_on_interrupt(kb, capsys, monkeypatch):
    kb.add_raw("a", "# A\n\nAlpha content.\n")
    kb.add_wiki("x", ["raw/a"])

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", interrupt)
    rc = cli.main(["watch", "--root", str(kb.root)])
    assert rc == 0  # Ctrl-C is a clean exit for watch, not 130
    out = capsys.readouterr().out
    assert "watching" in out
    assert "ok — stale=0" in out  # one full status+verify cycle ran


def test_watch_loop_flags_findings(kb, capsys, monkeypatch):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    monkeypatch.setattr(time, "sleep", lambda _s: (_ for _ in ()).throw(KeyboardInterrupt))
    assert cli.main(["watch", "--root", str(kb.root)]) == 0
    assert "FINDINGS" in capsys.readouterr().out

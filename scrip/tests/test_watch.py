"""The per-cycle summary behind `scrip watch` (the loop itself is a thin wrapper)."""

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

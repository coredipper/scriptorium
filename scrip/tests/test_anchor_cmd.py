"""`scrip anchor` — mint a verified provenance anchor for a quote. Deterministic,
no model; reuses the anchors create+verify path."""

import json

from scrip import anchors, cli


def test_anchor_emits_resolving_anchor_and_footnote(kb, capsys):
    src = "# H\n\nThe quick brown fox jumps over the lazy dog.\n"
    kb.add_raw("s", src)
    rc = cli.main(
        [
            "anchor",
            "The quick brown fox jumps over the lazy dog.",
            "--source",
            "raw/s",
            "--root",
            str(kb.root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "raw/s#qh:" in out
    assert "[^a1]: anchor=raw/s#qh:" in out


def test_anchor_json_anchor_actually_resolves(kb, capsys):
    src = "# H\n\nA unique and unambiguous sentence.\n"
    kb.add_raw("s", src)
    rc = cli.main(
        [
            "anchor",
            "A unique and unambiguous sentence.",
            "--source",
            "raw/s",
            "--root",
            str(kb.root),
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "OK"
    assert data["target"].startswith("raw/s#")
    assert anchors.resolve(src, data["anchor"]) == "OK"


def test_anchor_ambiguous_quote_exits_1(kb):
    kb.add_raw("s", "alpha beta. alpha beta.\n")
    rc = cli.main(["anchor", "alpha beta.", "--source", "raw/s", "--root", str(kb.root)])
    assert rc == 1  # not unique — agent must lengthen the quote


def test_anchor_absent_quote_is_broken_exits_1(kb):
    kb.add_raw("s", "# H\n\nNothing relevant here.\n")
    rc = cli.main(["anchor", "this text is absent", "--source", "raw/s", "--root", str(kb.root)])
    assert rc == 1


def test_anchor_source_without_raw_prefix_is_accepted(kb, capsys):
    kb.add_raw("s", "# H\n\nLenient source reference.\n")
    rc = cli.main(["anchor", "Lenient source reference.", "--source", "s", "--root", str(kb.root)])
    assert rc == 0
    assert "raw/s#qh:" in capsys.readouterr().out


def test_anchor_rejects_unsafe_source_exit_2(kb):
    kb.add_raw("s", "# H\n\nSome text.\n")
    rc = cli.main(["anchor", "Some text.", "--source", "../../etc/passwd", "--root", str(kb.root)])
    assert rc == 2  # traversal in the source id is rejected, not read


def test_anchor_custom_footnote_label(kb, capsys):
    kb.add_raw("s", "# H\n\nDistinct labelled line.\n")
    rc = cli.main(
        [
            "anchor",
            "Distinct labelled line.",
            "--source",
            "raw/s",
            "--label",
            "b7",
            "--root",
            str(kb.root),
        ]
    )
    assert rc == 0
    assert "[^b7]: anchor=raw/s#qh:" in capsys.readouterr().out

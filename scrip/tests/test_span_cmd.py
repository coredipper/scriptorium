"""`scrip span` — resolve an anchor and print the cited text. Read-only; lets an
agent read both sides of a contradiction (RECONCILE) without re-implementing
anchor resolution."""

import json

import pytest

from scrip import anchors, cli

SRC = "# H\n\nThe quick brown fox jumps over the lazy dog.\n\nalpha beta. alpha beta.\n"


def test_span_prints_cited_text(kb, capsys):
    kb.add_raw("s", SRC)
    anchor = anchors.make_anchor(SRC, "The quick brown fox jumps over the lazy dog.")
    rc = cli.main(["span", f"raw/s#{anchor}", "--root", str(kb.root)])
    assert rc == 0
    # the cited span is shown (normalized: lowercased, whitespace-collapsed)
    assert "the quick brown fox jumps over the lazy dog." in capsys.readouterr().out.lower()


def test_span_json_shape(kb, capsys):
    kb.add_raw("s", SRC)
    anchor = anchors.make_anchor(SRC, "The quick brown fox jumps over the lazy dog.")
    rc = cli.main(["span", f"raw/s#{anchor}", "--json", "--root", str(kb.root)])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"target", "status", "text"}
    assert data["status"] == "OK"
    assert "quick brown fox" in data["text"]


def test_span_by_claim_id(kb, capsys):
    kb.add_raw("s", SRC)
    kb.add_claim("clm_0001", "s", "The quick brown fox jumps over the lazy dog.")
    rc = cli.main(["span", "--claim", "clm_0001", "--json", "--root", str(kb.root)])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "OK"
    assert "quick brown fox" in data["text"]


def test_span_ambiguous_exits_1(kb, capsys):
    kb.add_raw("s", SRC)
    anchor = anchors.make_anchor(SRC, "alpha beta.")  # appears twice
    rc = cli.main(["span", f"raw/s#{anchor}", "--json", "--root", str(kb.root)])
    assert rc == 1
    assert json.loads(capsys.readouterr().out)["status"] == "AMBIGUOUS"


def test_span_broken_exits_1(kb, capsys):
    kb.add_raw("s", SRC)
    # a well-formed anchor whose quote is absent from the source
    anchor = anchors.make_anchor("a totally different document about cats", "totally different")
    rc = cli.main(["span", f"raw/s#{anchor}", "--json", "--root", str(kb.root)])
    assert rc == 1
    assert json.loads(capsys.readouterr().out)["status"] == "BROKEN"


def test_span_unsafe_source_is_usage_error(kb):
    kb.add_raw("s", SRC)
    anchor = anchors.make_anchor(SRC, "The quick brown fox jumps over the lazy dog.")
    assert cli.main(["span", f"../../etc/passwd#{anchor}", "--root", str(kb.root)]) == 2


def test_span_missing_source_is_data_error(kb):
    kb.add_raw("s", SRC)
    anchor = anchors.make_anchor(SRC, "The quick brown fox jumps over the lazy dog.")
    assert cli.main(["span", f"raw/absent#{anchor}", "--root", str(kb.root)]) == 3


def test_span_unknown_claim_is_data_error(kb):
    kb.add_raw("s", SRC)
    assert cli.main(["span", "--claim", "clm_9999", "--root", str(kb.root)]) == 3


def test_span_requires_a_target(kb):
    with pytest.raises(SystemExit) as e:
        cli.main(["span", "--root", str(kb.root)])
    assert e.value.code == 2


def test_span_target_without_anchor_is_usage_error(kb):
    kb.add_raw("s", SRC)
    assert cli.main(["span", "raw/s", "--root", str(kb.root)]) == 2  # no '#<anchor>'

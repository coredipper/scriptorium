"""--json output shapes across commands. This is the de facto API the harness
(and any scripting agent) consumes — shape drift is a breaking change."""

import json

from scrip import cli


def _out(capsys):
    return json.loads(capsys.readouterr().out)


def test_verify_json_shape(kb, capsys):
    kb.add_raw("a", "# A\n\nA unique cited sentence.\n")
    kb.add_claim("clm_0001", "a", "A unique cited sentence.")
    assert cli.main(["verify", "--json", "--root", str(kb.root)]) == 0
    data = _out(capsys)
    assert set(data) == {"checked", "ok", "ambiguous", "broken"}
    assert data["checked"] == data["ok"] == 1


def test_stamp_json_shape(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    assert cli.main(["stamp", "--json", "--root", str(kb.root)]) == 0
    [stamped] = _out(capsys)["stamped"]
    assert set(stamped) == {"id", "path", "input_hash"}
    assert stamped["input_hash"].startswith("sha256:")


def test_query_json_is_a_row_list(kb, capsys):
    kb.add_raw("a", "# A\n\nA unique cited sentence.\n")
    kb.add_claim("clm_0001", "a", "A unique cited sentence.", subject="s1")
    assert cli.main(["query", "claims", "--json", "--root", str(kb.root)]) == 0
    rows = _out(capsys)
    assert isinstance(rows, list)
    assert rows[0]["claim_id"] == "clm_0001"


def test_anchor_json_shape(kb, capsys):
    kb.add_raw("a", "# A\n\nA unique cited sentence.\n")
    rc = cli.main(
        ["anchor", "A unique cited sentence.", "--source", "raw/a", "--json",
         "--root", str(kb.root)]
    )
    assert rc == 0
    data = _out(capsys)
    assert set(data) == {"source_id", "anchor", "target", "status", "label", "footnote"}


def test_new_json_shape(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    assert cli.main(["new", "concept", "thing", "--from", "raw/a", "--json",
                     "--root", str(kb.root)]) == 0
    data = _out(capsys)
    assert set(data) == {"created", "id"}
    assert data["id"] == "concept/thing"

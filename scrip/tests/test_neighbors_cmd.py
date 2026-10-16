"""`scrip neighbors` — a focused, read-only view of one node's edges within N hops
of facts/graph.ndjson, instead of the whole-graph dump of `scrip query edges`."""

import json

from scrip import cli, neighbors


def _write(kb, fname, rows):
    p = kb.root / "vault" / "facts" / fname
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _ent(slug, name=None, kind="system"):
    return {"entity_id": f"entity/{slug}", "name": name or slug.title(), "kind": kind}


def _edge(src, dst, kind="depends-on", **kw):
    return {"src": f"entity/{src}", "dst": f"entity/{dst}", "kind": kind, **kw}


def _graph(kb):
    # a -> b -> c -> d, plus x -> a (incoming), a -alt-> e, and a cycle c -> a.
    _write(kb, "entities.ndjson", [_ent(s) for s in "abcdex"])
    _write(
        kb,
        "graph.ndjson",
        [
            _edge("a", "b"),
            _edge("b", "c"),
            _edge("c", "d"),
            _edge("x", "a", "part-of"),
            _edge("a", "e", "alternative-to"),
            _edge("c", "a"),
        ],
    )


def _pairs(result):
    return [(e["src"], e["dst"], e["kind"]) for e in result["edges"]]


def test_depth_one_both_directions(kb):
    _graph(kb)
    r = neighbors.neighborhood(kb.root, "entity/a")
    assert r["root"] == "entity/a" and r["depth"] == 1 and r["truncated"] is False
    assert _pairs(r) == [
        ("entity/a", "entity/b", "depends-on"),
        ("entity/a", "entity/e", "alternative-to"),
        ("entity/c", "entity/a", "depends-on"),
        ("entity/x", "entity/a", "part-of"),
    ]
    assert all(e["hop"] == 1 for e in r["edges"])
    assert [n["id"] for n in r["nodes"]] == [
        "entity/a", "entity/b", "entity/c", "entity/e", "entity/x",
    ]


def test_depth_two_reaches_second_hop_and_cycle_terminates(kb):
    _graph(kb)
    r = neighbors.neighborhood(kb.root, "entity/a", depth=2, direction="out")
    assert _pairs(r) == [
        ("entity/a", "entity/b", "depends-on"),
        ("entity/a", "entity/e", "alternative-to"),
        ("entity/b", "entity/c", "depends-on"),
    ]
    assert [e["hop"] for e in r["edges"]] == [1, 1, 2]
    # depth 3 closes the c -> a cycle and reaches d, each edge once
    r3 = neighbors.neighborhood(kb.root, "entity/a", depth=3, direction="out")
    assert len(_pairs(r3)) == len(set(_pairs(r3))) == 5


def test_kind_filter_and_direction_in(kb):
    _graph(kb)
    r = neighbors.neighborhood(kb.root, "entity/a", kinds=["part-of"])
    assert _pairs(r) == [("entity/x", "entity/a", "part-of")]
    r_in = neighbors.neighborhood(kb.root, "entity/a", direction="in")
    assert {e["dst"] for e in r_in["edges"]} == {"entity/a"}


def test_limit_sets_truncated(kb):
    _graph(kb)
    r = neighbors.neighborhood(kb.root, "entity/a", limit=2)
    assert len(r["edges"]) == 2 and r["truncated"] is True


def test_cited_edge_and_non_entity_node(kb):
    _write(kb, "entities.ndjson", [_ent("a")])
    _write(
        kb,
        "graph.ndjson",
        [{"src": "entity/a", "dst": "raw/paper", "kind": "cites",
          "source_id": "raw/paper", "anchor": "qh:ab|loc:0|len:5"}],
    )
    r = neighbors.neighborhood(kb.root, "raw/paper")
    [edge] = r["edges"]
    assert edge["anchor"] == "qh:ab|loc:0|len:5"
    assert {"id": "raw/paper"} in r["nodes"]  # not an entity: id only


def test_entity_without_edges(kb):
    _write(kb, "entities.ndjson", [_ent("lonely")])
    r = neighbors.neighborhood(kb.root, "entity/lonely")
    assert r["edges"] == [] and [n["id"] for n in r["nodes"]] == ["entity/lonely"]


def test_cli_unknown_node_is_data_error(kb, capsys):
    _graph(kb)
    assert cli.main(["neighbors", "entity/nope", "--root", str(kb.root)]) == 3
    assert "no such node: entity/nope" in capsys.readouterr().err


def test_cli_empty_facts_is_data_error(kb):
    assert cli.main(["neighbors", "entity/a", "--root", str(kb.root)]) == 3


def test_cli_depth_out_of_range_is_usage_error(kb):
    _graph(kb)
    assert cli.main(["neighbors", "entity/a", "--depth", "4", "--root", str(kb.root)]) == 2


def test_cli_json_is_stable(kb, capsys):
    _graph(kb)
    args = ["neighbors", "entity/a", "--depth", "2", "--json", "--root", str(kb.root)]
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert set(first) == {"root", "depth", "nodes", "edges", "truncated"}


def test_cli_text_output(kb, capsys):
    _graph(kb)
    assert cli.main(["neighbors", "entity/a", "--root", str(kb.root)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "entity/a  A (system)"
    assert "  -> depends-on  entity/b  B (system)" in out
    assert "  <- part-of  entity/x  X (system)" in out
    assert out[-1] == "4 edges, 5 nodes (depth 1)"

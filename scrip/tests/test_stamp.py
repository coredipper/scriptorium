from scrip import graph


def test_stamp_makes_unstamped_page_fresh(kb):
    kb.add_raw("a", "# A\n\nAlpha content here.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    # unstamped -> stale
    assert graph.compute_status(kb.root, use_cache=False)["stale"]
    # stamp -> fresh
    stamped = graph.stamp_artifacts(kb.root)
    assert any(s["id"] == "concept/x" for s in stamped)
    assert graph.compute_status(kb.root, use_cache=False)["stale"] == []


def test_stamp_then_mutate_goes_stale_again(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    graph.stamp_artifacts(kb.root)
    assert graph.compute_status(kb.root, use_cache=False)["stale"] == []
    kb.mutate_raw("a", "# A\n\nAlpha rewritten.\n")
    assert {s["id"] for s in graph.compute_status(kb.root, use_cache=False)["stale"]} == {
        "concept/x"
    }


def test_stamp_specific_path_only(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_raw("b", "# B\n\nBeta.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    kb.add_wiki("y", ["raw/b"], stamp=False)
    graph.stamp_artifacts(kb.root, ["vault/wiki/concepts/x.md"])
    stale = {s["id"] for s in graph.compute_status(kb.root, use_cache=False)["stale"]}
    assert "concept/x" not in stale  # stamped
    assert "concept/y" in stale  # left unstamped

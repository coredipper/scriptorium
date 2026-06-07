from scrip import graph


def test_fresh_vault_all_ok(kb):
    kb.add_raw("a", "# A\n\nAlpha content.\n")
    kb.add_wiki("x", ["raw/a"])
    res = graph.compute_status(kb.root, use_cache=False)
    assert res["stale"] == []
    assert "concept/x" in {o["id"] for o in res["ok"]}


def test_mutate_source_marks_only_dependents_stale(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_raw("b", "# B\n\nBeta.\n")
    kb.add_wiki("x", ["raw/a"])
    kb.add_wiki("y", ["raw/b"])
    graph.compute_status(kb.root, use_cache=True, rebuild=True)  # seed manifest

    kb.mutate_raw("a", "# A\n\nAlpha CHANGED.\n")
    res = graph.compute_status(kb.root, use_cache=True)

    assert {s["id"] for s in res["stale"]} == {"concept/x"}
    sx = next(s for s in res["stale"] if s["id"] == "concept/x")
    assert sx["changed_sources"] == ["raw/a"]
    assert "concept/y" in {o["id"] for o in res["ok"]}


def test_uncompiled_source_reported(kb):
    kb.add_raw("orphan", "# O\n\nNobody depends on me.\n")
    res = graph.compute_status(kb.root, use_cache=False)
    assert "raw/orphan" in {u["id"] for u in res["uncompiled"]}


def test_unstamped_page_is_stale(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    res = graph.compute_status(kb.root, use_cache=False)
    s = next(s for s in res["stale"] if s["id"] == "concept/x")
    assert "input-hash" in s["reason"]


def test_missing_source_is_stale(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a", "raw/ghost"])
    res = graph.compute_status(kb.root, use_cache=False)
    s = next(s for s in res["stale"] if s["id"] == "concept/x")
    assert "missing source" in s["reason"]


def test_status_exit_semantics_via_stale_list(kb):
    # cmd_status returns 1 iff result["stale"] is non-empty
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"])
    clean = graph.compute_status(kb.root, use_cache=False)
    assert not clean["stale"]
    kb.mutate_raw("a", "# A\n\ndifferent.\n")
    dirty = graph.compute_status(kb.root, use_cache=False)
    assert dirty["stale"]

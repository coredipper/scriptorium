import os

from scrip import cli, graph


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


def test_block_dep_stays_fresh_when_other_block_inserted(kb):
    """A page depending on a single block must not go stale when an unrelated
    block is inserted elsewhere in the source. Positional ids renumbered here and
    falsely staled the page; content-derived ids fix that."""
    kb.add_raw("a", "# A\n\nfirst fact.\n\nsecond fact.\n")
    bid = kb.block_id("a", "second fact")
    kb.add_wiki("x", [f"raw/a#{bid}"])
    assert graph.compute_status(kb.root, use_cache=False)["stale"] == []

    kb.mutate_raw("a", "# A\n\nfirst fact.\n\nINSERTED.\n\nsecond fact.\n")
    res = graph.compute_status(kb.root, use_cache=False)
    assert res["stale"] == []
    assert "concept/x" in {o["id"] for o in res["ok"]}


def test_block_dep_goes_stale_when_depended_block_edited(kb):
    kb.add_raw("a", "# A\n\nfirst fact.\n\nsecond fact.\n")
    bid = kb.block_id("a", "second fact")
    kb.add_wiki("x", [f"raw/a#{bid}"])
    assert graph.compute_status(kb.root, use_cache=False)["stale"] == []

    kb.mutate_raw("a", "# A\n\nfirst fact.\n\nsecond fact, revised.\n")
    res = graph.compute_status(kb.root, use_cache=False)
    assert "concept/x" in {s["id"] for s in res["stale"]}


def test_fast_trusts_mtime_size_and_can_miss_an_edit(kb):
    """`--fast` reuses the cached hash when (mtime, size) match, so an edit that
    preserves both is missed — the documented speed/guarantee tradeoff. Plain
    status always re-hashes and catches it."""
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"])
    graph.compute_status(kb.root, use_cache=True, rebuild=True)  # seed manifest

    p = kb.root / "vault" / "raw" / "a.md"
    st = p.stat()
    new = "# A\n\nBeta!.\n"  # same byte length as the original
    assert len(new.encode()) == st.st_size
    p.write_text(new, encoding="utf-8")
    os.utime(p, (st.st_atime, st.st_mtime))  # restore mtime → looks unchanged

    assert graph.compute_status(kb.root, use_cache=True)["stale"]  # plain: detected
    assert graph.compute_status(kb.root, use_cache=True, fast=True)["stale"] == []  # fast: missed


def test_fast_without_cache_falls_back_to_rehash(kb):
    """`fast` must not override `use_cache`: with the cache off there is nothing
    trustworthy to reuse, so it re-hashes and catches a same-mtime+size edit."""
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"])
    graph.compute_status(kb.root, use_cache=True, rebuild=True)
    p = kb.root / "vault" / "raw" / "a.md"
    st = p.stat()
    new = "# A\n\nBeta!.\n"
    assert len(new.encode()) == st.st_size
    p.write_text(new, encoding="utf-8")
    os.utime(p, (st.st_atime, st.st_mtime))
    assert graph.compute_status(kb.root, use_cache=False, fast=True)["stale"]


def test_status_fast_with_no_cache_is_usage_error(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"])
    assert cli.main(["status", "--no-cache", "--fast", "--root", str(kb.root)]) == 2


def test_fast_still_detects_a_normal_edit(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"])
    graph.compute_status(kb.root, use_cache=True, rebuild=True)
    kb.mutate_raw("a", "# A\n\nAlpha rewritten at length.\n")  # bumps mtime + size
    res = graph.compute_status(kb.root, use_cache=True, fast=True)
    assert "concept/x" in {s["id"] for s in res["stale"]}


def test_status_exit_semantics_via_stale_list(kb):
    # cmd_status returns 1 iff result["stale"] is non-empty
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"])
    clean = graph.compute_status(kb.root, use_cache=False)
    assert not clean["stale"]
    kb.mutate_raw("a", "# A\n\ndifferent.\n")
    dirty = graph.compute_status(kb.root, use_cache=False)
    assert dirty["stale"]

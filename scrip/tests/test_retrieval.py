"""Retrieval rung tests. Hermetic: the embeddings backend is an optional extra
not installed in the test env, so `search` exercises the grep fallback. (If the
backend *is* installed, no index is built here, so vector_search returns None and
we still fall back to grep.)"""

from scrip import retrieval


def test_grep_finds_relevant_block(kb):
    kb.add_raw(
        "rag",
        "# RAG\n\nFixed-size chunking discards document structure.\n\n"
        "An unrelated paragraph about gardening.\n",
    )
    out = retrieval.search(kb.root, "chunking structure", k=3)
    assert out["results"], "expected at least one hit"
    top = out["results"][0]
    assert top["source_id"] == "raw/rag"
    assert "chunking" in top["snippet"].lower()


def test_grep_ranks_by_term_frequency(kb):
    kb.add_raw("a", "# A\n\ncache cache cache rules everything.\n\ncache once.\n")
    out = retrieval.search(kb.root, "cache", k=2)
    assert out["results"][0]["score"] >= out["results"][-1]["score"]


def test_no_match_returns_empty(kb):
    kb.add_raw("a", "# A\n\nnothing relevant here.\n")
    out = retrieval.search(kb.root, "quantum zebra entanglement", k=3)
    assert out["results"] == []
    assert out["method"] == "grep"

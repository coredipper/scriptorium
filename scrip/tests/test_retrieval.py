"""Retrieval rung tests. Hermetic: the embeddings backend is an optional extra
not installed in the test env, so `search` exercises the grep fallback. (If the
backend *is* installed, no index is built here, so vector_search returns None and
we still fall back to grep.)"""

from scrip import cli, embeddings, retrieval


def test_index_unavailable_message_names_scriptoria(kb, capsys, monkeypatch):
    # Force the backend-absent branch (don't depend on whether the optional
    # embeddings extra happens to be installed) so `index` prints the install
    # hint — which must name the published PyPI package, not the taken `scrip`.
    monkeypatch.setattr(embeddings, "available", lambda: False)
    kb.add_raw("a", "# A\n\nAlpha.\n")
    assert cli.main(["index", "--root", str(kb.root)]) == 0
    out = capsys.readouterr().out
    assert "scriptoria[embeddings]" in out
    assert "scrip[embeddings]" not in out


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

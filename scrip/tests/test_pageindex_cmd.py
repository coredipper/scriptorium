"""PageIndex adapter tests. Hermetic: no real PageIndex dependency is installed;
the backend is monkeypatched with a deterministic tiny object."""

import json

from scrip import cli, pageindex_adapter, retrieval


class FakePageIndex:
    __version__ = "test"

    def build_index(self, *, source_id, text):
        start = text.index("Alpha section explains caching.")
        end = start + len("Alpha section explains caching.")
        return {
            "sections": [
                {"section_id": "alpha", "span_hint": [start, end], "score": 0.9},
                # Summaries that are not verbatim raw text must not enter cache.
                {"section_id": "summary", "snippet": "a generated summary absent from raw"},
            ]
        }

    def search(self, *, query, items, k):
        return [it for it in items if query.lower() in it["snippet"].lower()][:k]


def _fake_backend(monkeypatch):
    monkeypatch.setattr(pageindex_adapter, "_get_backend", lambda: FakePageIndex())


def test_pageindex_build_unavailable_exits_cleanly(kb, capsys, monkeypatch):
    monkeypatch.setattr(pageindex_adapter, "_get_backend", lambda: None)
    kb.add_raw("paper", "# Paper\n\nAlpha section explains caching.\n")
    rc = cli.main(["pageindex", "build", "raw/paper", "--json", "--root", str(kb.root)])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "unavailable"


def test_pageindex_build_persists_only_verbatim_raw_snippets(kb, capsys, monkeypatch):
    _fake_backend(monkeypatch)
    kb.add_raw(
        "paper",
        "# Paper\n\nAlpha section explains caching.\n\nBeta section covers indexing.\n",
    )
    rc = cli.main(["pageindex", "build", "raw/paper", "--json", "--root", str(kb.root)])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "built"
    assert data["sections_indexed"] == 1

    tree = json.loads(
        (kb.root / ".kb" / "pageindex" / "paper" / "tree.json").read_text(encoding="utf-8")
    )
    [item] = tree["items"]
    assert item["source_id"] == "raw/paper"
    assert item["section_id"] == "alpha"
    assert item["snippet"] == "Alpha section explains caching."
    assert "summary absent" not in json.dumps(tree)


def test_pageindex_search_cli_and_retrieval_integration(kb, capsys, monkeypatch):
    _fake_backend(monkeypatch)
    kb.add_raw(
        "paper",
        "# Paper\n\nAlpha section explains caching.\n\nBeta section covers indexing.\n",
    )
    assert cli.main(["pageindex", "build", "paper", "--root", str(kb.root)]) == 0
    capsys.readouterr()

    assert cli.main(["pageindex", "search", "Alpha", "--json", "--root", str(kb.root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["method"] == "pageindex"
    assert out["results"][0]["snippet"] == "Alpha section explains caching."

    routed = retrieval.search(kb.root, "Alpha", long_docs="pageindex")
    assert routed["method"] == "pageindex"
    assert routed["results"][0]["source_id"] == "raw/paper"


def test_search_long_docs_pageindex_cli_prints_section_results(kb, capsys, monkeypatch):
    _fake_backend(monkeypatch)
    kb.add_raw("paper", "# Paper\n\nAlpha section explains caching.\n")
    assert cli.main(["pageindex", "build", "paper", "--root", str(kb.root)]) == 0
    capsys.readouterr()

    rc = cli.main(["search", "Alpha", "--long-docs", "pageindex", "--root", str(kb.root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[pageindex]" in out
    assert "raw/paper#alpha" in out
    assert "Alpha section explains caching." in out


def test_pageindex_search_reuses_cached_verbatim_snippet(kb, monkeypatch):
    class SummarySearchBackend(FakePageIndex):
        def search(self, *, query, items, k):
            return [
                {
                    "source_id": "raw/paper",
                    "section_id": "alpha",
                    "snippet": "fabricated summary absent from raw",
                    "score": 99,
                }
            ]

    monkeypatch.setattr(pageindex_adapter, "_get_backend", lambda: SummarySearchBackend())
    kb.add_raw("paper", "# Paper\n\nAlpha section explains caching.\n")
    pageindex_adapter.build_index(kb.root, "paper")

    out = pageindex_adapter.search(kb.root, "Alpha")
    assert out is not None
    assert out["results"][0]["snippet"] == "Alpha section explains caching."
    assert "fabricated summary" not in json.dumps(out)


def test_pageindex_cache_revalidates_snippets_after_raw_change(kb, monkeypatch):
    _fake_backend(monkeypatch)
    kb.add_raw("paper", "# Paper\n\nAlpha section explains caching.\n")
    pageindex_adapter.build_index(kb.root, "paper")
    kb.mutate_raw("paper", "# Paper\n\nNew intro.\n\nAlpha section explains caching.\n")

    out = pageindex_adapter.search(kb.root, "Alpha")
    assert out is not None
    assert out["stale_index"] is True
    assert out["results"][0]["snippet"] == "Alpha section explains caching."


def test_pageindex_cache_drops_stale_snippets_absent_from_raw(kb, monkeypatch):
    _fake_backend(monkeypatch)
    kb.add_raw("paper", "# Paper\n\nAlpha section explains caching.\n")
    pageindex_adapter.build_index(kb.root, "paper")
    kb.mutate_raw("paper", "# Paper\n\nAlpha section changed completely.\n")

    assert pageindex_adapter.search(kb.root, "Alpha") is None
    out = retrieval.search(kb.root, "Alpha", long_docs="pageindex")
    assert out["method"] == "grep"
    assert "changed completely" in out["results"][0]["snippet"]


def test_pageindex_lexical_fallback_uses_query_time_scores(kb, monkeypatch):
    class RankedBuildBackend:
        __version__ = "test"

        def build_index(self, *, source_id, text):
            alpha_start = text.index("Alpha Alpha section.")
            beta_start = text.index("Beta section.")
            return {
                "sections": [
                    {
                        "section_id": "alpha",
                        "span_hint": [alpha_start, alpha_start + len("Alpha Alpha section.")],
                        "score": 1,
                    },
                    {
                        "section_id": "beta",
                        "span_hint": [beta_start, beta_start + len("Beta section.")],
                        "score": 100,
                    },
                ]
            }

    monkeypatch.setattr(pageindex_adapter, "_get_backend", lambda: RankedBuildBackend())
    kb.add_raw("paper", "# Paper\n\nAlpha Alpha section.\n\nBeta section.\n")
    pageindex_adapter.build_index(kb.root, "paper")
    monkeypatch.setattr(pageindex_adapter, "_get_backend", lambda: None)

    out = pageindex_adapter.search(kb.root, "Alpha section")
    assert out is not None
    assert [r["section_id"] for r in out["results"]] == ["alpha", "beta"]
    assert [r["score"] for r in out["results"]] == [3.0, 1.0]


def test_search_long_docs_pageindex_falls_back_without_cache(kb):
    kb.add_raw("paper", "# Paper\n\nAlpha section explains caching.\n")
    out = retrieval.search(kb.root, "Alpha", long_docs="pageindex")
    assert out["method"] == "grep"
    assert out["results"][0]["source_id"] == "raw/paper"


def test_pageindex_search_missing_cache_json(kb, capsys):
    rc = cli.main(["pageindex", "search", "anything", "--json", "--root", str(kb.root)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "missing"
    assert out["results"] == []

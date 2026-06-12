"""`scrip index` + the embeddings search path, exercised end-to-end with a
deterministic toy encoder. The real backend (model2vec) stays out of the test
env — it downloads weights — but the index math, persistence, fingerprint
staleness, and CLI surface all run for real (numpy is a dev dependency)."""

import json

from scrip import cli, embeddings, retrieval

_DIM = 16


class ToyModel:
    """Deterministic bag-of-words encoder: each token adds weight to one of
    _DIM buckets (by character-sum). No randomness, no network."""

    def encode(self, texts):
        out = []
        for text in texts:
            v = [0.0] * _DIM
            for token in text.lower().split():
                v[sum(map(ord, token)) % _DIM] += 1.0
            out.append(v)
        return out


def _with_toy_backend(monkeypatch):
    monkeypatch.setattr(embeddings, "_get_model", lambda: ToyModel())


def test_index_builds_and_search_uses_embeddings(kb, capsys, monkeypatch):
    _with_toy_backend(monkeypatch)
    kb.add_raw(
        "src",
        "# S\n\ncaching caching caching answers.\n\ngardening tulips daffodils.\n",
    )
    rc = cli.main(["index", "--json", "--root", str(kb.root)])
    assert rc == 0
    built = json.loads(capsys.readouterr().out)
    assert built["status"] == "built"
    assert built["blocks_indexed"] == 3  # heading + two paragraphs

    out = retrieval.search(kb.root, "caching", k=2)
    assert out["method"] == "embeddings"
    assert out["stale_index"] is False
    assert "caching" in out["results"][0]["snippet"]


def test_search_cli_reports_stale_index_after_source_change(kb, capsys, monkeypatch):
    _with_toy_backend(monkeypatch)
    kb.add_raw("src", "# S\n\noriginal indexed content here.\n")
    assert cli.main(["index", "--root", str(kb.root)]) == 0
    capsys.readouterr()

    kb.mutate_raw("src", "# S\n\ncompletely different content now.\n")
    rc = cli.main(["search", "different content", "--json", "--root", str(kb.root)])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"method", "stale_index", "results"}
    assert data["method"] == "embeddings"
    assert data["stale_index"] is True  # fingerprint drifted from raw hashes

    # rebuilding the index clears the drift warning
    assert cli.main(["index", "--root", str(kb.root)]) == 0
    capsys.readouterr()
    assert cli.main(["search", "different content", "--json", "--root", str(kb.root)]) == 0
    assert json.loads(capsys.readouterr().out)["stale_index"] is False


def test_index_on_empty_vault_builds_empty_index(kb, capsys, monkeypatch):
    _with_toy_backend(monkeypatch)
    rc = cli.main(["index", "--json", "--root", str(kb.root)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["blocks_indexed"] == 0
    # an empty index is usable: search returns no results, not an error
    out = retrieval.search(kb.root, "anything", k=3)
    assert out["results"] == []

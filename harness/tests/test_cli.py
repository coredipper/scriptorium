"""cli.py tests: pure unit tests for the argument helpers, plus one end-to-end
dispatch test for the `graph` command that stubs only the model call and lets
argparse and the REAL `scrip` CLI run. Hermetic — no network, no LLM."""

from scrip_harness import cli, model
from scrip_harness.cli import _normalize_sources
from scrip_harness.graph import DraftEdge, DraftEntity, DraftGraph


def test_normalize_sources_strips_each_part_before_prefixing():
    # whitespace around a comma-separated part must be stripped BEFORE the raw/
    # prefix check, or " raw/b" wrongly becomes "raw/ raw/b"
    assert _normalize_sources("raw/a, raw/b") == ["raw/a", "raw/b"]


def test_normalize_sources_prefixes_bare_slugs():
    assert _normalize_sources("a, b") == ["raw/a", "raw/b"]
    assert _normalize_sources("raw/a,b") == ["raw/a", "raw/b"]


def test_normalize_sources_drops_empty_parts():
    # an all-empty value yields nothing — the CLI treats that as a usage error
    assert _normalize_sources(",") == []
    assert _normalize_sources("") == []
    assert _normalize_sources(" , raw/a , ") == ["raw/a"]


def test_graph_command_drafts_entities_and_edges(tmp_path, monkeypatch, capsys):
    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")
    (tmp_path / "vault" / "raw" / "topic.md").write_text("# T\n\nText.\n", encoding="utf-8")

    def fake_draft_graph(text, *, source_id, **kw):
        return DraftGraph(
            entities=[
                DraftEntity(name="PageIndex", kind="tool"),
                DraftEntity(name="Vector DB", kind="tool"),
            ],
            edges=[DraftEdge(src="PageIndex", dst="Vector DB", kind="alternative-to")],
        )

    monkeypatch.setattr(model, "draft_graph", fake_draft_graph)

    rc = cli.main(["graph", "topic", "--root", str(tmp_path)])

    assert rc == 0
    assert "drafted 2 entities and 1 edge(s)" in capsys.readouterr().out
    ents = (tmp_path / "vault" / "facts" / "entities.ndjson").read_text(encoding="utf-8")
    assert "entity/pageindex" in ents and "entity/vector-db" in ents
    edges = (tmp_path / "vault" / "facts" / "graph.ndjson").read_text(encoding="utf-8")
    assert '"kind": "alternative-to"' in edges

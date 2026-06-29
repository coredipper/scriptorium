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


def test_extract_command_multi_source_attributes_each_claim(tmp_path, monkeypatch, capsys):
    from scrip_harness.extract import DraftExtraction, DraftFact

    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")
    (tmp_path / "vault" / "raw" / "a.md").write_text(
        "# A\n\nAlpha is documented only in source A.\n", encoding="utf-8"
    )
    (tmp_path / "vault" / "raw" / "b.md").write_text(
        "# B\n\nBeta is documented only in source B.\n", encoding="utf-8"
    )

    def fake_draft_extraction(text, *, source_id, failures=None, **kw):
        # --from passes both sources to the model, labelled for attribution
        assert source_id == "raw/a,raw/b"
        assert "----- SOURCE raw/a -----" in text
        return DraftExtraction(
            claims=[
                DraftFact(
                    quote="Alpha is documented only in source A.",
                    subject="alpha", predicate="in", object="a", source_id="raw/a",
                ),
                DraftFact(
                    quote="Beta is documented only in source B.",
                    subject="beta", predicate="in", object="b", source_id="raw/b",
                ),
            ]
        )

    monkeypatch.setattr(model, "draft_extraction", fake_draft_extraction)

    rc = cli.main(["extract", "a", "--from", "raw/a,raw/b", "--root", str(tmp_path)])

    assert rc == 0
    assert "extracted 2 claim(s) from raw/a,raw/b" in capsys.readouterr().out
    recs = (tmp_path / "vault" / "facts" / "claims.ndjson").read_text(encoding="utf-8")
    assert '"source_id": "raw/a"' in recs and '"source_id": "raw/b"' in recs

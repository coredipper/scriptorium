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


def test_promote_resynthesize_command_redrafts_target(tmp_path, monkeypatch, capsys):
    from scrip_harness.compile import DraftClaim, DraftPage

    from scrip import anchors, frontmatter

    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")
    (tmp_path / "vault" / "raw" / "alpha.md").write_text(
        "# A\n\nAlpha one sentence.\n", encoding="utf-8"
    )
    (tmp_path / "vault" / "raw" / "beta.md").write_text(
        "# B\n\nBeta one sentence.\n", encoding="utf-8"
    )

    def _page(slug, quote, ssl):
        src = (tmp_path / "vault" / "raw" / f"{ssl}.md").read_text(encoding="utf-8")
        anchor = anchors.make_anchor(src, quote)
        body = f'Point.[^a1]\n\n[^a1]: anchor=raw/{ssl}#{anchor}  "{quote[:20]}"\n'
        meta = {"id": f"concept/{slug}", "type": "wiki.concept", "title": "Compilation",
                "derived-from": ["raw/alpha", "raw/beta"], "confidence": 0.8}
        (tmp_path / "vault" / "wiki" / "concepts" / f"{slug}.md").write_text(
            frontmatter.dump(meta, body), encoding="utf-8"
        )

    _page("compilation", "Alpha one sentence.", "alpha")
    _page("compilation-redux", "Beta one sentence.", "beta")

    def fake_draft_page(text, *, source_id, failures=None, **kw):
        assert source_id == "raw/alpha,raw/beta"  # re-drafts over the union
        return DraftPage(
            title="ignored",
            body="Coherent re-synthesis of alpha[^a1] and beta[^a2].\n",
            claims=[
                DraftClaim(quote="Alpha one sentence.", source_id="raw/alpha"),
                DraftClaim(quote="Beta one sentence.", source_id="raw/beta"),
            ],
        )

    monkeypatch.setattr(model, "draft_page", fake_draft_page)

    rc = cli.main(["promote", "compilation-redux", "--resynthesize", "--root", str(tmp_path)])

    assert rc == 0
    assert "resynthesized concept/compilation-redux into concept/compilation" in capsys.readouterr().out
    body = (tmp_path / "vault" / "wiki" / "concepts" / "compilation.md").read_text(encoding="utf-8")
    assert "Coherent re-synthesis of alpha" in body  # body re-drafted, not appended


def _ingest_vault(tmp_path):
    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")


def test_ingest_command_through_ingest_only(tmp_path, capsys):
    # the default-orchestration dispatch with no model: just `scrip ingest`.
    _ingest_vault(tmp_path)
    src = tmp_path / "topic.md"
    src.write_text("# Topic\n\nA body sentence.\n", encoding="utf-8")

    rc = cli.main(["ingest", str(src), "--through", "ingest", "--root", str(tmp_path)])

    assert rc == 0
    assert (tmp_path / "vault" / "raw" / "topic.md").exists()
    assert "ingest" in capsys.readouterr().out.lower()


def test_ingest_command_clean_routes_to_model_clean_source(tmp_path, monkeypatch, capsys):
    _ingest_vault(tmp_path)
    src = tmp_path / "topic.md"
    src.write_text("Nav | Menu\n\nThe kept sentence.\n", encoding="utf-8")

    def fake_clean(text, **kw):
        assert "kept sentence" in text  # the extracted source text is handed to the model
        return "# Topic\n\nThe kept sentence.\n"

    monkeypatch.setattr(model, "clean_source", fake_clean)

    rc = cli.main(["ingest", str(src), "--clean", "--through", "ingest", "--root", str(tmp_path)])

    assert rc == 0
    raw = (tmp_path / "vault" / "raw" / "topic.md").read_text(encoding="utf-8")
    assert "# Topic" in raw and "Nav | Menu" not in raw  # cleaned text replaced the raw
    capsys.readouterr()


def test_ingest_command_full_pipeline_drives_compile_extract_graph(tmp_path, monkeypatch, capsys):
    from scrip_harness.compile import DraftClaim, DraftPage
    from scrip_harness.extract import DraftExtraction, DraftFact
    from scrip_harness.graph import DraftEdge, DraftEntity, DraftGraph

    _ingest_vault(tmp_path)
    src = tmp_path / "topic.md"
    src.write_text(
        "# Topic\n\nPageIndex is a retrieval tool. It is an alternative to a vector DB.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(model, "draft_page", lambda text, *, source_id, failures=None, **kw: DraftPage(
        title="Topic",
        body="PageIndex is a retrieval tool.[^a1]\n",
        claims=[DraftClaim(quote="PageIndex is a retrieval tool.")],
    ))
    monkeypatch.setattr(model, "draft_extraction", lambda text, *, source_id, failures=None, **kw: DraftExtraction(
        claims=[DraftFact(quote="It is an alternative to a vector DB.",
                          subject="pageindex", predicate="alternative-to", object="vector-db")],
    ))
    monkeypatch.setattr(model, "draft_graph", lambda text, *, source_id, **kw: DraftGraph(
        entities=[DraftEntity(name="PageIndex", kind="tool"), DraftEntity(name="Vector DB", kind="tool")],
        edges=[DraftEdge(src="PageIndex", dst="Vector DB", kind="alternative-to")],
    ))

    rc = cli.main(["ingest", str(src), "--root", str(tmp_path)])  # default --through graph

    assert rc == 0
    assert (tmp_path / "vault" / "wiki" / "concepts" / "topic.md").exists()
    assert (tmp_path / "vault" / "facts" / "claims.ndjson").exists()
    assert "entity/pageindex" in (tmp_path / "vault" / "facts" / "entities.ndjson").read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "compile" in out and "extract" in out and "graph" in out

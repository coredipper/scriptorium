"""GRAPH integration tests: stub the model, drive the REAL `scrip` CLI over a
temp vault, and assert entities + edges land and the vault stays green. Edges
carry no anchors (structural, not cited), so there is no quote-retry loop; the
harness's own guard drops edges whose endpoints are not real entities. Hermetic
— no network, no LLM."""

import json
import subprocess

import pytest
from scrip_harness.graph import (
    DraftEdge,
    DraftEntity,
    DraftGraph,
    edges_to_ndjson,
    entities_to_ndjson,
    entity_id,
    slug,
)
from scrip_harness.runner import GraphError, draft_graph_facts


def _vault(tmp_path):
    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")
    return tmp_path


def _rows(root, name):
    p = root / "vault" / "facts" / name
    if not p.exists():
        return []
    return [json.loads(s) for s in p.read_text(encoding="utf-8").splitlines() if s.strip()]


# --------------------------------------------------------------------------- #
# Deterministic helpers (no scrip, no model)
# --------------------------------------------------------------------------- #
def test_slug_derives_scrip_valid_entity_ids():
    assert slug("Retrieval Augmented Generation") == "retrieval-augmented-generation"
    assert slug("  PageIndex  ") == "pageindex"
    assert slug("AI/ML") == "ai-ml"
    assert entity_id("Vector DB") == "entity/vector-db"
    # nothing usable -> empty (the runner treats this as "skip")
    assert slug("!!!") == ""
    assert entity_id("***") == ""


def test_entities_to_ndjson_mints_ids_and_omits_empty_tags():
    out = entities_to_ndjson(
        [
            DraftEntity(name="PageIndex", kind="tool", tags=["retrieval"]),
            DraftEntity(name="Vector DB", kind="tool"),
        ]
    )
    rows = [json.loads(s) for s in out.splitlines()]
    assert rows[0] == {"entity_id": "entity/pageindex", "name": "PageIndex", "kind": "tool", "tags": ["retrieval"]}
    assert rows[1] == {"entity_id": "entity/vector-db", "name": "Vector DB", "kind": "tool"}
    # scrip owns nothing here, but edges/entities never carry anchors/timestamps
    assert all("anchor" not in r for r in rows)


def test_edges_to_ndjson_maps_names_to_ids():
    name_to_id = {"PageIndex": "entity/pageindex", "Vector DB": "entity/vector-db"}
    out = edges_to_ndjson(
        [DraftEdge(src="PageIndex", dst="Vector DB", kind="alternative-to")], name_to_id
    )
    [row] = [json.loads(s) for s in out.splitlines()]
    # edges allow EXACTLY src/dst/kind (scrip rejects extra fields)
    assert row == {"src": "entity/pageindex", "dst": "entity/vector-db", "kind": "alternative-to"}


# --------------------------------------------------------------------------- #
# Happy path (real scrip)
# --------------------------------------------------------------------------- #
def test_graph_appends_entities_and_edges_and_stays_green(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# Retrieval\n\nPageIndex is a long-document retrieval tool. A vector DB "
        "stores embeddings.\n",
        encoding="utf-8",
    )

    def stub(source_text, *, source_id):
        return DraftGraph(
            entities=[
                DraftEntity(name="PageIndex", kind="tool"),
                DraftEntity(name="Vector DB", kind="tool"),
            ],
            edges=[DraftEdge(src="PageIndex", dst="Vector DB", kind="alternative-to")],
        )

    result = draft_graph_facts(root, "topic", draft_fn=stub)

    ents = _rows(root, "entities.ndjson")
    edges = _rows(root, "graph.ndjson")
    assert {e["entity_id"] for e in ents} == {"entity/pageindex", "entity/vector-db"}
    assert edges == [{"src": "entity/pageindex", "dst": "entity/vector-db", "kind": "alternative-to"}]
    assert len(result["entities"]["appended"]) == 2
    assert len(result["edges"]["appended"]) == 1
    assert result["dropped_edges"] == [] and result["skipped_entities"] == []

    status = subprocess.run(
        ["scrip", "status", "--root", str(root)], capture_output=True, text=True
    )
    assert status.returncode == 0, status.stdout + status.stderr


def test_graph_is_idempotent_via_duplicate_skip(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text("# T\n\nOne entity here.\n", encoding="utf-8")

    def stub(source_text, *, source_id):
        return DraftGraph(entities=[DraftEntity(name="Solo", kind="concept")], edges=[])

    draft_graph_facts(root, "topic", draft_fn=stub)
    result = draft_graph_facts(root, "topic", draft_fn=stub)  # re-run: nothing new
    assert result["entities"]["appended"] == []
    assert len(result["entities"]["skipped"]) == 1
    assert len(_rows(root, "entities.ndjson")) == 1


# --------------------------------------------------------------------------- #
# Guard rails
# --------------------------------------------------------------------------- #
def test_graph_drops_edges_with_unknown_endpoints(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text("# T\n\nText.\n", encoding="utf-8")

    def stub(source_text, *, source_id):
        return DraftGraph(
            entities=[DraftEntity(name="A", kind="concept"), DraftEntity(name="B", kind="concept")],
            edges=[
                DraftEdge(src="A", dst="B", kind="relates-to"),
                DraftEdge(src="A", dst="Ghost", kind="relates-to"),  # Ghost is not an entity
            ],
        )

    result = draft_graph_facts(root, "topic", draft_fn=stub)
    assert len(result["edges"]["appended"]) == 1
    assert result["dropped_edges"] == [{"src": "A", "dst": "Ghost", "kind": "relates-to"}]
    assert _rows(root, "graph.ndjson") == [
        {"src": "entity/a", "dst": "entity/b", "kind": "relates-to"}
    ]


def test_graph_edges_may_reference_existing_entities(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text("# T\n\nText.\n", encoding="utf-8")
    # seed an existing entity from a prior run
    (root / "vault" / "facts" / "entities.ndjson").write_text(
        json.dumps({"entity_id": "entity/prior", "name": "Prior", "kind": "concept"}) + "\n",
        encoding="utf-8",
    )

    def stub(source_text, *, source_id):
        return DraftGraph(
            entities=[DraftEntity(name="Fresh", kind="concept")],
            edges=[DraftEdge(src="Fresh", dst="Prior", kind="builds-on")],
        )

    result = draft_graph_facts(root, "topic", draft_fn=stub)
    assert result["dropped_edges"] == []
    assert _rows(root, "graph.ndjson") == [
        {"src": "entity/fresh", "dst": "entity/prior", "kind": "builds-on"}
    ]


def test_graph_skips_unsluggable_entities_and_their_edges(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text("# T\n\nText.\n", encoding="utf-8")

    def stub(source_text, *, source_id):
        return DraftGraph(
            entities=[DraftEntity(name="Good", kind="concept"), DraftEntity(name="???", kind="concept")],
            edges=[DraftEdge(src="Good", dst="???", kind="relates-to")],
        )

    result = draft_graph_facts(root, "topic", draft_fn=stub)
    assert result["skipped_entities"] == ["???"]
    assert {e["entity_id"] for e in _rows(root, "entities.ndjson")} == {"entity/good"}
    assert _rows(root, "graph.ndjson") == []  # the edge referenced a skipped entity


def test_graph_rejects_unsafe_slug(tmp_path):
    root = _vault(tmp_path)
    called = False

    def stub(source_text, *, source_id):
        nonlocal called
        called = True
        return DraftGraph(entities=[], edges=[])

    with pytest.raises(GraphError):
        draft_graph_facts(root, "../../etc/passwd", draft_fn=stub)
    assert called is False


def test_graph_missing_source_is_a_clean_error(tmp_path):
    root = _vault(tmp_path)

    def stub(source_text, *, source_id):
        raise AssertionError("must not be called for a missing source")

    with pytest.raises(GraphError, match="raw/absent"):
        draft_graph_facts(root, "absent", draft_fn=stub)


def test_graph_empty_draft_is_a_clean_error(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text("# T\n\nText.\n", encoding="utf-8")

    def stub(source_text, *, source_id):
        return DraftGraph(entities=[], edges=[])

    with pytest.raises(GraphError, match="no entities or edges"):
        draft_graph_facts(root, "topic", draft_fn=stub)

"""ANSWER: the model drafts from bounded evidence; scrip verifies every citation.
Hermetic — no network, no LLM; the draft function is stubbed and scrip runs for
real over a temp vault."""

import json
import subprocess
import sys

import pytest
from scrip_harness.answer import (
    AnswerCitation,
    DraftAnswer,
    build_answer_prompt,
    overlap_score,
)
from scrip_harness.runner import AnswerError, _read_ndjson, answer_question

from scrip import anchors, frontmatter, hashing


def _vault(tmp_path):
    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")
    return tmp_path


def _raw(root, slug, text):
    (root / "vault" / "raw" / f"{slug}.md").write_text(text, encoding="utf-8")


def _claim(root, claim_id, slug, quote, *, subject="caching", predicate="helps"):
    src = (root / "vault" / "raw" / f"{slug}.md").read_text(encoding="utf-8")
    rec = {
        "claim_id": claim_id,
        "source_id": f"raw/{slug}",
        "anchor": anchors.make_anchor(src, quote),
        "claim_text": quote,
        "subject": subject,
        "predicate": predicate,
        "object": "answers",
        "polarity": "asserts",
        "confidence": 0.9,
        "tags": ["caching"],
    }
    with open(root / "vault" / "facts" / "claims.ndjson", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _verify(root):
    return subprocess.run(
        [sys.executable, "-m", "scrip.cli", "verify", "--root", str(root)],
        capture_output=True,
        text=True,
    )


def test_build_answer_prompt_includes_evidence_packet():
    evidence = {"claims": [{"ref": "clm_0001", "text": "Cached answer."}]}
    prompt = build_answer_prompt("Why cache?", evidence)
    assert "Why cache?" in prompt
    assert "clm_0001" in prompt


def test_overlap_score_counts_question_terms():
    assert overlap_score("cached answers", "Answers are cached by default") == 2


def test_graph_context_ndjson_reader_preserves_unicode_line_separator(tmp_path):
    path = tmp_path / "entities.ndjson"
    path.write_text(
        json.dumps({"entity_id": "entity/a", "name": "Alpha\u2028Beta"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    assert _read_ndjson(path, "entities.ndjson")[0]["name"] == "Alpha\u2028Beta"


def test_answer_uses_verified_claim_and_raw_citations(tmp_path):
    root = _vault(tmp_path)
    _raw(
        root,
        "topic",
        "# Topic\n\nCached answers avoid recomputing work.\n\n"
        "Raw retrieval is only needed when compiled evidence is thin.\n",
    )
    _claim(root, "clm_0001", "topic", "Cached answers avoid recomputing work.")
    seen = {}

    def stub(question, *, evidence):
        seen["evidence"] = evidence
        assert evidence["claims"][0]["ref"] == "clm_0001"
        assert evidence["raw_blocks"]  # min_compiled below forces search fallback too
        return DraftAnswer(
            body=(
                "The corpus says caching avoids repeated work.[^a1]\n\n"
                "It uses raw retrieval when compiled evidence is thin.[^a2]"
            ),
            citations=[
                AnswerCitation(marker="a1", kind="claim", claim_id="clm_0001"),
                AnswerCitation(
                    marker="a2",
                    kind="raw",
                    source_id="raw/topic",
                    quote="Raw retrieval is only needed when compiled evidence is thin.",
                ),
            ],
        )

    result = answer_question(root, "How do cached answers use retrieval?", draft_fn=stub,
                             min_compiled=99)
    answer = result["answer"]
    assert "claim=clm_0001" in answer
    assert "[^a2]: anchor=raw/topic#qh:" in answer
    assert result["saved"] is None
    assert seen["evidence"]["policy"]["wiki_pages"] == "context only; do not cite directly"


def test_answer_save_writes_verified_exploration(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "topic", "# Topic\n\nCached answers avoid recomputing work.\n")
    _claim(root, "clm_0001", "topic", "Cached answers avoid recomputing work.")

    def stub(question, *, evidence):
        return DraftAnswer(
            body="Caching avoids recomputation.[^a1]",
            citations=[AnswerCitation(marker="a1", kind="claim", claim_id="clm_0001")],
        )

    result = answer_question(root, "Why cache answers?", draft_fn=stub, save=True)
    assert result["saved"].startswith("vault/wiki/explorations/why-cache-answers")
    saved = root / result["saved"]
    assert saved.exists()
    assert "query: " in saved.read_text(encoding="utf-8")
    assert _verify(root).returncode == 0


def test_answer_reads_relevant_wiki_pages_as_context(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "topic", "# Topic\n\nCompiled knowledge compounds over time.\n")
    _claim(root, "clm_0001", "topic", "Compiled knowledge compounds over time.",
           subject="compiled knowledge")
    body = "Compiled knowledge is useful context.[^a1]\n"
    meta = {
        "id": "concept/compiled-knowledge",
        "type": "wiki.concept",
        "title": "Compiled knowledge",
        "derived-from": ["raw/topic"],
        "input-hash": hashing.input_hash({
            "raw/topic": hashing.sha256_bytes(
                (root / "vault" / "raw" / "topic.md").read_bytes()
            )
        }),
        "last-compiled": "2026-01-01T00:00:00Z",
        "confidence": 0.9,
    }
    page = root / "vault" / "wiki" / "concepts" / "compiled-knowledge.md"
    page.write_text(frontmatter.dump(meta, body), encoding="utf-8")

    def stub(question, *, evidence):
        assert evidence["wiki_pages"][0]["id"] == "concept/compiled-knowledge"
        return DraftAnswer(
            body="Compiled knowledge compounds.[^a1]",
            citations=[AnswerCitation(marker="a1", kind="claim", claim_id="clm_0001")],
        )

    answer_question(root, "What about compiled knowledge?", draft_fn=stub)


def test_answer_includes_relevant_graph_context_but_does_not_cite_it(tmp_path):
    root = _vault(tmp_path)
    _raw(
        root,
        "topic",
        "# Topic\n\nPageIndex is an alternative to a vector DB.\n",
    )
    _claim(
        root,
        "clm_0001",
        "topic",
        "PageIndex is an alternative to a vector DB.",
        subject="pageindex",
        predicate="alternative-to",
    )
    (root / "vault" / "facts" / "entities.ndjson").write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "entity_id": "entity/pageindex",
                    "name": "PageIndex",
                    "kind": "tool",
                    "tags": ["retrieval"],
                    "uri": "https://example.test/pageindex",
                    "same_as": ["https://example.test/page-index"],
                    "external_ids": {"wikidata": "Q123"},
                },
                {
                    "entity_id": "entity/vector-db",
                    "name": "Vector DB",
                    "kind": "tool",
                    "tags": ["retrieval"],
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "vault" / "facts" / "graph.ndjson").write_text(
        json.dumps(
            {
                "src": "entity/pageindex",
                "dst": "entity/vector-db",
                "kind": "alternative-to",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def stub(question, *, evidence):
        graph_context = evidence["graph_context"]
        by_id = {entity["entity_id"]: entity for entity in graph_context["entities"]}
        assert evidence["policy"]["graph_context"] == "context only; do not cite directly"
        assert by_id["entity/pageindex"]["uri"] == "https://example.test/pageindex"
        assert by_id["entity/pageindex"]["external_ids"] == {"wikidata": "Q123"}
        assert graph_context["edges"][0]["kind"] == "alternative-to"
        assert graph_context["edges"][0]["src_name"] == "PageIndex"
        return DraftAnswer(
            body="PageIndex is framed as an alternative to vector databases.[^a1]",
            citations=[AnswerCitation(marker="a1", kind="claim", claim_id="clm_0001")],
        )

    result = answer_question(root, "How does PageIndex relate to vector databases?", draft_fn=stub)

    assert "claim=clm_0001" in result["answer"]


def test_answer_falls_back_to_raw_when_only_wiki_context_matches(tmp_path):
    root = _vault(tmp_path)
    raw_text = "# Topic\n\nCompiled knowledge compounds over time.\n"
    _raw(root, "topic", raw_text)
    ih = hashing.input_hash({"raw/topic": hashing.sha256_bytes(raw_text.encode("utf-8"))})
    for i in range(4):
        meta = {
            "id": f"concept/context-{i}",
            "type": "wiki.concept",
            "title": "Compiled knowledge",
            "derived-from": ["raw/topic"],
            "input-hash": ih,
            "last-compiled": "2026-01-01T00:00:00Z",
            "confidence": 0.9,
        }
        page = root / "vault" / "wiki" / "concepts" / f"context-{i}.md"
        page.write_text(
            frontmatter.dump(meta, "Compiled knowledge is useful context.\n"),
            encoding="utf-8",
        )

    def stub(question, *, evidence):
        assert len(evidence["wiki_pages"]) == 4  # context found
        assert evidence["claims"] == []  # but no citable compiled facts
        assert evidence["raw_blocks"]  # so raw search still runs
        return DraftAnswer(
            body="Compiled knowledge compounds over time.[^a1]",
            citations=[
                AnswerCitation(
                    marker="a1",
                    kind="raw",
                    source_id="raw/topic",
                    quote="Compiled knowledge compounds over time.",
                )
            ],
        )

    result = answer_question(root, "compiled knowledge", draft_fn=stub, k=4)
    assert "[^a1]: anchor=raw/topic#qh:" in result["answer"]


def test_answer_refuses_stale_artifacts_before_model_call(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "topic", "# Topic\n\nCached answers avoid recomputing work.\n")
    _claim(root, "clm_0001", "topic", "Cached answers avoid recomputing work.")
    page = root / "vault" / "wiki" / "concepts" / "stale.md"
    page.write_text(
        frontmatter.dump(
            {
                "id": "concept/stale",
                "type": "wiki.concept",
                "title": "Stale",
                "derived-from": ["raw/topic"],
                "input-hash": "sha256:not-current",
                "last-compiled": "2026-01-01T00:00:00Z",
                "confidence": 0.8,
            },
            "Body.\n",
        ),
        encoding="utf-8",
    )
    called = False

    def stub(question, *, evidence):
        nonlocal called
        called = True
        return DraftAnswer(body="x", citations=[])

    with pytest.raises(AnswerError, match="stale"):
        answer_question(root, "Why cache?", draft_fn=stub)
    assert called is False


def test_answer_refuses_broken_vault_before_model_call(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "topic", "# Topic\n\nCached answers avoid recomputing work.\n")
    with open(root / "vault" / "facts" / "claims.ndjson", "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "claim_id": "clm_0001",
            "source_id": "raw/topic",
            "anchor": "qh:deadbeef|loc:0.0|len:10",
            "claim_text": "Broken",
            "subject": "s",
            "predicate": "p",
            "object": "o",
            "polarity": "asserts",
            "confidence": 0.9,
            "tags": [],
        }) + "\n")
    called = False

    def stub(question, *, evidence):
        nonlocal called
        called = True
        return DraftAnswer(body="x", citations=[])

    with pytest.raises(AnswerError, match="unresolved citations"):
        answer_question(root, "Why cache?", draft_fn=stub)
    assert called is False


def test_answer_refuses_open_contradictions(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "a", "# A\n\nChunking helps retrieval.\n")
    _raw(root, "b", "# B\n\nChunking does not help retrieval.\n")
    _claim(root, "clm_0001", "a", "Chunking helps retrieval.",
           subject="chunking", predicate="helps")
    _claim(root, "clm_0002", "b", "Chunking does not help retrieval.",
           subject="chunking", predicate="helps")
    # flip polarity on second claim by rewriting the tiny facts file
    rows = [
        json.loads(s)
        for s in (root / "vault" / "facts" / "claims.ndjson").read_text().splitlines()
    ]
    rows[1]["polarity"] = "denies"
    (root / "vault" / "facts" / "claims.ndjson").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )

    def stub(question, *, evidence):
        return DraftAnswer(body="x", citations=[])

    with pytest.raises(AnswerError, match="open contradiction"):
        answer_question(root, "Does chunking help?", draft_fn=stub)


def test_answer_rejects_unknown_claim_citation(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "topic", "# Topic\n\nCached answers avoid recomputing work.\n")
    _claim(root, "clm_0001", "topic", "Cached answers avoid recomputing work.")

    def stub(question, *, evidence):
        return DraftAnswer(
            body="Caching helps.[^a1]",
            citations=[AnswerCitation(marker="a1", kind="claim", claim_id="clm_9999")],
        )

    with pytest.raises(AnswerError, match="ungathered claim"):
        answer_question(root, "Why cache?", draft_fn=stub)


def test_answer_rejects_non_verbatim_raw_quote(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "topic", "# Topic\n\nCached answers avoid recomputing work.\n")
    # no claims/page context: raw search becomes the evidence layer

    def stub(question, *, evidence):
        return DraftAnswer(
            body="Caching helps.[^a1]",
            citations=[
                AnswerCitation(
                    marker="a1",
                    kind="raw",
                    source_id="raw/topic",
                    quote="This quote is not in the source.",
                )
            ],
        )

    with pytest.raises(AnswerError, match="did not resolve"):
        answer_question(root, "cached answers", draft_fn=stub)


def test_answer_rejects_marker_mismatch(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "topic", "# Topic\n\nCached answers avoid recomputing work.\n")
    _claim(root, "clm_0001", "topic", "Cached answers avoid recomputing work.")

    def stub(question, *, evidence):
        return DraftAnswer(
            body="Caching helps.[^a2]",
            citations=[AnswerCitation(marker="a1", kind="claim", claim_id="clm_0001")],
        )

    with pytest.raises(AnswerError, match="must be exactly"):
        answer_question(root, "Why cache?", draft_fn=stub)


def test_answer_citation_accepts_markdown_marker_wrapper():
    citation = AnswerCitation(marker="[^a1]", kind="claim", claim_id="clm_0001")

    assert citation.marker == "a1"

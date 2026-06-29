"""EXTRACT integration tests: stub the model, drive the REAL `scrip` CLI over a
temp vault, and assert claims land verified + the facts set is stamped. The
retry loop is exercised with a stateful stub that fixes its quote when asked.
Hermetic — no network, no LLM."""

import json
import subprocess

import pytest
from scrip_harness.extract import DraftExtraction, DraftFact, to_ndjson
from scrip_harness.runner import ExtractError, extract_facts


def _vault(tmp_path):
    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")
    return tmp_path


def _fact(quote, **kw):
    kw.setdefault("subject", "s")
    kw.setdefault("predicate", "p")
    kw.setdefault("object", "o")
    return DraftFact(quote=quote, **kw)


def _claims_lines(root):
    p = root / "vault" / "facts" / "claims.ndjson"
    if not p.exists():
        return []
    return [json.loads(s) for s in p.read_text(encoding="utf-8").splitlines() if s.strip()]


# --------------------------------------------------------------------------- #
# Deterministic serializer (no scrip, no model)
# --------------------------------------------------------------------------- #
def test_to_ndjson_serializes_proposals_for_scrip():
    facts = [
        _fact("a verbatim quote", claim_text="A restatement.", tags=["t1"]),
        _fact("another quote"),  # empty claim_text/tags are omitted: scrip defaults them
    ]
    lines = [json.loads(s) for s in to_ndjson(facts, "raw/src").splitlines()]
    assert lines[0]["source_id"] == "raw/src"
    assert lines[0]["claim_text"] == "A restatement."
    assert lines[0]["tags"] == ["t1"]
    assert lines[0]["polarity"] == "asserts"
    assert "claim_text" not in lines[1]
    assert "tags" not in lines[1]
    # scrip owns these — proposals must never carry them
    for line in lines:
        assert "anchor" not in line and "claim_id" not in line and "extracted_at" not in line


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_extract_appends_verified_claims_and_stamps_meta(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# Topic\n\nCompiled knowledge compounds over time.\n\n"
        "Provenance is checkable by content, not by line number.\n",
        encoding="utf-8",
    )

    def stub(source_text, *, source_id, failures=None):
        assert failures is None
        return DraftExtraction(
            claims=[
                _fact("Compiled knowledge compounds over time."),
                _fact("Provenance is checkable by content", subject="provenance"),
            ]
        )

    result = extract_facts(root, "topic", draft_fn=stub)
    recs = _claims_lines(root)
    assert [r["claim_id"] for r in recs] == ["clm_0001", "clm_0002"]
    assert len(result["appended"]) == 2
    assert result["contradictions"] == []

    # the facts set was stamped after the merge — the vault is left green
    meta = (root / "vault" / "facts" / "_meta.yaml").read_text(encoding="utf-8")
    assert "input-hash: sha256:" in meta
    assert "raw/topic" in meta
    status = subprocess.run(
        ["scrip", "status", "--root", str(root)], capture_output=True, text=True
    )
    assert status.returncode == 0, status.stdout + status.stderr


def test_extract_is_idempotent_via_duplicate_skip(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# T\n\nA single extractable sentence.\n", encoding="utf-8"
    )

    def stub(source_text, *, source_id, failures=None):
        return DraftExtraction(claims=[_fact("A single extractable sentence.")])

    extract_facts(root, "topic", draft_fn=stub)
    result = extract_facts(root, "topic", draft_fn=stub)  # re-run: nothing new
    assert result["appended"] == []
    assert len(result["skipped"]) == 1
    assert len(_claims_lines(root)) == 1


# --------------------------------------------------------------------------- #
# The quote-retry loop
# --------------------------------------------------------------------------- #
def test_extract_retries_failed_quotes_with_lengthened_ones(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "alpha beta. alpha beta. gamma delta unique sentence.\n", encoding="utf-8"
    )
    calls = []

    def stub(source_text, *, source_id, failures=None):
        calls.append(failures)
        if failures is None:
            return DraftExtraction(
                claims=[
                    _fact("gamma delta unique sentence."),
                    _fact("alpha beta.", subject="s2"),  # AMBIGUOUS: appears twice
                ]
            )
        # asked to fix exactly the failing quote — return it lengthened, in order
        assert [f["status"] for f in failures] == ["AMBIGUOUS"]
        return DraftExtraction(claims=[_fact("alpha beta. alpha beta.", subject="s2")])

    result = extract_facts(root, "topic", draft_fn=stub)
    assert len(calls) == 2  # one draft + one targeted retry
    assert len(result["appended"]) == 2
    assert len(_claims_lines(root)) == 2


def test_extract_fails_cleanly_after_retry_exhaustion(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# T\n\nThe only real text.\n", encoding="utf-8"
    )
    calls = []

    def stub(source_text, *, source_id, failures=None):
        calls.append(failures)
        return DraftExtraction(claims=[_fact("a quote that is never in the source")])

    with pytest.raises(ExtractError):
        extract_facts(root, "topic", draft_fn=stub, max_quote_retries=2)
    assert len(calls) == 3  # initial draft + 2 bounded retries
    assert _claims_lines(root) == []  # all-or-nothing held throughout


def test_extract_retry_can_drop_an_unfixable_claim(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# T\n\nOne good extractable sentence.\n", encoding="utf-8"
    )

    def stub(source_text, *, source_id, failures=None):
        if failures is None:
            return DraftExtraction(
                claims=[
                    _fact("One good extractable sentence."),
                    _fact("hallucinated text", subject="s2"),
                ]
            )
        # an empty replacement quote means: drop this claim
        return DraftExtraction(claims=[_fact("", subject="s2")])

    result = extract_facts(root, "topic", draft_fn=stub)
    assert len(result["appended"]) == 1
    assert _claims_lines(root)[0]["claim_text"] == "One good extractable sentence."


# --------------------------------------------------------------------------- #
# Guard rails
# --------------------------------------------------------------------------- #
def test_extract_rejects_unsafe_slug(tmp_path):
    root = _vault(tmp_path)
    called = False

    def stub(source_text, *, source_id, failures=None):
        nonlocal called
        called = True
        return DraftExtraction(claims=[])

    with pytest.raises(ExtractError):
        extract_facts(root, "../../etc/passwd", draft_fn=stub)
    assert called is False


def test_extract_missing_source_is_a_clean_error(tmp_path):
    root = _vault(tmp_path)
    called = False

    def stub(source_text, *, source_id, failures=None):
        nonlocal called
        called = True
        return DraftExtraction(claims=[])

    with pytest.raises(ExtractError, match="raw/absent"):
        extract_facts(root, "absent", draft_fn=stub)
    assert called is False  # no model call for a source that does not exist


def test_to_ndjson_uses_per_claim_source_over_default():
    facts = [
        _fact("from a", source_id="raw/a"),
        _fact("from default"),  # empty source_id falls back to the default
    ]
    lines = [json.loads(s) for s in to_ndjson(facts, "raw/default").splitlines()]
    assert lines[0]["source_id"] == "raw/a"
    assert lines[1]["source_id"] == "raw/default"


# --------------------------------------------------------------------------- #
# Multi-source extract
# --------------------------------------------------------------------------- #
def test_extract_multi_source_attributes_each_claim_to_its_source(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "a.md").write_text(
        "# A\n\nAlpha is documented only in source A.\n", encoding="utf-8"
    )
    (root / "vault" / "raw" / "b.md").write_text(
        "# B\n\nBeta is documented only in source B.\n", encoding="utf-8"
    )

    def stub(source_text, *, source_id, failures=None):
        # multi-source: the draft id names both, and the formatted text labels them
        assert source_id == "raw/a,raw/b"
        assert "----- SOURCE raw/a -----" in source_text
        return DraftExtraction(
            claims=[
                _fact("Alpha is documented only in source A.", source_id="raw/a"),
                _fact("Beta is documented only in source B.", subject="beta", source_id="raw/b"),
            ]
        )

    result = extract_facts(root, "a", draft_fn=stub, sources=["raw/a", "raw/b"])
    recs = _claims_lines(root)
    assert {r["source_id"] for r in recs} == {"raw/a", "raw/b"}
    assert len(result["appended"]) == 2
    # anchors were minted against the RIGHT source (a B quote verified vs raw/a
    # would be BROKEN) — the vault verifies clean
    verify = subprocess.run(
        ["scrip", "verify", "--root", str(root)], capture_output=True, text=True
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr


def test_extract_multi_source_requires_a_source_id_per_claim(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "a.md").write_text("# A\n\nAlpha here.\n", encoding="utf-8")
    (root / "vault" / "raw" / "b.md").write_text("# B\n\nBeta here.\n", encoding="utf-8")

    def stub(source_text, *, source_id, failures=None):
        return DraftExtraction(claims=[_fact("Alpha here.")])  # no source_id given

    with pytest.raises(ExtractError, match="source"):
        extract_facts(root, "a", draft_fn=stub, sources=["raw/a", "raw/b"])
    assert _claims_lines(root) == []  # nothing written


def test_extract_multi_source_rejects_unknown_source_id(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "a.md").write_text("# A\n\nAlpha here.\n", encoding="utf-8")
    (root / "vault" / "raw" / "b.md").write_text("# B\n\nBeta here.\n", encoding="utf-8")

    def stub(source_text, *, source_id, failures=None):
        return DraftExtraction(claims=[_fact("Alpha here.", source_id="raw/ghost")])

    with pytest.raises(ExtractError, match="raw/ghost"):
        extract_facts(root, "a", draft_fn=stub, sources=["raw/a", "raw/b"])


def test_extract_surfaces_contradiction_candidates(tmp_path):
    from scrip import anchors  # the harness depends on scrip; reuse its anchor math

    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# T\n\nChunking discards document structure.\n", encoding="utf-8"
    )
    other_src = "# O\n\nChunking does not meaningfully hurt retrieval.\n"
    (root / "vault" / "raw" / "other.md").write_text(other_src, encoding="utf-8")
    seed = {
        "claim_id": "clm_0001",
        "subject": "chunking",
        "predicate": "discards",
        "object": "structure",
        "claim_text": "Chunking does not meaningfully hurt retrieval.",
        "source_id": "raw/other",
        "anchor": anchors.make_anchor(other_src, "Chunking does not meaningfully hurt retrieval."),
        "confidence": 0.8,
        "polarity": "denies",
        "extracted_at": "2026-01-01T00:00:00Z",
        "tags": [],
    }
    (root / "vault" / "facts" / "claims.ndjson").write_text(
        json.dumps(seed) + "\n", encoding="utf-8"
    )

    def stub(source_text, *, source_id, failures=None):
        return DraftExtraction(
            claims=[
                _fact(
                    "Chunking discards document structure.",
                    subject="chunking",
                    predicate="discards",
                    object="structure",
                )
            ]
        )

    result = extract_facts(root, "topic", draft_fn=stub)
    [pair] = result["contradictions"]
    assert {pair["source_a"], pair["source_b"]} == {"raw/topic", "raw/other"}

"""RECONCILE: the model decides each contradiction; scrip records it. Hermetic —
the decider is stubbed; scrip runs for real over a temp vault."""

import json
import subprocess
import sys

import pytest
from scrip_harness.reconcile import ReconciliationDecision, build_reconcile_prompt
from scrip_harness.runner import ReconcileError, reconcile_contradictions

from scrip import anchors


def _vault(tmp_path):
    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")
    return tmp_path


def _raw(root, slug, text):
    (root / "vault" / "raw" / f"{slug}.md").write_text(text, encoding="utf-8")


def _claim(root, claim_id, slug, quote, *, subject, predicate, polarity):
    src = (root / "vault" / "raw" / f"{slug}.md").read_text(encoding="utf-8")
    rec = {
        "claim_id": claim_id, "source_id": f"raw/{slug}",
        "anchor": anchors.make_anchor(src, quote), "claim_text": quote,
        "subject": subject, "predicate": predicate, "object": "o",
        "polarity": polarity, "confidence": 0.8, "tags": [],
    }
    with open(root / "vault" / "facts" / "claims.ndjson", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _contradiction(tmp_path):
    """A vault with one contradiction pair (clm_1 asserts, clm_2 denies)."""
    root = _vault(tmp_path)
    _raw(root, "a", "# A\n\nFixed-size chunking discards document structure.\n")
    _raw(root, "b", "# B\n\nChunking does not meaningfully harm retrieval.\n")
    _claim(root, "clm_0001", "a", "Fixed-size chunking discards document structure.",
           subject="chunking", predicate="discards", polarity="asserts")
    _claim(root, "clm_0002", "b", "Chunking does not meaningfully harm retrieval.",
           subject="chunking", predicate="discards", polarity="denies")
    (root / "vault" / "facts" / "_meta.yaml").write_text(
        "id: facts/core\ntype: facts.set\nderived-from:\n- raw/a\n- raw/b\n", encoding="utf-8"
    )
    return root


def _recs(root):
    p = root / "vault" / "facts" / "reconciliations.ndjson"
    return [json.loads(s) for s in p.read_text(encoding="utf-8").splitlines() if s.strip()] if p.exists() else []


def _contradictions(root):
    r = subprocess.run(
        [sys.executable, "-m", "scrip.cli", "query", "contradictions", "--json", "--root", str(root)],
        capture_output=True, text=True,
    )
    return json.loads(r.stdout)


# --------------------------------------------------------------------------- #
# Pure prompt
# --------------------------------------------------------------------------- #
def test_build_reconcile_prompt_includes_both_spans():
    pair = {"claim_a": "clm_0001", "claim_b": "clm_0002", "subject": "chunking",
            "predicate": "discards", "source_a": "raw/a", "source_b": "raw/b"}
    prompt = build_reconcile_prompt(pair, "chunking discards structure", "chunking does not harm")
    assert "chunking discards structure" in prompt
    assert "chunking does not harm" in prompt
    assert "raw/a" in prompt and "raw/b" in prompt


# --------------------------------------------------------------------------- #
# Integration (stubbed decider, real scrip)
# --------------------------------------------------------------------------- #
def test_reconcile_records_supersede_and_converges(tmp_path):
    root = _contradiction(tmp_path)
    seen = []

    def decide(pair, span_a, span_b):
        seen.append((span_a, span_b))
        return ReconciliationDecision(decision="supersede", winner="a", rationale="a is direct")

    result = reconcile_contradictions(root, decide_fn=decide)
    assert result["pairs"] == 1
    [rec] = _recs(root)
    assert rec["decision"] == "supersede"
    assert rec["winner"] == "clm_0001" and rec["claim_a"] == "clm_0001"
    assert rec["rationale"] == "a is direct"
    # the spans were actually read from the sources and handed to the decider
    assert any("chunking" in (s or "").lower() for s in seen[0])
    # contradiction is now adjudicated → no longer surfaced
    assert _contradictions(root) == []
    # vault left green
    assert subprocess.run([sys.executable, "-m", "scrip.cli", "verify", "--root", str(root)]).returncode == 0
    assert subprocess.run([sys.executable, "-m", "scrip.cli", "status", "--root", str(root)]).returncode == 0


def test_reconcile_keep_both(tmp_path):
    root = _contradiction(tmp_path)

    def decide(pair, span_a, span_b):
        return ReconciliationDecision(decision="keep-both", rationale="both contexts valid")

    reconcile_contradictions(root, decide_fn=decide)
    [rec] = _recs(root)
    assert rec["decision"] == "keep-both"
    assert "winner" not in rec


def test_reconcile_dry_run_records_nothing(tmp_path):
    root = _contradiction(tmp_path)

    def decide(pair, span_a, span_b):
        return ReconciliationDecision(decision="supersede", winner="b", rationale="x")

    result = reconcile_contradictions(root, decide_fn=decide, dry_run=True)
    assert result["dry_run"] is True and result["pairs"] == 1
    assert _recs(root) == []  # nothing written
    assert len(_contradictions(root)) == 1  # still flagged


def test_reconcile_no_contradictions_is_noop(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "a", "# A\n\nFixed-size chunking discards document structure.\n")
    _claim(root, "clm_0001", "a", "Fixed-size chunking discards document structure.",
           subject="chunking", predicate="discards", polarity="asserts")
    called = False

    def decide(pair, span_a, span_b):
        nonlocal called
        called = True
        return ReconciliationDecision(decision="keep-both")

    result = reconcile_contradictions(root, decide_fn=decide)
    assert result["pairs"] == 0  # a lone claim has nothing to contradict
    assert called is False  # no pairs → model never consulted


def test_reconcile_refuses_unresolved_span(tmp_path):
    """A claim whose anchor doesn't resolve must abort the reconcile BEFORE any
    decision/record — never adjudicate (and suppress) a contradiction on evidence
    that can't be read."""
    root = _vault(tmp_path)
    _raw(root, "a", "# A\n\nFixed-size chunking discards document structure.\n")
    _raw(root, "b", "# B\n\nChunking does not meaningfully harm retrieval.\n")
    _claim(root, "clm_0001", "a", "Fixed-size chunking discards document structure.",
           subject="chunking", predicate="discards", polarity="asserts")
    # clm_0002 carries a broken anchor (quote absent from source b)
    with open(root / "vault" / "facts" / "claims.ndjson", "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "claim_id": "clm_0002", "source_id": "raw/b",
            "anchor": anchors.make_anchor("an unrelated document", "unrelated"),
            "claim_text": "x", "subject": "chunking", "predicate": "discards",
            "object": "o", "polarity": "denies", "confidence": 0.8, "tags": [],
        }) + "\n")
    called = False

    def decide(pair, span_a, span_b):
        nonlocal called
        called = True
        return ReconciliationDecision(decision="keep-both")

    with pytest.raises(ReconcileError):
        reconcile_contradictions(root, decide_fn=decide)
    assert called is False  # never asked the model on unreadable evidence
    assert _recs(root) == []  # nothing recorded


def test_reconcile_supersede_without_winner_errors(tmp_path):
    root = _contradiction(tmp_path)

    def decide(pair, span_a, span_b):
        return ReconciliationDecision(decision="supersede", winner=None)

    with pytest.raises(ReconcileError):
        reconcile_contradictions(root, decide_fn=decide)
    assert _recs(root) == []  # nothing recorded on a bad decision

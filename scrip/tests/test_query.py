import pytest
from scrip.errors import UsageError

from scrip import cli, query


def test_named_claims_query(kb):
    kb.add_raw("a", "# A\n\nThe sky is blue.\n")
    kb.add_claim("clm_1", "a", "the sky is blue", subject="sky", tags=["color"])
    cols, rows = query.run(kb.root, name="claims")
    assert "subject" in cols
    assert any(r["claim_id"] == "clm_1" for r in rows)


def test_raw_sql_aggregate(kb):
    kb.add_raw("a", "# A\n\nThe sky is blue.\n")
    kb.add_claim("clm_1", "a", "the sky is blue")
    kb.add_claim("clm_2", "a", "the sky is blue")
    cols, rows = query.run(kb.root, sql="SELECT count(*) AS n FROM claims")
    assert rows[0]["n"] == 2


def test_contradictions_detected(kb):
    kb.add_raw("a", "# A\n\nThe sky is blue.\n")
    kb.add_raw("b", "# B\n\nThe sky is not blue.\n")
    kb.add_claim(
        "clm_1", "a", "the sky is blue", subject="sky", predicate="color",
        polarity="asserts",
    )
    kb.add_claim(
        "clm_2", "b", "the sky is not blue", subject="sky", predicate="color",
        polarity="denies",
    )
    cols, rows = query.run(kb.root, name="contradictions")
    assert len(rows) == 1
    assert rows[0]["subject"] == "sky"
    assert {rows[0]["source_a"], rows[0]["source_b"]} == {"raw/a", "raw/b"}


def _contradiction_pair(kb):
    kb.add_raw("a", "# A\n\nThe sky is blue.\n")
    kb.add_raw("b", "# B\n\nThe sky is not blue.\n")
    kb.add_claim("clm_1", "a", "the sky is blue", subject="sky", predicate="color", polarity="asserts")
    kb.add_claim("clm_2", "b", "the sky is not blue", subject="sky", predicate="color", polarity="denies")


def test_contradictions_excludes_reconciled_pairs(kb):
    _contradiction_pair(kb)
    assert len(query.run(kb.root, name="contradictions")[1]) == 1
    # record a reconciliation for that pair (reversed order, to test symmetry)
    (kb.root / "vault" / "facts" / "reconciliations.ndjson").write_text(
        '{"reconciliation_id":"rec_0001","decision":"supersede","claim_a":"clm_2",'
        '"claim_b":"clm_1","winner":"clm_2","at":"2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    assert query.run(kb.root, name="contradictions")[1] == []  # adjudicated → gone


def test_reconciliations_named_query(kb):
    _contradiction_pair(kb)
    (kb.root / "vault" / "facts" / "reconciliations.ndjson").write_text(
        '{"reconciliation_id":"rec_0001","decision":"keep-both","claim_a":"clm_1",'
        '"claim_b":"clm_2","at":"2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    cols, rows = query.run(kb.root, name="reconciliations")
    assert rows[0]["reconciliation_id"] == "rec_0001"
    assert rows[0]["decision"] == "keep-both"


def test_contradictions_works_without_reconciliations_file(kb):
    # the reconciliations view is an empty stub when the file is absent
    _contradiction_pair(kb)
    assert len(query.run(kb.root, name="contradictions")[1]) == 1


def test_contradictions_works_with_empty_reconciliations_file(kb):
    # an existing-but-empty file should use the same stub schema as a missing file
    _contradiction_pair(kb)
    (kb.root / "vault" / "facts" / "reconciliations.ndjson").write_text(
        "\n", encoding="utf-8"
    )

    assert len(query.run(kb.root, name="contradictions")[1]) == 1


def test_query_reconciliations_cli_choice(kb):
    # the named query must be a valid CLI `query` choice, not just in query.run
    _contradiction_pair(kb)
    assert cli.main(["query", "reconciliations", "--json", "--root", str(kb.root)]) == 0


def test_reconciliations_stub_exposes_full_schema(kb):
    # before the file exists, raw SQL over the stub's columns must still work
    _contradiction_pair(kb)
    cols, rows = query.run(kb.root, sql="SELECT decision, winner, reconciliation_id FROM reconciliations")
    assert rows == []
    assert "decision" in cols


def test_empty_reconciliations_file_exposes_full_schema(kb):
    _contradiction_pair(kb)
    (kb.root / "vault" / "facts" / "reconciliations.ndjson").write_text(
        "\n", encoding="utf-8"
    )

    cols, rows = query.run(
        kb.root,
        sql="SELECT decision, winner, reconciliation_id FROM reconciliations",
    )
    assert rows == []
    assert "decision" in cols


def test_where_and_limit(kb):
    kb.add_raw("a", "# A\n\nThe sky is blue.\n")
    kb.add_claim("clm_1", "a", "the sky is blue")
    kb.add_claim("clm_2", "a", "the sky is blue")
    cols, rows = query.run(kb.root, name="claims", where="claim_id = 'clm_1'", limit=10)
    assert len(rows) == 1
    assert rows[0]["claim_id"] == "clm_1"


def test_where_rejects_statement_chaining(kb):
    kb.add_raw("a", "# A\n\nThe sky is blue.\n")
    kb.add_claim("clm_1", "a", "the sky is blue")
    with pytest.raises(UsageError):
        query.run(kb.root, name="claims", where="1=1; DROP TABLE claims")


def test_unknown_named_query_is_usage_error(kb):
    with pytest.raises(UsageError):
        query.run(kb.root, name="bogus")

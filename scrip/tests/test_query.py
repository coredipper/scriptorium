import pytest

from scrip import query
from scrip.errors import UsageError


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

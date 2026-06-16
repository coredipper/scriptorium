"""`scrip similar` — deterministic topic-overlap scorer for PROMOTE step 1.
Ranks existing wiki pages by title-token + shared-source + derived-tag overlap.
Pure informational (always exit 0); no model, no lock."""

import json

import pytest

from scrip import cli


def _similar(kb, *args):
    """Run `scrip similar … --json` and return the parsed payload."""
    rc = cli.main(["similar", *args, "--json", "--root", str(kb.root)])
    return rc


def _json(capsys):
    return json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
def test_similar_high_overlap_ranks_first(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_raw("b", "# B\n\nBeta.\n")
    kb.add_raw("c", "# C\n\nGamma.\n")
    kb.add_wiki("twin", ["raw/a", "raw/b"], title="Alpha and Beta")
    kb.add_wiki("unrelated", ["raw/c"], title="Gamma only")

    rc = _similar(kb, "--title", "Alpha and Beta", "--from", "raw/a,raw/b")
    assert rc == 0
    data = _json(capsys)
    assert data["candidates"][0]["id"] == "concept/twin"
    assert data["candidates"][0]["scores"]["sources"] == 1.0
    assert data["candidates"][0]["scores"]["title"] == 1.0
    # the unrelated page is present but ranked strictly lower
    assert data["candidates"][-1]["id"] == "concept/unrelated"
    assert (
        data["candidates"][-1]["scores"]["combined"] < data["candidates"][0]["scores"]["combined"]
    )


def test_similar_partial_source_overlap_scores_between(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_raw("b", "# B\n\nBeta.\n")
    kb.add_wiki("both", ["raw/a", "raw/b"], title="Shared")
    kb.add_wiki("half", ["raw/a"], title="Partial")

    _similar(kb, "--title", "Shared", "--from", "raw/a,raw/b")
    data = _json(capsys)
    by_id = {c["id"]: c for c in data["candidates"]}
    assert by_id["concept/both"]["scores"]["sources"] == 1.0
    # half shares 1 of {a,b} → Jaccard 1/2
    assert by_id["concept/half"]["scores"]["sources"] == 0.5
    assert by_id["concept/half"]["scores"]["combined"] < by_id["concept/both"]["scores"]["combined"]


def test_similar_no_candidates_exits_0(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    rc = _similar(kb, "--title", "Anything", "--from", "raw/a")
    assert rc == 0
    assert _json(capsys)["candidates"] == []


# --------------------------------------------------------------------------- #
# Self-exclusion
# --------------------------------------------------------------------------- #
def test_similar_excludes_named_ids(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("self", ["raw/a"], title="Self Page")
    kb.add_wiki("peer", ["raw/a"], title="Self Page")

    _similar(kb, "--title", "Self Page", "--from", "raw/a", "--exclude", "concept/self")
    ids = [c["id"] for c in _json(capsys)["candidates"]]
    assert "concept/self" not in ids
    assert "concept/peer" in ids


# --------------------------------------------------------------------------- #
# Tags derived from claims (pages carry no tags frontmatter)
# --------------------------------------------------------------------------- #
def test_similar_tags_derived_from_claims(kb, capsys):
    kb.add_raw("shared", "# S\n\nA cited sentence about caching.\n")
    kb.add_raw("bare", "# B\n\nUncited content here.\n")
    kb.add_claim("clm_0001", "shared", "A cited sentence about caching.", tags=["caching", "cost"])
    kb.add_wiki("with-tags", ["raw/shared"], title="Tagged")
    kb.add_wiki("no-tags", ["raw/bare"], title="Untagged")

    _similar(kb, "--title", "Proposed", "--from", "raw/shared")
    by_id = {c["id"]: c for c in _json(capsys)["candidates"]}
    # proposed derives tags {caching,cost} from raw/shared's claim → perfect tag match
    assert by_id["concept/with-tags"]["scores"]["tags"] == 1.0
    assert by_id["concept/with-tags"]["shared"]["tags"] == ["caching", "cost"]
    # raw/bare has no claims → no tags → tag score 0
    assert by_id["concept/no-tags"]["scores"]["tags"] == 0.0


# --------------------------------------------------------------------------- #
# Block-scoped derived-from is stripped to the whole source
# --------------------------------------------------------------------------- #
def test_similar_strips_block_suffix(kb, capsys):
    kb.add_raw("a", "# Heading\n\nFirst paragraph body.\n\nSecond paragraph body.\n")
    bid = kb.block_id("a", "First paragraph")
    kb.add_wiki("whole", ["raw/a"], title="Whole source page")

    _similar(kb, "--title", "Block page", "--from", f"raw/a#{bid}")
    [cand] = _json(capsys)["candidates"]
    assert cand["id"] == "concept/whole"
    assert cand["scores"]["sources"] == 1.0  # raw/a#<block> stripped to raw/a


# --------------------------------------------------------------------------- #
# Kind filter
# --------------------------------------------------------------------------- #
def test_similar_scores_only_same_kind(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("a-concept", ["raw/a"], title="Topic", kind="concept")
    kb.add_wiki("an-entity", ["raw/a"], title="Topic", kind="entity")
    # a facts.set row also exists in scan_derived once _meta is present:
    (kb.root / "vault" / "facts" / "_meta.yaml").write_text(
        "id: facts/core\ntype: facts.set\nderived-from:\n- raw/a\n", encoding="utf-8"
    )

    _similar(kb, "--title", "Topic", "--from", "raw/a", "--kind", "concept")
    ids = [c["id"] for c in _json(capsys)["candidates"]]
    assert ids == ["concept/a-concept"]
    assert "entity/an-entity" not in ids
    assert "facts/core" not in ids


def test_similar_entity_kind_scores_entities(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("a-concept", ["raw/a"], title="Topic", kind="concept")
    kb.add_wiki("an-entity", ["raw/a"], title="Topic", kind="entity")

    _similar(kb, "--title", "Topic", "--from", "raw/a", "--kind", "entity")
    ids = [c["id"] for c in _json(capsys)["candidates"]]
    assert ids == ["entity/an-entity"]


# --------------------------------------------------------------------------- #
# --top + shape
# --------------------------------------------------------------------------- #
def test_similar_top_limits_results(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_raw("b", "# B\n\nBeta.\n")
    kb.add_wiki("p1", ["raw/a", "raw/b"], title="Best match")
    kb.add_wiki("p2", ["raw/a"], title="Partial")
    kb.add_wiki("p3", ["raw/b"], title="Other")

    _similar(kb, "--title", "Best match", "--from", "raw/a,raw/b", "--top", "1")
    data = _json(capsys)
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["id"] == "concept/p1"


def test_similar_json_shape(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("p", ["raw/a"], title="A Page")
    _similar(kb, "--title", "Proposed", "--from", "raw/a")
    data = _json(capsys)
    assert set(data) == {"proposed", "weights", "candidates"}
    assert set(data["proposed"]) == {"title", "derived_from", "kind"}
    assert set(data["weights"]) == {"title", "sources", "tags"}
    [cand] = data["candidates"]
    assert set(cand) == {"id", "title", "path", "kind", "scores", "shared"}
    assert set(cand["scores"]) == {"title", "sources", "tags", "combined"}
    assert set(cand["shared"]) == {"sources", "tags"}


def test_similar_human_output_lists_candidate(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("twin", ["raw/a"], title="Twin")
    rc = cli.main(["similar", "--title", "Twin", "--from", "raw/a", "--root", str(kb.root)])
    assert rc == 0
    assert "concept/twin" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
def test_similar_missing_title_is_usage_error(kb):
    with pytest.raises(SystemExit) as e:
        cli.main(["similar", "--from", "raw/a", "--root", str(kb.root)])
    assert e.value.code == 2


def test_similar_missing_from_is_usage_error(kb):
    with pytest.raises(SystemExit) as e:
        cli.main(["similar", "--title", "X", "--root", str(kb.root)])
    assert e.value.code == 2


def test_similar_empty_from_is_usage_error(kb):
    assert cli.main(["similar", "--title", "X", "--from", " , ", "--root", str(kb.root)]) == 2


def test_similar_outside_a_vault_is_usage_error(tmp_path):
    assert (
        cli.main(["similar", "--title", "X", "--from", "raw/a", "--root", str(tmp_path / "no")])
        == 2
    )


def test_similar_malformed_claims_is_data_error(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("p", ["raw/a"], title="P")
    (kb.root / "vault" / "facts" / "claims.ndjson").write_text("{not json}\n", encoding="utf-8")
    assert cli.main(["similar", "--title", "X", "--from", "raw/a", "--root", str(kb.root)]) == 3


def test_similar_non_object_claim_line_is_data_error(kb):
    # a valid-JSON non-object must be a clean data error (3), not an internal one (4)
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("p", ["raw/a"], title="P")
    (kb.root / "vault" / "facts" / "claims.ndjson").write_text("[]\n", encoding="utf-8")
    assert cli.main(["similar", "--title", "X", "--from", "raw/a", "--root", str(kb.root)]) == 3


def test_similar_bad_source_id_is_data_error(kb):
    # a non-string source_id is malformed facts data → exit 3, not a silent skip
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("p", ["raw/a"], title="P")
    (kb.root / "vault" / "facts" / "claims.ndjson").write_text(
        '{"source_id": 1, "tags": "oops"}\n', encoding="utf-8"
    )
    assert cli.main(["similar", "--title", "X", "--from", "raw/a", "--root", str(kb.root)]) == 3


def test_similar_bad_tags_shape_is_data_error(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("p", ["raw/a"], title="P")
    (kb.root / "vault" / "facts" / "claims.ndjson").write_text(
        '{"claim_id": "clm_0001", "source_id": "raw/a", "anchor": "qh:x|loc:0|len:1", "tags": "oops"}\n',
        encoding="utf-8",
    )
    assert cli.main(["similar", "--title", "X", "--from", "raw/a", "--root", str(kb.root)]) == 3

import pytest
from scrip.errors import DataError

from scrip import anchors, cli


def test_cli_verify_fails_on_ambiguous_by_default(kb):
    # a quote that occurs twice in the source -> AMBIGUOUS
    kb.add_raw("a", "# A\n\nalpha beta gamma. alpha beta gamma.\n")
    kb.add_claim("clm_1", "a", "alpha beta gamma.")
    assert cli.main(["verify", "--root", str(kb.root)]) == 1
    assert cli.main(["verify", "--allow-ambiguous", "--root", str(kb.root)]) == 0


def test_verify_clean_vault(kb):
    kb.add_raw("a", "# A\n\nThe sky is blue today over the hills.\n")
    kb.add_claim("clm_1", "a", "the sky is blue today")
    res = anchors.verify_vault(kb.root)
    assert res["broken"] == []
    assert res["ambiguous"] == []
    assert res["ok"] == 1


def test_verify_broken_anchor_is_listed_not_raised(kb):
    kb.add_raw("a", "# A\n\nThe sky is blue.\n")
    bogus = "qh:" + ("0" * 64) + "|loc:0.0|len:10"
    kb.add_claim("clm_1", "a", "irrelevant", anchor=bogus)
    res = anchors.verify_vault(kb.root)
    assert len(res["broken"]) == 1
    assert res["broken"][0]["where"] == "claim:clm_1"


def test_verify_missing_source_is_data_error(kb):
    kb.add_claim_record(
        {
            "claim_id": "clm_1",
            "source_id": "raw/ghost",
            "anchor": "qh:" + ("0" * 64) + "|loc:0|len:5",
        }
    )
    with pytest.raises(DataError):
        anchors.verify_vault(kb.root)


def test_verify_duplicate_claim_id_is_data_error(kb):
    kb.add_raw("a", "# A\n\nThe sky is blue.\n")
    kb.add_claim("clm_1", "a", "the sky is blue")
    kb.add_claim("clm_1", "a", "the sky is blue")
    with pytest.raises(DataError):
        anchors.verify_vault(kb.root)


def test_verify_wiki_footnote_anchor(kb):
    src = "# A\n\nMarkdown is good middleware between humans and agents.\n"
    kb.add_raw("a", src)
    anchor = anchors.make_anchor(src, "markdown is good middleware")
    body = (
        "Agents love markdown.[^a1]\n\n"
        f"[^a1]: anchor=raw/a#{anchor}  \"markdown is good middleware\"\n"
    )
    kb.add_wiki("md", ["raw/a"], body=body)
    res = anchors.verify_vault(kb.root)
    assert res["ok"] == 1
    assert res["broken"] == []

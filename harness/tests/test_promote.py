"""PROMOTE: deterministic footnote-merge unit tests + integration over the REAL
scrip CLI. The model is used only in the middle band, so high/low bands run with
no decider; the middle band uses a stub. Hermetic — no network, no LLM."""

import subprocess
import sys

import pytest
from scrip_harness.promote import PromotionDecision, merge_bodies, renumber, split_body
from scrip_harness.runner import PromoteError, promote_page

from scrip import anchors, frontmatter


# --------------------------------------------------------------------------- #
# Pure merge logic (no scrip)
# --------------------------------------------------------------------------- #
def test_split_body_separates_prose_from_definitions():
    body = 'Claim one.[^a1]\n\n[^a1]: anchor=raw/x#qh:aa|loc:0|len:2  "x"\n'
    prose, defs = split_body(body)
    assert prose == "Claim one.[^a1]"
    assert defs == ['[^a1]: anchor=raw/x#qh:aa|loc:0|len:2  "x"']


def test_renumber_offsets_all_labels():
    body = 'A.[^a1] B.[^a2]\n\n[^a1]: anchor=raw/x#q  "A"\n[^a2]: anchor=raw/x#q2  "B"\n'
    out = renumber(body, 3)  # continue after a target's two footnotes
    assert "[^a3]" in out and "[^a4]" in out
    assert "[^a1]" not in out and "[^a2]" not in out


def test_merge_bodies_renumbers_absorbed_no_collision():
    target = 'T.[^a1]\n\n[^a1]: anchor=raw/x#q  "T"\n'
    absorbed = 'B.[^a1]\n\n[^a1]: anchor=raw/y#q  "B"\n'
    merged = merge_bodies(target, absorbed)
    # target keeps a1; absorbed's a1 becomes a2 — no collision
    assert merged.count("[^a1]:") == 1
    assert merged.count("[^a2]:") == 1
    assert "T.[^a1]" in merged and "B.[^a2]" in merged
    # all definitions land at the bottom, after both prose lines
    assert merged.index("B.[^a2]") < merged.index("[^a1]:")


# --------------------------------------------------------------------------- #
# Integration helpers
# --------------------------------------------------------------------------- #
def _vault(tmp_path):
    for d in ("vault/raw", "vault/wiki/concepts", "vault/wiki/entities", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")
    return tmp_path


def _raw(root, slug, text):
    (root / "vault" / "raw" / f"{slug}.md").write_text(text, encoding="utf-8")


def _page(root, slug, title, sources, cites, *, kind="concept"):
    """Write a wiki page whose footnotes anchor real quotes. `cites` is a list of
    (quote, source_slug); markers a1.. are emitted in order."""
    prose, defs = [], []
    for i, (quote, ssl) in enumerate(cites, 1):
        prose.append(f"Point {i}.[^a{i}]")
        src = (root / "vault" / "raw" / f"{ssl}.md").read_text(encoding="utf-8")
        anchor = anchors.make_anchor(src, quote)
        defs.append(f'[^a{i}]: anchor=raw/{ssl}#{anchor}  "{quote[:32]}"')
    body = "\n".join(prose) + "\n\n" + "\n".join(defs) + "\n"
    meta = {
        "id": f"{kind}/{slug}",
        "type": f"wiki.{kind}",
        "title": title,
        "derived-from": list(sources),
        "confidence": 0.8,
    }
    p = root / "vault" / "wiki" / f"{kind}s" / f"{slug}.md"
    p.write_text(frontmatter.dump(meta, body), encoding="utf-8")
    return p


def _verify(root):
    return subprocess.run(
        [sys.executable, "-m", "scrip.cli", "verify", "--root", str(root)],
        capture_output=True, text=True,
    ).returncode


# --------------------------------------------------------------------------- #
# High band — deterministic merge, no model
# --------------------------------------------------------------------------- #
def test_promote_high_band_merges_without_a_model(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "alpha", "# A\n\nAlpha one sentence.\n\nAlpha two sentence.\n")
    _raw(root, "beta", "# B\n\nBeta one sentence.\n")
    target = _page(root, "compilation", "Compilation",
                   ["raw/alpha", "raw/beta"], [("Alpha one sentence.", "alpha")])
    absorbed = _page(root, "compilation-redux", "Compilation",
                     ["raw/alpha", "raw/beta"], [("Beta one sentence.", "beta")])

    # high band (shared sources + same title → combined 0.75) needs no decider
    result = promote_page(root, "compilation-redux", decide_fn=None)
    assert result["action"] == "merge"
    assert result["target"] == "concept/compilation"

    assert not absorbed.exists()  # absorbed page deleted; id lives on in supersedes
    meta, body = frontmatter.load(target)
    assert meta["supersedes"] == ["concept/compilation-redux"]
    assert set(meta["derived-from"]) == {"raw/alpha", "raw/beta"}
    assert "Point 1.[^a1]" in body and "[^a2]" in body  # absorbed footnote renumbered in
    assert _verify(root) == 0  # vault still green


# --------------------------------------------------------------------------- #
# Low band — keep, no mutation
# --------------------------------------------------------------------------- #
def test_promote_low_band_keeps(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "alpha", "# A\n\nAlpha one sentence.\n")
    _raw(root, "b1", "# B1\n\nB one sentence.\n")
    _raw(root, "b2", "# B2\n\nB two sentence.\n")
    _page(root, "existing", "Totally different",
          ["raw/b1", "raw/b2"], [("B one sentence.", "b1")])
    candidate = _page(root, "newbie", "Fresh topic", ["raw/alpha"],
                      [("Alpha one sentence.", "alpha")])

    result = promote_page(root, "newbie", decide_fn=None)
    assert result["action"] == "keep"
    assert candidate.exists()  # untouched
    assert "supersedes" not in frontmatter.load(root / "vault/wiki/concepts/existing.md")[0]


# --------------------------------------------------------------------------- #
# Middle band — the only model use
# --------------------------------------------------------------------------- #
def _middle_vault(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "alpha", "# A\n\nAlpha one sentence.\n")
    _raw(root, "beta", "# B\n\nBeta one sentence.\n")
    # existing shares 1 of {alpha} → sources Jaccard 0.5 → combined 0.25 (middle)
    _page(root, "pair", "Pair page", ["raw/alpha", "raw/beta"],
          [("Alpha one sentence.", "alpha")])
    _page(root, "solo", "Solo page", ["raw/alpha"], [("Alpha one sentence.", "alpha")])
    return root


def test_promote_middle_band_merges_on_model_decision(tmp_path):
    root = _middle_vault(tmp_path)
    calls = []

    def decide(candidate_text, candidates):
        calls.append(candidates)
        return PromotionDecision(decision="merge", target_id="concept/pair", reasoning="same topic")

    result = promote_page(root, "solo", decide_fn=decide)
    assert len(calls) == 1  # model consulted exactly once, in the middle band
    assert result["action"] == "merge" and result["target"] == "concept/pair"
    assert not (root / "vault/wiki/concepts/solo.md").exists()
    assert frontmatter.load(root / "vault/wiki/concepts/pair.md")[0]["supersedes"] == ["concept/solo"]
    assert _verify(root) == 0


def test_promote_middle_band_keeps_on_model_decision(tmp_path):
    root = _middle_vault(tmp_path)

    def decide(candidate_text, candidates):
        return PromotionDecision(decision="keep", reasoning="distinct enough")

    result = promote_page(root, "solo", decide_fn=decide)
    assert result["action"] == "keep"
    assert (root / "vault/wiki/concepts/solo.md").exists()


def test_promote_middle_band_without_decider_errors(tmp_path):
    root = _middle_vault(tmp_path)
    with pytest.raises(PromoteError):
        promote_page(root, "solo", decide_fn=None)


# --------------------------------------------------------------------------- #
# Dry run + guards
# --------------------------------------------------------------------------- #
def test_promote_dry_run_mutates_nothing(tmp_path):
    root = _vault(tmp_path)
    _raw(root, "alpha", "# A\n\nAlpha one sentence.\n")
    _raw(root, "beta", "# B\n\nBeta one sentence.\n")
    target = _page(root, "compilation", "Compilation",
                   ["raw/alpha", "raw/beta"], [("Alpha one sentence.", "alpha")])
    absorbed = _page(root, "compilation-redux", "Compilation",
                     ["raw/alpha", "raw/beta"], [("Beta one sentence.", "beta")])
    before_target = target.read_text(encoding="utf-8")
    before_absorbed = absorbed.read_text(encoding="utf-8")

    result = promote_page(root, "compilation-redux", decide_fn=None, dry_run=True)
    assert result["action"] == "merge" and result["dry_run"] is True
    assert result["target"] == "concept/compilation"
    assert target.read_text(encoding="utf-8") == before_target  # unchanged
    assert absorbed.read_text(encoding="utf-8") == before_absorbed  # still present, unchanged


def test_promote_missing_page_errors(tmp_path):
    root = _vault(tmp_path)
    with pytest.raises(PromoteError):
        promote_page(root, "does-not-exist", decide_fn=None)


def test_promote_rejects_unsafe_slug(tmp_path):
    root = _vault(tmp_path)
    # a traversal slug must be rejected by an explicit guard (not incidentally by
    # a missing-file check), before any path is built or unlinked
    with pytest.raises(PromoteError, match="invalid slug"):
        promote_page(root, "../../etc/passwd", decide_fn=None)


def test_promote_preserves_absorbed_page_when_verify_fails(tmp_path):
    """The absorbed page must not be deleted until stamp+verify succeed: a
    failure (here, a pre-existing broken anchor elsewhere) must not lose data."""
    root = _vault(tmp_path)
    _raw(root, "alpha", "# A\n\nAlpha one sentence.\n")
    _raw(root, "beta", "# B\n\nBeta one sentence.\n")
    _raw(root, "broken", "# Broken\n\nReal content here.\n")
    target = _page(root, "compilation", "Compilation",
                   ["raw/alpha", "raw/beta"], [("Alpha one sentence.", "alpha")])
    absorbed = _page(root, "compilation-redux", "Compilation",
                     ["raw/alpha", "raw/beta"], [("Beta one sentence.", "beta")])
    # an unrelated page with a BROKEN anchor makes vault-wide `scrip verify` fail
    broken = root / "vault" / "wiki" / "concepts" / "broken.md"
    broken.write_text(
        frontmatter.dump(
            {"id": "concept/broken", "type": "wiki.concept", "title": "Z page",
             "derived-from": ["raw/broken"], "confidence": 0.5},
            'Claim.[^a1]\n\n[^a1]: anchor=raw/broken#qh:deadbeef|loc:0.0|len:99  "absent"\n',
        ),
        encoding="utf-8",
    )
    target_before = target.read_text(encoding="utf-8")

    with pytest.raises(PromoteError):
        promote_page(root, "compilation-redux", decide_fn=None)
    # the merge is atomic: on stamp/verify failure BOTH pages are left untouched,
    # so a rerun after fixing the failure cannot duplicate the absorbed content
    assert absorbed.exists()
    assert target.read_text(encoding="utf-8") == target_before

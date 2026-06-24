"""Integration smoke test: stub the model, drive the REAL `scrip` CLI over a temp
vault, and assert the compiled page is verified and stamped. Hermetic — no network,
no LLM (the draft is stubbed); `scrip` runs from the harness's own scriptoria."""

import subprocess
import sys

import pytest
from scrip_harness import runner
from scrip_harness.compile import DraftClaim, DraftPage
from scrip_harness.runner import CompileError, compile_page


def test_default_scrip_cmd_runs_the_bundled_scriptoria():
    """The harness must drive its OWN installed scriptoria, not a bare `scrip` on
    PATH: a `uv tool install scrip-harness` exposes scrip-harness's entry point but
    not its dependency's, so a PATH `scrip` may be absent or a different version.
    Invoking via the running interpreter (`-m scrip.cli`) pins both."""
    import scrip

    assert runner.DEFAULT_SCRIP_CMD == (sys.executable, "-m", "scrip.cli")
    r = subprocess.run(
        [*runner.DEFAULT_SCRIP_CMD, "--version"], capture_output=True, text=True
    )
    assert r.returncode == 0
    # exactly the scriptoria the harness imports — no PATH version skew
    assert scrip.__version__ in r.stdout


def _vault(tmp_path):
    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")
    return tmp_path


def test_compile_produces_a_verified_stamped_page(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# Topic\n\nThe key insight is that compiled knowledge compounds over time "
        "rather than evaporating after each session.\n\nProvenance is checkable by "
        "content, not by line number.\n",
        encoding="utf-8",
    )

    def stub(source_text, *, source_id):
        return DraftPage(
            title="Topic",
            body="Compiled knowledge compounds over time.[^a1]\n",
            claims=[
                DraftClaim(quote="compiled knowledge compounds over time rather than evaporating")
            ],
        )

    page = compile_page(root, "topic", draft_fn=stub)
    assert page.exists()
    text = page.read_text(encoding="utf-8")
    assert "id: concept/topic" in text
    assert "input-hash: sha256:" in text  # stamped
    assert "[^a1]: anchor=raw/topic#qh:" in text  # minted, verified footnote


def test_compile_rejects_a_non_verbatim_quote(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# T\n\nThe actual content of the source.\n", encoding="utf-8"
    )

    def stub(source_text, *, source_id, failures=None):
        # keeps proposing the absent quote through every retry → clean failure
        return DraftPage(
            title="T",
            body="A hallucinated claim.[^a1]\n",
            claims=[DraftClaim(quote="this sentence is absent from the source")],
        )

    with pytest.raises(CompileError):
        compile_page(root, "topic", draft_fn=stub)
    # nothing was left behind as a stamped page
    assert not (root / "vault" / "wiki" / "concepts" / "topic.md").exists()


def test_compile_rejects_marker_mismatch(tmp_path):
    """If the draft body's markers don't match the claims (here: a2 missing for two
    claims), the compile must fail before stamping — scrip verify wouldn't catch
    uncited prose on its own."""
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# T\n\nFirst real fact. Second real fact in the same source.\n", encoding="utf-8"
    )

    def stub(source_text, *, source_id):
        return DraftPage(
            title="T",
            body="Only one marker.[^a1]\n",  # but two claims supplied
            claims=[DraftClaim(quote="first real fact"), DraftClaim(quote="second real fact")],
        )

    with pytest.raises(CompileError):
        compile_page(root, "topic", draft_fn=stub)


def test_compile_rejects_leading_zero_and_foreign_markers(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# T\n\nA real fact in the source.\n", encoding="utf-8"
    )

    def leading_zero(source_text, *, source_id):
        return DraftPage(title="T", body="x[^a01]\n", claims=[DraftClaim(quote="a real fact")])

    def foreign(source_text, *, source_id):
        return DraftPage(
            title="T", body="ok[^a1] extra[^b1]\n", claims=[DraftClaim(quote="a real fact")]
        )

    with pytest.raises(CompileError):
        compile_page(root, "topic", draft_fn=leading_zero)
    with pytest.raises(CompileError):
        compile_page(root, "topic", draft_fn=foreign)


def test_compile_rejects_slug_with_trailing_newline(tmp_path):
    root = _vault(tmp_path)
    called = False

    def stub(source_text, *, source_id):
        nonlocal called
        called = True
        return DraftPage(title="x", body="x[^a1]\n", claims=[DraftClaim(quote="x")])

    with pytest.raises(CompileError):
        compile_page(root, "topic\n", draft_fn=stub)
    assert called is False


def test_compile_missing_source_is_a_clean_error(tmp_path):
    root = _vault(tmp_path)
    called = False

    def stub(source_text, *, source_id):
        nonlocal called
        called = True
        return DraftPage(title="x", body="x[^a1]\n", claims=[DraftClaim(quote="x")])

    with pytest.raises(CompileError, match="raw/absent"):
        compile_page(root, "absent", draft_fn=stub)
    assert called is False  # no model call for a source that does not exist


def test_compile_rejects_unsafe_slug(tmp_path):
    root = _vault(tmp_path)
    called = False

    def stub(source_text, *, source_id):
        nonlocal called
        called = True
        return DraftPage(title="x", body="x[^a1]\n", claims=[DraftClaim(quote="x")])

    with pytest.raises(CompileError):
        compile_page(root, "../../etc/passwd", draft_fn=stub)
    assert called is False  # rejected before reading any source or calling the model


# --------------------------------------------------------------------------- #
# The quote-retry loop (mirror of EXTRACT, but claims keep their marker slots)
# --------------------------------------------------------------------------- #
def test_compile_retries_a_failed_quote_then_compiles(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "alpha beta. alpha beta. gamma delta is a unique closing sentence.\n",
        encoding="utf-8",
    )
    calls = []

    def stub(source_text, *, source_id, failures=None):
        calls.append(failures)
        if failures is None:
            # one good claim + one AMBIGUOUS claim ("alpha beta." appears twice)
            return DraftPage(
                title="Topic",
                body="Unique fact.[^a1] Ambiguous fact.[^a2]\n",
                claims=[
                    DraftClaim(quote="gamma delta is a unique closing sentence."),
                    DraftClaim(quote="alpha beta."),
                ],
            )
        # asked to fix exactly the failing quote — one replacement, in order, the
        # body/title are ignored on retry (only the corrected claim is used)
        assert [f["status"] for f in failures] == ["AMBIGUOUS"]
        assert failures[0]["index"] == 1  # the second claim is the one that failed
        return DraftPage(
            title="(ignored on retry)",
            body="(ignored on retry)\n",
            claims=[DraftClaim(quote="alpha beta. alpha beta.")],
        )

    page = compile_page(root, "topic", draft_fn=stub)
    assert len(calls) == 2  # one draft + one targeted retry
    text = page.read_text(encoding="utf-8")
    # both markers minted against the source; the prose is the ORIGINAL draft body
    assert "Unique fact.[^a1] Ambiguous fact.[^a2]" in text
    assert "[^a1]: anchor=raw/topic#qh:" in text
    assert "[^a2]: anchor=raw/topic#qh:" in text
    assert (
        subprocess.run(
            [sys.executable, "-m", "scrip.cli", "verify", "--root", str(root)]
        ).returncode
        == 0
    )


def test_compile_fails_cleanly_after_retry_exhaustion(tmp_path):
    root = _vault(tmp_path)
    (root / "vault" / "raw" / "topic.md").write_text(
        "# T\n\nThe only real text here.\n", encoding="utf-8"
    )
    calls = []

    def stub(source_text, *, source_id, failures=None):
        calls.append(failures)
        return DraftPage(
            title="T",
            body="Claim.[^a1]\n",
            claims=[DraftClaim(quote="a quote that is never present in the source")],
        )

    with pytest.raises(CompileError):
        compile_page(root, "topic", draft_fn=stub, max_quote_retries=2)
    assert len(calls) == 3  # initial draft + 2 bounded retries
    assert not (root / "vault" / "wiki" / "concepts" / "topic.md").exists()


# --------------------------------------------------------------------------- #
# Multi-source COMPILE: one page synthesized from several raw sources
# --------------------------------------------------------------------------- #
def _two_sources(root):
    (root / "vault" / "raw" / "a.md").write_text(
        "# A\n\nAlpha asserts the first unique fact clearly.\n", encoding="utf-8"
    )
    (root / "vault" / "raw" / "b.md").write_text(
        "# B\n\nBeta provides a second distinct fact here.\n", encoding="utf-8"
    )


def test_compile_synthesizes_from_multiple_sources(tmp_path):
    root = _vault(tmp_path)
    _two_sources(root)

    def stub(source_text, *, source_id, failures=None):
        # the prompt carries BOTH labelled sources so the model can attribute quotes
        assert "raw/a" in source_text and "raw/b" in source_text
        return DraftPage(
            title="Combined",
            body="First point.[^a1] Second point.[^a2]\n",
            claims=[
                DraftClaim(quote="Alpha asserts the first unique fact", source_id="raw/a"),
                DraftClaim(quote="Beta provides a second distinct fact", source_id="raw/b"),
            ],
        )

    page = compile_page(root, "combined", sources=["raw/a", "raw/b"], draft_fn=stub)
    text = page.read_text(encoding="utf-8")
    # derived from BOTH sources, and each footnote anchors to its OWN source
    assert "- raw/a" in text and "- raw/b" in text
    assert "[^a1]: anchor=raw/a#qh:" in text
    assert "[^a2]: anchor=raw/b#qh:" in text
    assert subprocess.run(
        [sys.executable, "-m", "scrip.cli", "verify", "--root", str(root)]
    ).returncode == 0


def test_compile_rejects_a_claim_citing_an_unknown_source(tmp_path):
    root = _vault(tmp_path)
    _two_sources(root)

    def stub(source_text, *, source_id, failures=None):
        return DraftPage(
            title="Combined",
            body="First.[^a1]\n",
            claims=[DraftClaim(quote="Alpha asserts the first unique fact", source_id="raw/c")],
        )

    with pytest.raises(CompileError):
        compile_page(root, "combined", sources=["raw/a", "raw/b"], draft_fn=stub)
    assert not (root / "vault" / "wiki" / "concepts" / "combined.md").exists()


def test_compile_requires_source_id_when_multiple_sources(tmp_path):
    root = _vault(tmp_path)
    _two_sources(root)

    def stub(source_text, *, source_id, failures=None):
        # a claim with no source_id is ambiguous when more than one source is given
        return DraftPage(
            title="Combined",
            body="First.[^a1]\n",
            claims=[DraftClaim(quote="Alpha asserts the first unique fact")],
        )

    with pytest.raises(CompileError):
        compile_page(root, "combined", sources=["raw/a", "raw/b"], draft_fn=stub)
    assert not (root / "vault" / "wiki" / "concepts" / "combined.md").exists()

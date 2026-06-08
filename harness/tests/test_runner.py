"""Integration smoke test: stub the model, drive the REAL `scrip` CLI over a temp
vault, and assert the compiled page is verified and stamped. Hermetic — no network,
no LLM (the draft is stubbed); `scrip` is the path-dependency console script."""

import pytest

from scrip_harness.compile import DraftClaim, DraftPage
from scrip_harness.runner import CompileError, compile_page


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

    def stub(source_text, *, source_id):
        return DraftPage(
            title="T",
            body="A hallucinated claim.[^a1]\n",
            claims=[DraftClaim(quote="this sentence is absent from the source")],
        )

    with pytest.raises(CompileError):
        compile_page(root, "topic", draft_fn=stub)
    # nothing was left behind as a stamped page
    assert not (root / "vault" / "wiki" / "concepts" / "topic.md").exists()

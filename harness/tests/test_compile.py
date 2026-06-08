"""Pure unit tests for the deterministic compile helpers — no model, no scrip."""

from scrip_harness.compile import (
    DraftClaim,
    DraftPage,
    assemble_body,
    build_user_prompt,
    extract_markers,
)


def test_extract_markers_returns_labels_in_first_appearance_order():
    assert extract_markers("First.[^a1] Second.[^a2]\n") == ["a1", "a2"]
    assert extract_markers("no markers here") == []
    assert extract_markers("b[^a2] a[^a1]") == ["a2", "a1"]
    assert extract_markers("x[^a1] again[^a1]") == ["a1"]
    # malformed / foreign labels are surfaced verbatim so validation can reject
    # them — a leading-zero label is NOT the same as a1, and [^b1] is foreign.
    assert extract_markers("x[^a01] y[^b1]") == ["a01", "b1"]


def test_build_user_prompt_includes_the_source():
    prompt = build_user_prompt("a distinctive source sentence")
    assert "SOURCE" in prompt
    assert "a distinctive source sentence" in prompt


def test_assemble_body_appends_footnote_definitions():
    draft = DraftPage(
        title="T",
        body="The first claim.[^a1]\nThe second.[^a2]\n",
        claims=[DraftClaim(quote="first"), DraftClaim(quote="second")],
    )
    footnotes = [
        '[^a1]: anchor=raw/s#qh:aaa|loc:0.0|len:5  "first"',
        '[^a2]: anchor=raw/s#qh:bbb|loc:0.5|len:6  "second"',
    ]
    body = assemble_body(draft, footnotes)
    assert body.startswith("The first claim.[^a1]")
    assert "[^a1]: anchor=raw/s#qh:aaa" in body
    assert "[^a2]: anchor=raw/s#qh:bbb" in body
    assert body.endswith("\n")
    # the marker prose and the definitions are separated by a blank line
    assert "[^a2]\n\n[^a1]:" in body

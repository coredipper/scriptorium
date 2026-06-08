"""Deterministic pieces of the compile loop: the structured draft schema, prompt
construction, and page-body assembly. No network, no scrip — unit-testable."""

from __future__ import annotations

import re

from pydantic import BaseModel

_MARKER = re.compile(r"\[\^a(\d+)\]")


def extract_markers(body: str) -> list[int]:
    """Footnote marker numbers in ``body``, distinct, in first-appearance order
    (``[^a1]`` → 1). Used to check the model's prose matches the claims it
    returned before any page is stamped."""
    seen: list[int] = []
    for m in _MARKER.finditer(body):
        k = int(m.group(1))
        if k not in seen:
            seen.append(k)
    return seen

SYSTEM = (
    "You are the scribe for a scriptorium knowledge base. From the single source "
    "you are given, synthesize a concise, accurate concept page in markdown.\n"
    "Rules:\n"
    "- Write only what the source supports; do not add outside facts.\n"
    "- Mark each claim-bearing sentence with a footnote marker ([^a1], [^a2], …) "
    "in order of first appearance.\n"
    "- For every marker, return one claim whose `quote` is copied VERBATIM from the "
    "source (it is machine-verified against the source text; paraphrases are "
    "rejected). Quote enough words to be unique.\n"
    "- Keep the body free of the footnote *definitions* — only the markers. The "
    "definitions are generated from your quotes."
)


class DraftClaim(BaseModel):
    quote: str
    """Verbatim text copied from the source, supporting the matching marker."""
    note: str = ""
    """Optional human-readable note on what the claim asserts."""


class DraftPage(BaseModel):
    title: str
    body: str
    """Markdown prose containing footnote markers [^a1], [^a2], … in order."""
    claims: list[DraftClaim]
    """One claim per marker, in the same order as the markers in `body`."""


def build_user_prompt(source_text: str) -> str:
    return (
        "Synthesize a concept page from the source below. In the body, mark each "
        "claim-bearing sentence with a footnote marker [^a1], [^a2], … in order. "
        "Return one claim per marker (same order), each with a `quote` copied "
        "verbatim from the source.\n\n----- SOURCE -----\n" + source_text
    )


def assemble_body(draft: DraftPage, footnotes: list[str]) -> str:
    """Combine the model's prose (with markers) and the scrip-minted footnote
    definition lines into the final page body."""
    return draft.body.rstrip() + "\n\n" + "\n".join(footnotes) + "\n"

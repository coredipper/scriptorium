"""Deterministic pieces of the compile loop: the structured draft schema, prompt
construction, and page-body assembly. No network, no scrip — unit-testable."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel

# Match ANY footnote reference label, not just well-formed a-markers, so that a
# foreign ([^b1]) or malformed ([^a01]) reference is surfaced and rejected rather
# than silently ignored (which would leave an undefined footnote in the page).
_MARKER = re.compile(r"\[\^([^\]]+)\]")


def extract_markers(body: str) -> list[str]:
    """Footnote reference *labels* in ``body``, distinct, in first-appearance order
    (``[^a1]`` → ``"a1"``). Returned verbatim — the caller requires them to be
    exactly ``a1..aN`` (no leading zeros, no foreign labels) before stamping."""
    # ⚡ Bolt: Use dict.fromkeys() for O(1) deduplication while preserving insertion order
    return list(dict.fromkeys(m.group(1) for m in _MARKER.finditer(body)))

SYSTEM = (
    "You are the scribe for a scriptorium knowledge base. From the source(s) "
    "you are given, synthesize a concise, accurate concept page in markdown.\n"
    "Rules:\n"
    "- Write only what the source supports; do not add outside facts.\n"
    "- Mark each claim-bearing sentence with a footnote marker ([^a1], [^a2], …) "
    "in order of first appearance.\n"
    "- For every marker, return one claim whose `quote` is copied VERBATIM from the "
    "source (it is machine-verified against the source text; paraphrases are "
    "rejected). Quote enough words to be unique.\n"
    "- When several sources are provided (each under a `----- SOURCE <id> -----` "
    "header), set each claim's `source_id` to the id of the source its quote was "
    "copied from; with a single source you may leave it empty.\n"
    "- Keep the body free of the footnote *definitions* — only the markers. The "
    "definitions are generated from your quotes."
)


class DraftClaim(BaseModel):
    quote: str
    """Verbatim text copied from the source, supporting the matching marker."""
    source_id: str = ""
    """Which source the quote was copied from (e.g. ``raw/a``), for multi-source
    compiles. Empty means the page's sole source."""
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


def format_sources(sources: list[tuple[str, str]]) -> str:
    """Concatenate labelled sources for a multi-source compile so the model can
    attribute each quote to the source it came from (and set the claim's
    ``source_id``). Each section is ``----- SOURCE <id> -----`` then that source's
    text — the same header the system prompt tells the model to read."""
    return "\n\n".join(f"----- SOURCE {sid} -----\n{text}" for sid, text in sources)


def build_compile_retry_prompt(source_text: str, failures: list[dict]) -> str:
    """Ask for a replacement for each failed quote, in the reported order. Unlike
    EXTRACT, COMPILE keeps *every* claim — the body's ``[^a1]..[^aN]`` markers are
    positional, so dropping one would misnumber the rest — hence there is no
    empty-quote drop option: each failure needs a corrected verbatim quote."""
    listing = "\n".join(
        f"- status {f['status']}: {json.dumps(f.get('quote', ''), ensure_ascii=False)}"
        f" ({f.get('detail', '')})"
        for f in failures
    )
    return (
        "Some quotes you proposed did not verify against the source: an AMBIGUOUS "
        "quote appears more than once (lengthen it until unique); a BROKEN quote "
        "is not present verbatim (re-copy it exactly).\n\n"
        f"Failed quotes, in order:\n{listing}\n\n"
        "Return exactly one replacement claim per failed quote, in the same order, "
        "each with a corrected verbatim `quote`. Every claim must keep a supporting "
        "quote.\n\n----- SOURCE -----\n" + source_text
    )


def assemble_body(draft: DraftPage, footnotes: list[str]) -> str:
    """Combine the model's prose (with markers) and the scrip-minted footnote
    definition lines into the final page body."""
    return draft.body.rstrip() + "\n\n" + "\n".join(footnotes) + "\n"

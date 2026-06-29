"""Deterministic pieces of the extract loop: the structured fact schema, prompt
construction, and the NDJSON serialization `scrip fact add` consumes. No
network, no scrip — unit-testable."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

EXTRACT_SYSTEM = (
    "You are the scribe for a scriptorium knowledge base. From the source(s) "
    "you are given, extract atomic factual claims as structured records.\n"
    "Rules:\n"
    "- Extract only what the source supports; do not add outside facts.\n"
    "- Each claim's `quote` is copied VERBATIM from the source (it is "
    "machine-verified against the source text; paraphrases are rejected). Quote "
    "enough words to be unique within the source.\n"
    "- When several sources are provided (each under a `----- SOURCE <id> -----` "
    "header), set each claim's `source_id` to the id of the source its quote was "
    "copied from; with a single source you may leave it empty.\n"
    "- `subject`/`predicate`/`object` form a coarse triple used for grouping and "
    "contradiction detection: keep them short, lowercase noun/verb phrases, and "
    "reuse the same wording for the same idea across claims.\n"
    "- `polarity` is `asserts`, `denies`, or `qualifies` — what the source does "
    "to the triple, not your judgment of it.\n"
    "- `claim_text` is an optional one-sentence restatement; leave it empty to "
    "reuse the quote.\n"
    "- `confidence` in [0, 1] is your honest rating that the claim faithfully "
    "represents the source."
)


class DraftFact(BaseModel):
    quote: str
    """Verbatim text copied from the source; anchors are minted from this."""
    subject: str
    predicate: str
    object: str
    polarity: Literal["asserts", "denies", "qualifies"] = "asserts"
    confidence: float = 0.8
    claim_text: str = ""
    """Optional restatement; empty means the quote itself is the claim text."""
    tags: list[str] = []
    source_id: str = ""
    """For multi-source extraction, which ``--from`` source this quote came from
    (e.g. ``raw/a``); empty means the run's sole source. The runner mints each
    claim's anchor against this, so a mis-attributed quote fails quote-verify."""


class DraftExtraction(BaseModel):
    claims: list[DraftFact]


def build_extract_prompt(source_text: str) -> str:
    return (
        "Extract the atomic factual claims from the source below as structured "
        "records. Each claim needs a verbatim `quote`, a subject/predicate/object "
        "triple, and a polarity.\n\n----- SOURCE -----\n" + source_text
    )


def build_extract_retry_prompt(source_text: str, failures: list[dict]) -> str:
    """Ask for a replacement for each failed quote, in the reported order. An
    empty replacement quote tells the runner to drop that claim."""
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
        "Return exactly one replacement claim per failed quote, in the same "
        "order, with the corrected verbatim `quote` and the claim's triple/"
        "polarity. If a claim cannot be supported by a verbatim quote, return it "
        "with an empty `quote` to drop it.\n\n----- SOURCE -----\n" + source_text
    )


def to_ndjson(facts: list[DraftFact], default_source_id: str) -> str:
    """Serialize proposed facts as the NDJSON `scrip fact add --stdin` expects.
    scrip owns `anchor`/`claim_id`/`extracted_at`, so they never appear here;
    empty `claim_text`/`tags` are omitted so scrip applies its defaults. Each
    claim's own `source_id` wins over ``default_source_id`` (the run's sole
    source), so a multi-source extract attributes each quote to its source."""
    lines = []
    for f in facts:
        rec: dict = {
            "quote": f.quote,
            "subject": f.subject,
            "predicate": f.predicate,
            "object": f.object,
            "polarity": f.polarity,
            "confidence": f.confidence,
            "source_id": f.source_id or default_source_id,
        }
        if f.claim_text:
            rec["claim_text"] = f.claim_text
        if f.tags:
            rec["tags"] = f.tags
        lines.append(json.dumps(rec, ensure_ascii=False))
    return "".join(line + "\n" for line in lines)

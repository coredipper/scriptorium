"""Deterministic pieces of RECONCILE: the decision schema and prompt. No scrip,
no network — unit-testable. The model adjudicates a contradiction pair; scrip
records the decision (`scrip fact add --table reconciliations`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ReconciliationDecision(BaseModel):
    decision: Literal["supersede", "qualify", "keep-both"]
    winner: Literal["a", "b"] | None = None
    """Which claim wins, for `supersede` only: "a" = claim_a, "b" = claim_b."""
    rationale: str = ""


RECONCILE_SYSTEM = (
    "You are the scribe for a scriptorium knowledge base resolving a contradiction "
    "between two extracted claims (same subject+predicate, opposing polarity, "
    "different sources). You are given each claim's verbatim cited span. Decide:\n"
    "- `supersede` — one claim is right and the other should be retired; set "
    '`winner` to "a" or "b".\n'
    "- `qualify` — both hold under different conditions; the disagreement should be "
    "nuanced rather than resolved.\n"
    "- `keep-both` — the sources genuinely disagree and both should stand on record.\n"
    "Decide only from the cited spans; give a one-sentence `rationale`."
)


def build_reconcile_prompt(pair: dict, span_a: str | None, span_b: str | None) -> str:
    return (
        f"Contradiction on subject={pair['subject']!r} predicate={pair['predicate']!r}.\n\n"
        f"----- CLAIM A ({pair['claim_a']}, from {pair['source_a']}) -----\n"
        f"{span_a or '(span did not resolve)'}\n\n"
        f"----- CLAIM B ({pair['claim_b']}, from {pair['source_b']}) -----\n"
        f"{span_b or '(span did not resolve)'}\n\n"
        "Decide: supersede (with winner a|b), qualify, or keep-both."
    )

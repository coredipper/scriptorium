"""Deterministic pieces of the PROMOTE merge, plus the middle-band decision
schema/prompt. No scrip, no network — unit-testable.

A page body is `prose-with-markers \n\n footnote-definition-lines`. Merging the
absorbed page B into target A appends B's prose after A's and collects all
definitions at the bottom — but B's `[^a1]..` labels would collide with A's, so
B's footnotes are renumbered to continue A's sequence first.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

# A footnote DEFINITION line: `[^a1]: anchor=raw/x#…  "quote"`
_DEF = re.compile(r"^\[\^([^\]]+)\]:\s*anchor=")
# Any footnote reference/marker (also matches the label inside a definition line).
_MARKER = re.compile(r"\[\^([^\]]+)\]")


def split_body(body: str) -> tuple[str, list[str]]:
    """Return ``(prose, definition_lines)``. Definition lines are the footnote
    definitions; prose is everything else with trailing blank lines trimmed."""
    prose: list[str] = []
    defs: list[str] = []
    for line in body.splitlines():
        (defs if _DEF.match(line) else prose).append(line)
    return "\n".join(prose).rstrip(), defs


def _labels_in_order(body: str) -> list[str]:
    seen: list[str] = []
    for m in _MARKER.finditer(body):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def renumber(body: str, start: int) -> str:
    """Renumber every footnote label in ``body`` to ``a{start}, a{start+1}, …``
    in first-appearance order, rewriting both prose markers and definition labels
    consistently."""
    remap = {old: f"a{start + i}" for i, old in enumerate(_labels_in_order(body))}
    return _MARKER.sub(lambda m: f"[^{remap[m.group(1)]}]", body)


def merge_bodies(target_body: str, absorbed_body: str) -> str:
    """Append ``absorbed_body`` into ``target_body``, renumbering the absorbed
    page's footnotes to continue the target's, with all definitions at the
    bottom."""
    t_prose, t_defs = split_body(target_body)
    absorbed_renum = renumber(absorbed_body, len(t_defs) + 1)
    a_prose, a_defs = split_body(absorbed_renum)

    prose = f"{t_prose}\n\n{a_prose}" if a_prose else t_prose
    defs = t_defs + a_defs
    body = prose
    if defs:
        body += "\n\n" + "\n".join(defs)
    return body + "\n"


# --------------------------------------------------------------------------- #
# Middle-band decision (the only model-driven part of PROMOTE)
# --------------------------------------------------------------------------- #
class PromotionDecision(BaseModel):
    decision: Literal["merge", "keep"]
    target_id: str | None = None
    """The candidate id to merge into when decision == "merge"."""
    reasoning: str = ""


PROMOTE_SYSTEM = (
    "You are the scribe for a scriptorium knowledge base deciding whether a "
    "freshly compiled page duplicates an existing one. You are given the candidate "
    "page and a short, pre-scored list of the most overlapping existing pages.\n"
    "- Choose `merge` (with `target_id` = the existing page it duplicates) only if "
    "they are genuinely the same topic and the candidate adds nothing a reader "
    "would want as a separate page.\n"
    "- Otherwise choose `keep` (the candidate stands as its own page).\n"
    "Decide only over the candidates given; do not invent ids."
)


def build_promote_prompt(candidate_text: str, candidates: list[dict]) -> str:
    listing = "\n".join(
        f"- {c['id']}  (combined={c['scores']['combined']:.2f}, "
        f"sources={c['scores']['sources']:.2f}, title={c['scores']['title']:.2f})"
        f"  \"{c['title']}\""
        for c in candidates
    )
    return (
        "Decide whether to merge this candidate page into one of the existing "
        "pages, or keep it separate.\n\n----- CANDIDATE PAGE -----\n"
        f"{candidate_text}\n\n----- EXISTING PAGES (most overlapping first) -----\n"
        f"{listing}"
    )

"""Deterministic pieces of the ANSWER loop: evidence formatting, structured
answer schema, and prompt construction. No network and no scrip subprocesses
here; runner.py owns orchestration and verification."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ANSWER_SYSTEM = (
    "You are the scribe for a scriptorium knowledge base answering a user's "
    "question from bounded evidence.\n"
    "Rules:\n"
    "- Use only the evidence provided. If it is insufficient, say what is missing.\n"
    "- Every factual sentence must carry a footnote marker ([^a1], [^a2], ...) "
    "whose citation record points to either an existing claim id or a raw source "
    "quote copied verbatim from the evidence.\n"
    "- Return one citation record for every marker, in the same order. In citation "
    "records, `marker` is the bare label (`a1`), not the markdown wrapper (`[^a1]`).\n"
    "- For raw citations, copy a complete contiguous quote, not a truncated snippet. "
    "Avoid generic table headers; quote enough source words to be unique.\n"
    "- Keep the body free of footnote definitions; the harness mints and appends "
    "verified definitions after your draft.\n"
    "- Do not cite wiki pages directly. They are context; final citations must be "
    "claim ids or raw quotes."
)


class AnswerCitation(BaseModel):
    marker: str
    """Footnote marker label, e.g. a1."""
    kind: Literal["claim", "raw"]
    claim_id: str = ""
    """Existing claim id when kind == claim."""
    source_id: str = ""
    """Raw source id when kind == raw, e.g. raw/paper."""
    quote: str = ""
    """Verbatim raw-source quote when kind == raw."""

    @field_validator("marker")
    @classmethod
    def normalize_marker(cls, value: str) -> str:
        value = value.strip()
        m = re.fullmatch(r"\[\^([^\]]+)\]", value)
        return m.group(1) if m else value


class DraftAnswer(BaseModel):
    body: str
    """Markdown answer body containing footnote markers [^a1], [^a2], ..."""
    citations: list[AnswerCitation] = Field(default_factory=list)


def _compact_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def build_answer_prompt(question: str, evidence: dict) -> str:
    """Prompt the model with a compact, explicit evidence packet."""
    return (
        "Answer the question using only this evidence packet. Cite every factual "
        "sentence with [^a1], [^a2], ... and return matching citation records. "
        "The citation record markers must be bare labels (`a1`, `a2`, ...). Raw "
        "citation quotes must be complete, contiguous, verbatim, and specific "
        "enough to resolve uniquely against the source.\n\n"
        f"QUESTION:\n{question}\n\n"
        "EVIDENCE JSON:\n"
        f"{_compact_json(evidence)}"
    )


_WORD = re.compile(r"\w+")


def tokenize(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)}


def overlap_score(question: str, text: str) -> int:
    q = tokenize(question)
    if not q:
        return 0
    return sum(1 for w in tokenize(text) if w in q)

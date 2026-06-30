"""Deterministic pieces of the model-assisted INGEST cleanup: the structured
schema and prompt for normalizing an extracted source into clean Markdown. No
network, no scrip — unit-testable.

Cleaning is **opt-in** (`scrip-harness ingest --clean`). It carries a provenance
trade-off: the cleaned text becomes `raw/<slug>`, so downstream anchors resolve
against the model's rendering, not the original bytes. The prompt therefore
insists the wording be preserved *verbatim* — the model may only drop boilerplate,
never paraphrase — so quote-anchoring stays meaningful."""

from __future__ import annotations

from pydantic import BaseModel

CLEAN_SYSTEM = (
    "You are preparing a fetched source for a scriptorium knowledge base. Return the "
    "source as clean Markdown, preserving its factual content while stripping cruft.\n"
    "Rules:\n"
    "- Preserve the prose **verbatim** — do not paraphrase, summarize, translate, "
    "reorder, or add anything not present in the source. Downstream claims are anchored "
    "to verbatim quotes in this text, so altered wording breaks provenance.\n"
    "- Remove navigation, menus, ads, cookie/consent banners, share/subscribe widgets, "
    "and repeated site headers/footers.\n"
    "- Keep headings, lists, tables, code blocks, and paragraph structure as Markdown.\n"
    "- Output only the cleaned Markdown — no commentary, no fences around the whole doc."
)


class DraftCleanSource(BaseModel):
    markdown: str
    """The source normalized to clean Markdown, factual prose preserved verbatim."""


def build_clean_prompt(source_text: str) -> str:
    return (
        "Clean the source below into Markdown per the rules, preserving the wording "
        "verbatim.\n\n----- SOURCE -----\n" + source_text
    )

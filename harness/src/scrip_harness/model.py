"""The only LLM-touching module. ``scrip`` never imports this; the harness does.

Uses the Anthropic SDK's structured-output parse helper so the draft comes back
as a validated ``DraftPage`` rather than free text to scrape.
"""

from __future__ import annotations

from .compile import SYSTEM, DraftPage, build_user_prompt
from .extract import (
    EXTRACT_SYSTEM,
    DraftExtraction,
    build_extract_prompt,
    build_retry_prompt,
)

DEFAULT_MODEL = "claude-opus-4-8"


def draft_page(
    source_text: str,
    *,
    source_id: str,
    model: str = DEFAULT_MODEL,
    client=None,
) -> DraftPage:
    """Ask Claude to synthesize a concept page from ``source_text``. Returns a
    validated :class:`DraftPage`. Lazily imports the SDK so the rest of the
    harness (and its tests) need no network or API key."""
    import anthropic

    client = client or anthropic.Anthropic()
    resp = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM,
        messages=[{"role": "user", "content": build_user_prompt(source_text)}],
        output_format=DraftPage,
    )
    out = resp.parsed_output
    if out is None:
        raise RuntimeError(f"model returned no parseable draft for {source_id}")
    return out


def draft_extraction(
    source_text: str,
    *,
    source_id: str,
    model: str = DEFAULT_MODEL,
    client=None,
    failures: list[dict] | None = None,
) -> DraftExtraction:
    """Ask Claude to extract structured claims from ``source_text``. With
    ``failures`` (the per-record findings from ``scrip fact add``), asks instead
    for one replacement claim per failure, in order — the retry half of the
    extract loop. Lazily imports the SDK so tests need no network or API key."""
    import anthropic

    client = client or anthropic.Anthropic()
    prompt = (
        build_extract_prompt(source_text)
        if failures is None
        else build_retry_prompt(source_text, failures)
    )
    resp = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=DraftExtraction,
    )
    out = resp.parsed_output
    if out is None:
        raise RuntimeError(f"model returned no parseable extraction for {source_id}")
    return out

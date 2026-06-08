"""The only LLM-touching module. ``scrip`` never imports this; the harness does.

Uses the Anthropic SDK's structured-output parse helper so the draft comes back
as a validated ``DraftPage`` rather than free text to scrape.
"""

from __future__ import annotations

from .compile import SYSTEM, DraftPage, build_user_prompt

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

"""The only LLM-touching module. ``scrip`` never imports this; the harness does.

The runner passes structured-output schemas from the deterministic prompt modules
below. This module adapts them to supported providers and returns validated
Pydantic objects, so the rest of the harness never scrapes free text.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .answer import ANSWER_SYSTEM, DraftAnswer, build_answer_prompt
from .compile import (
    SYSTEM,
    DraftPage,
    build_compile_retry_prompt,
    build_user_prompt,
)
from .extract import (
    EXTRACT_SYSTEM,
    DraftExtraction,
    build_extract_prompt,
    build_extract_retry_prompt,
)
from .graph import GRAPH_SYSTEM, DraftGraph, build_graph_prompt
from .ingest import CLEAN_SYSTEM, DraftCleanSource, build_clean_prompt
from .promote import PROMOTE_SYSTEM, PromotionDecision, build_promote_prompt
from .reconcile import RECONCILE_SYSTEM, ReconciliationDecision, build_reconcile_prompt

Provider = Literal["auto", "anthropic", "openai", "gemini"]

DEFAULT_PROVIDER: Provider = "auto"
DEFAULT_MODELS = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-5.5",
    "gemini": "gemini-3.5-flash",
}
# Kept for callers/tests that imported the historical Claude default.
DEFAULT_MODEL = DEFAULT_MODELS["anthropic"]

_OPENAI_URL = "https://api.openai.com/v1/responses"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"


class ModelConfigError(RuntimeError):
    """Provider/key configuration is missing or invalid."""


def _schema_name(output_format: type[BaseModel]) -> str:
    return output_format.__name__


def _json_schema(output_format: type[BaseModel], *, strict_openai: bool) -> dict[str, Any]:
    schema = output_format.model_json_schema()
    if strict_openai:
        _make_openai_strict(schema)
    return schema


def _make_openai_strict(node: Any) -> None:
    """OpenAI strict structured outputs require closed objects. Pydantic models
    with defaulted fields omit them from ``required``; require every property so
    provider output remains directly parseable by the target Pydantic model."""
    if isinstance(node, dict):
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            props = node["properties"]
            node["additionalProperties"] = False
            node["required"] = list(props)
        for value in node.values():
            _make_openai_strict(value)
    elif isinstance(node, list):
        for value in node:
            _make_openai_strict(value)


def _load_key_from_file(path: Path) -> str | None:
    try:
        text = path.expanduser().read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            _, line = line.split("=", 1)
            line = line.strip()
        if (line.startswith('"') and line.endswith('"')) or (
            line.startswith("'") and line.endswith("'")
        ):
            line = line[1:-1].strip()
        if line:
            return line
    return None


def _key_files(provider: str, explicit: str | None) -> list[Path]:
    if explicit:
        paths = [Path(explicit).expanduser()]
    elif provider == "openai":
        paths = [
            Path(p).expanduser()
            for p in (
                os.environ.get("SCRIP_HARNESS_OPENAI_API_KEY_FILE"),
                os.environ.get("OPENAI_API_KEY_FILE"),
                "~/veed/var/openai",
            )
            if p
        ]
    elif provider == "gemini":
        paths = [
            Path(p).expanduser()
            for p in (
                os.environ.get("SCRIP_HARNESS_GEMINI_API_KEY_FILE"),
                os.environ.get("GEMINI_API_KEY_FILE"),
                os.environ.get("GOOGLE_API_KEY_FILE"),
                "~/veed/var/gemini",
            )
            if p
        ]
    else:
        paths = [
            Path(p).expanduser()
            for p in (
                os.environ.get("SCRIP_HARNESS_ANTHROPIC_API_KEY_FILE"),
                os.environ.get("ANTHROPIC_API_KEY_FILE"),
            )
            if p
        ]

    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            out.extend(p for p in sorted(path.iterdir()) if p.is_file())
        else:
            out.append(path)
    return out


def _api_key(provider: str, explicit_file: str | None = None) -> str | None:
    env_names = {
        "anthropic": ("ANTHROPIC_API_KEY",),
        "openai": ("OPENAI_API_KEY",),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    }[provider]
    for name in env_names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    for path in _key_files(provider, explicit_file):
        key = _load_key_from_file(path)
        if key:
            return key
    return None


def _resolve_provider(provider: Provider | None, explicit_file: str | None = None) -> str:
    requested = provider or os.environ.get("SCRIP_HARNESS_PROVIDER") or DEFAULT_PROVIDER
    if requested != "auto":
        if requested not in DEFAULT_MODELS:
            raise ModelConfigError(
                f"unknown provider {requested!r}; choose anthropic, openai, gemini, or auto"
            )
        return requested
    if explicit_file:
        raise ModelConfigError("--api-key-file needs an explicit --provider")

    for candidate in ("anthropic", "openai", "gemini"):
        if _api_key(candidate, explicit_file):
            return candidate
    raise ModelConfigError(
        "no provider API key found. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, "
        "GEMINI_API_KEY/GOOGLE_API_KEY, or pass --provider and --api-key-file"
    )


def _resolve_model(provider: str, model: str | None) -> str:
    if model:
        return model
    env_name = f"SCRIP_HARNESS_{provider.upper()}_MODEL"
    return os.environ.get(env_name) or DEFAULT_MODELS[provider]


def _http_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout: int | None = None,
) -> dict[str, Any]:
    if timeout is None:
        timeout = _http_timeout()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"provider API error HTTP {e.code}: {_redact(detail)}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"provider API request failed: {e}") from e
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"provider returned non-JSON response: {body[:500]}") from e
    if not isinstance(parsed, dict):
        raise RuntimeError("provider returned a non-object JSON response")
    return parsed


def _http_timeout() -> int:
    raw = os.environ.get("SCRIP_HARNESS_HTTP_TIMEOUT")
    if not raw:
        return 180
    try:
        timeout = int(raw)
    except ValueError as e:
        raise ModelConfigError("SCRIP_HARNESS_HTTP_TIMEOUT must be an integer") from e
    if timeout <= 0:
        raise ModelConfigError("SCRIP_HARNESS_HTTP_TIMEOUT must be positive")
    return timeout


def _redact(text: str) -> str:
    for prefix in ("sk-", "sk-proj-", "AIza"):
        idx = text.find(prefix)
        if idx >= 0:
            end = idx
            while end < len(text) and not text[end].isspace() and text[end] not in "\"'<>":
                end += 1
            text = text[:idx] + "***" + text[end:]
    return text


def _json_from_text(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        first_lf = text.find("\n")
        first_cr = text.find("\r")
        if first_lf == -1:
            start_idx = first_cr
        elif first_cr == -1:
            start_idx = first_lf
        else:
            start_idx = min(first_lf, first_cr)

        if start_idx != -1:
            start = start_idx + 1
            if text[start_idx] == "\r" and start < len(text) and text[start] == "\n":
                start += 1
            text = text[start:]
        else:
            text = ""

        end_idx = max(text.rfind("\n"), text.rfind("\r"))
        if end_idx != -1:
            if text[end_idx + 1:].strip() == "```":
                text = text[:end_idx]
        else:
            if text.strip() == "```":
                text = ""

        text = text.strip()
    return json.loads(text)


def _extract_openai_json(resp: dict[str, Any]) -> Any:
    if resp.get("status") == "incomplete":
        raise RuntimeError(f"OpenAI response incomplete: {resp.get('incomplete_details')}")
    if resp.get("error"):
        raise RuntimeError(f"OpenAI response error: {resp['error']}")
    if isinstance(resp.get("output_text"), str):
        return _json_from_text(resp["output_text"])
    for item in resp.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            if isinstance(content.get("text"), str):
                return _json_from_text(content["text"])
    raise RuntimeError("OpenAI response did not contain output text")


def _walk_strings(obj: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, dict):
        for key in ("output_text", "text"):
            value = obj.get(key)
            if isinstance(value, str):
                strings.append(value)
        for value in obj.values():
            strings.extend(_walk_strings(value))
    elif isinstance(obj, list):
        for value in obj:
            strings.extend(_walk_strings(value))
    return strings


def _extract_gemini_json(resp: dict[str, Any], output_format: type[BaseModel]) -> Any:
    try:
        output_format.model_validate(resp)
        return resp
    except Exception:
        pass
    for text in _walk_strings(resp):
        try:
            return _json_from_text(text)
        except json.JSONDecodeError:
            continue
    raise RuntimeError("Gemini response did not contain parseable structured output")


def _anthropic_structured(
    system: str,
    prompt: str,
    output_format: type[BaseModel],
    *,
    model: str,
    max_tokens: int,
    client=None,
    api_key: str | None = None,
) -> BaseModel:
    import anthropic

    client = client or (
        anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    )
    resp = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=output_format,
    )
    out = resp.parsed_output
    if out is None:
        raise RuntimeError("model returned no parseable structured output")
    return out


def _openai_structured(
    system: str,
    prompt: str,
    output_format: type[BaseModel],
    *,
    model: str,
    max_tokens: int,
    api_key: str,
) -> BaseModel:
    schema = _json_schema(output_format, strict_openai=True)
    resp = _http_json(
        _OPENAI_URL,
        {
            "model": model,
            "instructions": system,
            "input": prompt,
            "max_output_tokens": max_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _schema_name(output_format),
                    "schema": schema,
                    "strict": True,
                }
            },
        },
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    return output_format.model_validate(_extract_openai_json(resp))


def _gemini_structured(
    system: str,
    prompt: str,
    output_format: type[BaseModel],
    *,
    model: str,
    api_key: str,
) -> BaseModel:
    schema = _json_schema(output_format, strict_openai=False)
    resp = _http_json(
        _GEMINI_URL,
        {
            "model": model,
            "system_instruction": system,
            "input": prompt,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            },
        },
        {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
    )
    return output_format.model_validate(_extract_gemini_json(resp, output_format))


def _complete_structured(
    system: str,
    prompt: str,
    output_format: type[BaseModel],
    *,
    provider: Provider | None,
    model: str | None,
    max_tokens: int,
    client=None,
    api_key_file: str | None = None,
) -> BaseModel:
    # Historical unit tests inject an Anthropic-shaped fake client. Preserve that
    # seam unless a provider is explicitly selected.
    if client is not None and (provider is None or provider == "auto"):
        chosen_provider = "anthropic"
    else:
        chosen_provider = _resolve_provider(provider, api_key_file)
    chosen_model = _resolve_model(chosen_provider, model)

    if chosen_provider == "anthropic":
        key = _api_key(chosen_provider, api_key_file)
        return _anthropic_structured(
            system,
            prompt,
            output_format,
            model=chosen_model,
            max_tokens=max_tokens,
            client=client,
            api_key=key,
        )

    key = _api_key(chosen_provider, api_key_file)
    if not key:
        raise ModelConfigError(
            f"no API key found for provider {chosen_provider!r}; set the provider env var "
            "or pass --api-key-file"
        )
    if chosen_provider == "openai":
        return _openai_structured(
            system,
            prompt,
            output_format,
            model=chosen_model,
            max_tokens=max_tokens,
            api_key=key,
        )
    if chosen_provider == "gemini":
        return _gemini_structured(
            system,
            prompt,
            output_format,
            model=chosen_model,
            api_key=key,
        )
    raise AssertionError(f"unhandled provider {chosen_provider!r}")


def draft_page(
    source_text: str,
    *,
    source_id: str,
    model: str | None = None,
    provider: Provider | None = None,
    client=None,
    failures: list[dict] | None = None,
    api_key_file: str | None = None,
) -> DraftPage:
    """Ask a model to synthesize a concept page from ``source_text``. Returns a
    validated :class:`DraftPage`. With ``failures`` (the per-claim anchor findings
    from the mint loop), asks instead for one corrected claim per failure, in
    order — the retry half of the compile loop."""
    prompt = (
        build_user_prompt(source_text)
        if failures is None
        else build_compile_retry_prompt(source_text, failures)
    )
    out = _complete_structured(
        SYSTEM,
        prompt,
        DraftPage,
        provider=provider,
        model=model,
        max_tokens=16000,
        client=client,
        api_key_file=api_key_file,
    )
    if not isinstance(out, DraftPage):
        raise RuntimeError(f"model returned wrong draft type for {source_id}")
    return out


def draft_extraction(
    source_text: str,
    *,
    source_id: str,
    model: str | None = None,
    provider: Provider | None = None,
    client=None,
    failures: list[dict] | None = None,
    api_key_file: str | None = None,
) -> DraftExtraction:
    """Ask a model to extract structured claims from ``source_text``. With
    ``failures`` (the per-record findings from ``scrip fact add``), asks instead
    for one replacement claim per failure, in order — the retry half of the
    extract loop."""
    prompt = (
        build_extract_prompt(source_text)
        if failures is None
        else build_extract_retry_prompt(source_text, failures)
    )
    out = _complete_structured(
        EXTRACT_SYSTEM,
        prompt,
        DraftExtraction,
        provider=provider,
        model=model,
        max_tokens=16000,
        client=client,
        api_key_file=api_key_file,
    )
    if not isinstance(out, DraftExtraction):
        raise RuntimeError(f"model returned wrong extraction type for {source_id}")
    return out


def draft_graph(
    source_text: str,
    *,
    source_id: str,
    model: str | None = None,
    provider: Provider | None = None,
    client=None,
    api_key_file: str | None = None,
) -> DraftGraph:
    """Ask a model to draft the entities and typed edges a source describes.
    Returns a validated :class:`DraftGraph`. Entities/edges carry no anchors, so
    there is no quote-retry loop — the runner drops dangling edges and skips
    unsluggable entities instead."""
    out = _complete_structured(
        GRAPH_SYSTEM,
        build_graph_prompt(source_text),
        DraftGraph,
        provider=provider,
        model=model,
        max_tokens=8000,
        client=client,
        api_key_file=api_key_file,
    )
    if not isinstance(out, DraftGraph):
        raise RuntimeError(f"model returned wrong graph type for {source_id}")
    return out


def clean_source(
    source_text: str,
    *,
    model: str | None = None,
    provider: Provider | None = None,
    client=None,
    api_key_file: str | None = None,
) -> str:
    """Ask a model to normalize an extracted source into clean Markdown, preserving
    its prose verbatim (so anchors minted later still resolve). Returns the cleaned
    Markdown. Opt-in via ``scrip-harness ingest --clean``; see :mod:`ingest`."""
    out = _complete_structured(
        CLEAN_SYSTEM,
        build_clean_prompt(source_text),
        DraftCleanSource,
        provider=provider,
        model=model,
        max_tokens=8000,
        client=client,
        api_key_file=api_key_file,
    )
    if not isinstance(out, DraftCleanSource):
        raise RuntimeError("model returned wrong type for source cleaning")
    return out.markdown


def decide_promotion(
    candidate_text: str,
    candidates: list[dict],
    *,
    model: str | None = None,
    provider: Provider | None = None,
    client=None,
    api_key_file: str | None = None,
) -> PromotionDecision:
    """Ask whether a candidate page duplicates one of the pre-scored existing
    pages (merge into it) or should stand alone (keep)."""
    out = _complete_structured(
        PROMOTE_SYSTEM,
        build_promote_prompt(candidate_text, candidates),
        PromotionDecision,
        provider=provider,
        model=model,
        max_tokens=2000,
        client=client,
        api_key_file=api_key_file,
    )
    if not isinstance(out, PromotionDecision):
        raise RuntimeError("model returned wrong promotion decision type")
    return out


def decide_reconciliation(
    pair: dict,
    span_a: str | None,
    span_b: str | None,
    *,
    model: str | None = None,
    provider: Provider | None = None,
    client=None,
    api_key_file: str | None = None,
) -> ReconciliationDecision:
    """Ask a model to adjudicate one contradiction pair from its cited spans."""
    out = _complete_structured(
        RECONCILE_SYSTEM,
        build_reconcile_prompt(pair, span_a, span_b),
        ReconciliationDecision,
        provider=provider,
        model=model,
        max_tokens=2000,
        client=client,
        api_key_file=api_key_file,
    )
    if not isinstance(out, ReconciliationDecision):
        raise RuntimeError("model returned wrong reconciliation decision type")
    return out


def draft_answer(
    question: str,
    *,
    evidence: dict,
    model: str | None = None,
    provider: Provider | None = None,
    client=None,
    api_key_file: str | None = None,
) -> DraftAnswer:
    """Ask a model to answer from a bounded evidence packet."""
    out = _complete_structured(
        ANSWER_SYSTEM,
        build_answer_prompt(question, evidence),
        DraftAnswer,
        provider=provider,
        model=model,
        max_tokens=6000,
        client=client,
        api_key_file=api_key_file,
    )
    if not isinstance(out, DraftAnswer):
        raise RuntimeError("model returned wrong answer type")
    return out

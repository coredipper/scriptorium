"""model.py wiring tests — no network. A fake Anthropic client captures the
prompt so we can assert each retry path picks the RIGHT prompt. COMPILE and
EXTRACT each have their own retry-prompt builder (`build_compile_retry_prompt` /
`build_extract_retry_prompt`); a name collision once mis-wired `draft_page` to
EXTRACT's prompt (which invites dropping claims), violating COMPILE's
positional-marker contract. These tests guard that boundary."""

import json

from scrip_harness import model as model_mod
from scrip_harness.answer import DraftAnswer
from scrip_harness.compile import DraftClaim, DraftPage
from scrip_harness.extract import DraftExtraction, DraftFact
from scrip_harness.promote import PromotionDecision


class _CapturingClient:
    """Stands in for `anthropic.Anthropic()`; records the user prompt and returns
    a pre-baked parsed_output so no network/SDK is needed."""

    def __init__(self, parsed_output):
        self._parsed = parsed_output
        self.captured: dict = {}

    @property
    def messages(self):
        return self

    def parse(self, *, messages, **kw):
        self.captured["prompt"] = messages[0]["content"]
        return type("Resp", (), {"parsed_output": self._parsed})()


def test_draft_page_retry_uses_the_compile_prompt_not_extracts():
    client = _CapturingClient(
        DraftPage(title="t", body="x[^a1]\n", claims=[DraftClaim(quote="q")])
    )
    failures = [{"index": 0, "status": "AMBIGUOUS", "quote": "alpha beta", "detail": ""}]
    model_mod.draft_page(
        "a distinctive source body", source_id="raw/s", client=client, failures=failures
    )
    prompt = client.captured["prompt"]
    assert "a distinctive source body" in prompt and "AMBIGUOUS" in prompt
    # COMPILE keeps every claim (markers are positional) — the retry prompt must
    # NOT offer drop-via-empty-quote the way EXTRACT's does.
    assert "drop" not in prompt.lower() and "empty" not in prompt.lower()


def test_draft_extraction_retry_uses_the_extract_prompt():
    client = _CapturingClient(
        DraftExtraction(claims=[DraftFact(quote="q", subject="s", predicate="p", object="o")])
    )
    failures = [{"index": 0, "status": "BROKEN", "quote": "x", "detail": ""}]
    model_mod.draft_extraction(
        "a distinctive source body", source_id="raw/s", client=client, failures=failures
    )
    prompt = client.captured["prompt"]
    # EXTRACT facts are position-independent: an empty quote may drop a claim.
    assert "empty" in prompt.lower() and "drop" in prompt.lower()


def test_auto_provider_uses_default_openai_key_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    key_file = tmp_path / "openai"
    key_file.write_text("sk-test\n", encoding="utf-8")
    monkeypatch.setattr(
        model_mod,
        "_key_files",
        lambda provider, explicit: [key_file] if provider == "openai" else [],
    )

    assert model_mod._resolve_provider("auto") == "openai"


def test_auto_provider_rejects_explicit_key_file_without_provider(tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("sk-test\n", encoding="utf-8")

    try:
        model_mod._resolve_provider("auto", str(key_file))
    except model_mod.ModelConfigError as e:
        assert "--api-key-file needs an explicit --provider" in str(e)
    else:
        raise AssertionError("expected ModelConfigError")


def test_openai_provider_posts_responses_structured_output(monkeypatch):
    captured: dict = {}

    def fake_http_json(url, payload, headers, *, timeout=180):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return {
            "status": "completed",
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({"body": "Answer.", "citations": []}),
                        }
                    ]
                }
            ],
        }

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(model_mod, "_http_json", fake_http_json)

    out = model_mod.draft_answer(
        "question", evidence={}, provider="openai", model="gpt-test"
    )

    assert isinstance(out, DraftAnswer)
    assert captured["url"].endswith("/v1/responses")
    assert captured["payload"]["model"] == "gpt-test"
    fmt = captured["payload"]["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


def test_gemini_provider_posts_interactions_structured_output(monkeypatch):
    captured: dict = {}

    def fake_http_json(url, payload, headers, *, timeout=180):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return {
            "output_text": json.dumps(
                {"decision": "keep", "target_id": None, "reasoning": "distinct"}
            )
        }

    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")
    monkeypatch.setattr(model_mod, "_http_json", fake_http_json)

    out = model_mod.decide_promotion(
        "candidate", [], provider="gemini", model="gemini-test"
    )

    assert isinstance(out, PromotionDecision)
    assert captured["url"].endswith("/v1beta/interactions")
    assert captured["payload"]["model"] == "gemini-test"
    assert "system_instruction" in captured["payload"]
    fmt = captured["payload"]["response_format"]
    assert fmt["mime_type"] == "application/json"
    assert fmt["schema"]["type"] == "object"
    assert captured["headers"]["x-goog-api-key"] == "gem-test"

"""model.py wiring tests — no network. A fake Anthropic client captures the
prompt so we can assert each retry path picks the RIGHT prompt. COMPILE and
EXTRACT both export a `build_retry_prompt`; a name collision once mis-wired
`draft_page` to EXTRACT's prompt (which invites dropping claims), violating
COMPILE's positional-marker contract. These tests guard that boundary."""

from scrip_harness import model as model_mod
from scrip_harness.compile import DraftClaim, DraftPage
from scrip_harness.extract import DraftExtraction, DraftFact


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

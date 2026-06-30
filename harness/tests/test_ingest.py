"""INGEST orchestration: `scrip-harness ingest` drives `scrip ingest` then chains
COMPILE -> EXTRACT -> GRAPH (bounded by --through), with an opt-in --clean step
that rewrites raw/<slug> with model-cleaned Markdown. The stage runners have their
own suites, so here they are stubbed and we assert the orchestration itself. Real
`scrip ingest`; no network."""

import pytest
from scrip_harness import runner as runner_mod
from scrip_harness.runner import IngestError, ingest_source


def _vault(tmp_path):
    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "SPEC.md").write_text("marker\n", encoding="utf-8")
    return tmp_path


def _stub_stages(monkeypatch):
    """Replace the stage runners with recorders; return the ordered call log."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        runner_mod, "compile_page",
        lambda root, slug, **kw: calls.append(("compile", slug)),
    )
    monkeypatch.setattr(
        runner_mod, "extract_facts",
        lambda root, slug, **kw: (calls.append(("extract", slug)),
                                  {"appended": [], "skipped": [], "contradictions": []})[1],
    )
    monkeypatch.setattr(
        runner_mod, "draft_graph_facts",
        lambda root, slug, **kw: (calls.append(("graph", slug)),
                                  {"entities": {"appended": []}, "edges": {"appended": []},
                                   "dropped_edges": [], "degraded_edges": [],
                                   "skipped_entities": []})[1],
    )
    return calls


def _noop(*a, **k):
    # the stage runners are stubbed in these tests, so the draft fns they would
    # receive are never invoked; raising documents (and types as NoReturn) that.
    raise AssertionError("draft fn must not be called when stage runners are stubbed")


def test_ingest_orchestrates_ingest_then_compile_extract_graph(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    src = tmp_path / "doc.md"
    src.write_text("# Topic\n\nReal body about a thing.\n", encoding="utf-8")
    calls = _stub_stages(monkeypatch)

    result = ingest_source(
        root, str(src), slug="doc",
        compile_draft_fn=_noop, extract_draft_fn=_noop, graph_draft_fn=_noop,
    )
    assert (root / "vault" / "raw" / "doc.md").exists()  # the source landed
    assert result["slug"] == "doc"
    assert result["stages"] == ["ingest", "compile", "extract", "graph"]
    assert calls == [("compile", "doc"), ("extract", "doc"), ("graph", "doc")]


def test_ingest_derives_slug_from_source_when_not_given(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    src = tmp_path / "my-note.md"
    src.write_text("# N\n\nBody.\n", encoding="utf-8")
    _stub_stages(monkeypatch)

    result = ingest_source(
        root, str(src), through="ingest",
        compile_draft_fn=_noop, extract_draft_fn=_noop, graph_draft_fn=_noop,
    )
    assert result["slug"] == "my-note"
    assert (root / "vault" / "raw" / "my-note.md").exists()


def test_ingest_through_bounds_the_pipeline(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    src = tmp_path / "doc.md"
    src.write_text("# Topic\n\nReal body.\n", encoding="utf-8")
    calls = _stub_stages(monkeypatch)

    result = ingest_source(
        root, str(src), slug="doc", through="compile",
        compile_draft_fn=_noop, extract_draft_fn=_noop, graph_draft_fn=_noop,
    )
    assert result["stages"] == ["ingest", "compile"]
    assert calls == [("compile", "doc")]  # extract/graph were NOT run


def test_ingest_clean_rewrites_raw_with_cleaned_markdown(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    src = tmp_path / "doc.md"
    src.write_text("Nav | Menu | Junk\n\nThe real content sentence.\n", encoding="utf-8")
    _stub_stages(monkeypatch)

    def fake_clean(text):
        assert "real content sentence" in text  # receives the extracted source text
        return "# Doc\n\nThe real content sentence.\n"

    result = ingest_source(
        root, str(src), slug="doc", clean=True, through="ingest",
        clean_fn=fake_clean,
        compile_draft_fn=_noop, extract_draft_fn=_noop, graph_draft_fn=_noop,
    )
    raw = (root / "vault" / "raw" / "doc.md").read_text(encoding="utf-8")
    assert "# Doc" in raw and "Nav | Menu | Junk" not in raw  # cleaned text replaced raw
    assert result["cleaned"] is True
    assert result["stages"] == ["ingest"]


def test_ingest_clean_without_clean_fn_is_an_error(tmp_path):
    root = _vault(tmp_path)
    src = tmp_path / "doc.md"
    src.write_text("# D\n\nBody.\n", encoding="utf-8")
    with pytest.raises(IngestError):
        ingest_source(root, str(src), slug="doc", clean=True, through="ingest")


def test_ingest_rejects_unknown_through_stage(tmp_path):
    root = _vault(tmp_path)
    src = tmp_path / "doc.md"
    src.write_text("# D\n\nBody.\n", encoding="utf-8")
    with pytest.raises(IngestError):
        ingest_source(root, str(src), slug="doc", through="reconcile",
                      compile_draft_fn=_noop, extract_draft_fn=_noop, graph_draft_fn=_noop)

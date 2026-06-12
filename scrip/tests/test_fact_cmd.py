"""`scrip fact add` — validated, locked writer for the facts/ layer. The model
proposes records (claims carry a verbatim quote); scrip mints+verifies anchors,
owns ids/timestamps, and appends all-or-nothing. Deterministic, no model."""

import io
import json
import re

from scrip import anchors, cli, lock

SRC = (
    "# H\n\n"
    "The quick brown fox jumps over the lazy dog.\n\n"
    "Caching answers beats recomputing them.\n"
)

ISO_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _claim(quote, source="raw/s", **kw):
    rec = {
        "quote": quote,
        "source_id": source,
        "subject": "s",
        "predicate": "p",
        "object": "o",
        "polarity": "asserts",
        "confidence": 0.9,
    }
    rec.update(kw)
    return rec


def _ndjson(*recs):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)


def _run_add(kb, text, *extra):
    p = kb.root / "in.ndjson"
    p.write_text(text, encoding="utf-8")
    return cli.main(["fact", "add", "--file", str(p), "--root", str(kb.root), *extra])


def _claims_lines(kb):
    p = kb.root / "vault" / "facts" / "claims.ndjson"
    if not p.exists():
        return []
    return [json.loads(s) for s in p.read_text(encoding="utf-8").splitlines() if s.strip()]


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_fact_add_appends_claims_with_minted_anchor_and_ids(kb):
    kb.add_raw("s", SRC)
    rc = _run_add(
        kb,
        _ndjson(
            _claim("The quick brown fox jumps over the lazy dog."),
            _claim(
                "Caching answers beats recomputing them.",
                claim_text="Caching beats recomputation.",
                tags=["caching"],
            ),
        ),
    )
    assert rc == 0
    recs = _claims_lines(kb)
    assert [r["claim_id"] for r in recs] == ["clm_0001", "clm_0002"]
    for r in recs:
        # the minted anchor must actually resolve uniquely in the source
        assert anchors.resolve(SRC, r["anchor"]) == "OK"
        assert ISO_Z.fullmatch(r["extracted_at"])
        assert r["source_id"] == "raw/s"
    # claim_text defaults to the quote when omitted; explicit value is kept
    assert recs[0]["claim_text"] == "The quick brown fox jumps over the lazy dog."
    assert recs[1]["claim_text"] == "Caching beats recomputation."
    assert recs[1]["tags"] == ["caching"]


def test_fact_add_continues_existing_id_sequence(kb):
    kb.add_raw("s", SRC)
    kb.add_claim("clm_0001", "s", "The quick brown fox jumps over the lazy dog.")
    kb.add_claim("clm_0007", "s", "Caching answers beats recomputing them.")
    rc = _run_add(
        kb, _ndjson(_claim("The quick brown fox jumps over the lazy dog.", subject="s2"))
    )
    assert rc == 0
    assert _claims_lines(kb)[-1]["claim_id"] == "clm_0008"


def test_fact_add_reads_stdin(kb, monkeypatch):
    kb.add_raw("s", SRC)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(_ndjson(_claim("The quick brown fox jumps over the lazy dog."))),
    )
    rc = cli.main(["fact", "add", "--stdin", "--root", str(kb.root)])
    assert rc == 0
    assert len(_claims_lines(kb)) == 1


def test_fact_add_json_reports_appended_records(kb, capsys):
    kb.add_raw("s", SRC)
    rc = _run_add(
        kb, _ndjson(_claim("The quick brown fox jumps over the lazy dog.")), "--json"
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["table"] == "claims"
    assert data["failures"] == []
    assert data["skipped"] == []
    [rec] = data["appended"]
    assert rec["claim_id"] == "clm_0001"
    assert rec["anchor"].startswith("qh:")


# --------------------------------------------------------------------------- #
# All-or-nothing batch + per-record failures (exit 1)
# --------------------------------------------------------------------------- #
def test_fact_add_all_or_nothing_on_broken_quote(kb, capsys):
    kb.add_raw("s", SRC)
    rc = _run_add(
        kb,
        _ndjson(
            _claim("The quick brown fox jumps over the lazy dog."),
            _claim("this sentence is absent from the source"),
        ),
        "--json",
    )
    assert rc == 1
    # the good record was NOT appended: the batch is atomic
    assert _claims_lines(kb) == []
    data = json.loads(capsys.readouterr().out)
    assert data["appended"] == []
    [failure] = data["failures"]
    assert failure["index"] == 1
    assert failure["status"] == "BROKEN"
    assert failure["quote"] == "this sentence is absent from the source"


def test_fact_add_ambiguous_quote_fails(kb, capsys):
    kb.add_raw("s", "alpha beta. alpha beta.\n")
    rc = _run_add(kb, _ndjson(_claim("alpha beta.")), "--json")
    assert rc == 1
    assert _claims_lines(kb) == []
    [failure] = json.loads(capsys.readouterr().out)["failures"]
    assert failure["status"] == "AMBIGUOUS"


def test_fact_add_missing_source_fails_batch(kb, capsys):
    kb.add_raw("s", SRC)
    rc = _run_add(kb, _ndjson(_claim("anything", source="raw/nope")), "--json")
    assert rc == 1
    assert _claims_lines(kb) == []
    [failure] = json.loads(capsys.readouterr().out)["failures"]
    assert failure["status"] == "MISSING_SOURCE"
    assert failure["source_id"] == "raw/nope"


def test_fact_add_unsafe_source_id_fails_batch(kb, capsys):
    kb.add_raw("s", SRC)
    rc = _run_add(kb, _ndjson(_claim("anything", source="../../etc/passwd")), "--json")
    assert rc == 1
    assert _claims_lines(kb) == []
    [failure] = json.loads(capsys.readouterr().out)["failures"]
    assert failure["status"] == "INVALID_SOURCE"


def test_fact_add_empty_quote_fails_batch(kb, capsys):
    kb.add_raw("s", SRC)
    rc = _run_add(kb, _ndjson(_claim("   ")), "--json")
    assert rc == 1
    [failure] = json.loads(capsys.readouterr().out)["failures"]
    assert failure["status"] == "EMPTY_QUOTE"


# --------------------------------------------------------------------------- #
# Idempotence: exact duplicates are skipped, not re-appended
# --------------------------------------------------------------------------- #
def test_fact_add_skips_exact_duplicates(kb, capsys):
    kb.add_raw("s", SRC)
    proposal = _ndjson(_claim("The quick brown fox jumps over the lazy dog."))
    assert _run_add(kb, proposal) == 0
    capsys.readouterr()  # drain the first run's human-format output
    rc = _run_add(kb, proposal, "--json")
    assert rc == 0
    assert len(_claims_lines(kb)) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["appended"] == []
    [skip] = data["skipped"]
    assert skip["reason"] == "duplicate"
    assert skip["existing_id"] == "clm_0001"


# --------------------------------------------------------------------------- #
# facts/_meta.yaml: derived-from merged, but NOT stamped (honest staleness)
# --------------------------------------------------------------------------- #
def test_fact_add_merges_meta_derived_from_without_stamping(kb):
    import yaml

    kb.add_raw("s", SRC)
    kb.add_raw("t", "# T\n\nA wholly different second source.\n")
    assert _run_add(kb, _ndjson(_claim("The quick brown fox jumps over the lazy dog."))) == 0

    meta_path = kb.root / "vault" / "facts" / "_meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    assert meta["id"] == "facts/core"
    assert meta["derived-from"] == ["raw/s"]
    assert "input-hash" not in meta  # fact add never stamps

    # the facts set is STALE until the caller stamps it — the honest state
    assert cli.main(["status", "--root", str(kb.root)]) == 1
    assert cli.main(["stamp", str(meta_path), "--root", str(kb.root)]) == 0
    assert cli.main(["status", "--root", str(kb.root)]) == 0

    # a second add from a new source merges derived-from without duplicates
    assert _run_add(kb, _ndjson(_claim("A wholly different second source.", source="raw/t"))) == 0
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    assert meta["derived-from"] == ["raw/s", "raw/t"]


def test_fact_add_malformed_meta_appends_nothing(kb):
    """A malformed _meta.yaml must fail the whole add BEFORE claims land —
    otherwise claims would exist whose source is missing from derived-from,
    and the facts set would report OK while silently under-declaring deps."""
    kb.add_raw("s", SRC)
    meta_path = kb.root / "vault" / "facts" / "_meta.yaml"
    meta_path.write_text("id: [unclosed\n", encoding="utf-8")
    rc = _run_add(kb, _ndjson(_claim("The quick brown fox jumps over the lazy dog.")))
    assert rc == 3
    assert _claims_lines(kb) == []


# --------------------------------------------------------------------------- #
# Structural input errors (exit 3) and usage errors (exit 2)
# --------------------------------------------------------------------------- #
def test_fact_add_rejects_scrip_owned_fields(kb):
    kb.add_raw("s", SRC)
    rc = _run_add(kb, _ndjson(_claim("anything", claim_id="clm_9999")))
    assert rc == 3
    rc = _run_add(kb, _ndjson(_claim("anything", anchor="qh:beef|loc:0|len:8")))
    assert rc == 3
    assert _claims_lines(kb) == []


def test_fact_add_rejects_unknown_and_invalid_fields(kb):
    kb.add_raw("s", SRC)
    assert _run_add(kb, _ndjson(_claim("anything", wibble=1))) == 3
    assert _run_add(kb, _ndjson(_claim("anything", polarity="shouts"))) == 3
    assert _run_add(kb, _ndjson(_claim("anything", confidence=1.5))) == 3
    missing = {"quote": "anything", "source_id": "raw/s"}  # no triple/polarity/confidence
    assert _run_add(kb, _ndjson(missing)) == 3


def test_fact_add_bad_json_is_data_error(kb):
    kb.add_raw("s", SRC)
    assert _run_add(kb, "{not json}\n") == 3


def test_fact_add_empty_input_is_usage_error(kb):
    kb.add_raw("s", SRC)
    assert _run_add(kb, "\n\n") == 2


def test_fact_add_unreadable_file_is_usage_error(kb):
    assert (
        cli.main(["fact", "add", "--file", str(kb.root / "absent.ndjson"), "--root", str(kb.root)])
        == 2
    )


# --------------------------------------------------------------------------- #
# Locking
# --------------------------------------------------------------------------- #
def test_fact_add_blocked_by_live_lock(kb):
    kb.add_raw("s", SRC)
    info = lock.acquire(kb.root)  # our own (live) pid holds the lock
    try:
        rc = _run_add(kb, _ndjson(_claim("The quick brown fox jumps over the lazy dog.")))
    finally:
        lock.release(kb.root, info)
    assert rc == 2
    assert _claims_lines(kb) == []


def test_fact_add_resolves_quotes_under_the_lock(kb):
    """Anchors must be minted/verified INSIDE the write lock — otherwise a
    concurrent `ingest --reingest` could rewrite the source between
    verification and append, landing claims whose anchors no longer resolve.
    Observable contract: with the lock held, even a bad quote is refused with
    the lock error (2), never reported as a quote finding (1)."""
    kb.add_raw("s", SRC)
    info = lock.acquire(kb.root)
    try:
        rc = _run_add(kb, _ndjson(_claim("this sentence is absent from the source")))
    finally:
        lock.release(kb.root, info)
    assert rc == 2


# --------------------------------------------------------------------------- #
# entities / edges tables: schema + id checks, no anchors
# --------------------------------------------------------------------------- #
def test_fact_add_entities_appends_and_conflicts(kb, capsys):
    ent = {"entity_id": "entity/duckdb", "name": "DuckDB", "kind": "system"}
    rc = _run_add(kb, _ndjson(ent), "--table", "entities")
    assert rc == 0
    lines = (kb.root / "vault" / "facts" / "entities.ndjson").read_text(encoding="utf-8")
    assert json.loads(lines.splitlines()[0])["entity_id"] == "entity/duckdb"

    # identical record is skipped; a conflicting one (same id, new name) fails
    assert _run_add(kb, _ndjson(ent), "--table", "entities") == 0
    conflicting = {"entity_id": "entity/duckdb", "name": "Duck DB", "kind": "system"}
    capsys.readouterr()  # drain the earlier runs' human-format output
    rc = _run_add(kb, _ndjson(conflicting), "--table", "entities", "--json")
    assert rc == 1
    [failure] = json.loads(capsys.readouterr().out)["failures"]
    assert failure["status"] == "ID_CONFLICT"
    assert len(lines.splitlines()) == 1  # nothing else was appended


def test_fact_add_edges_appends_and_skips_duplicates(kb):
    edge = {"src": "entity/duckdb", "dst": "entity/motherduck", "kind": "made-by"}
    assert _run_add(kb, _ndjson(edge), "--table", "edges") == 0
    assert _run_add(kb, _ndjson(edge), "--table", "edges") == 0
    lines = (kb.root / "vault" / "facts" / "graph.ndjson").read_text(encoding="utf-8")
    assert len(lines.splitlines()) == 1

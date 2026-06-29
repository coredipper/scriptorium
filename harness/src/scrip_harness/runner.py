"""Orchestrate the model-driven AGENT.md steps (COMPILE, EXTRACT, GRAPH, PROMOTE,
RECONCILE, ANSWER) — handing every verifiable step to ``scrip`` subprocesses.
``scrip`` stays the deterministic source of truth: this never re-implements
hashing, anchoring, staleness, or fact writing. The one narrow exception is the
GRAPH stage, which records ``raw/<slug>`` in ``facts/_meta.yaml`` ``derived-from``
(see :func:`_ensure_source_tracked`) — a provenance link the source-less
entity/edge schema cannot carry; scrip still computes the hash and decides
staleness from it."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from scrip import frontmatter  # reuse the deterministic frontmatter helper

from .answer import DraftAnswer, overlap_score, tokenize
from .compile import DraftPage, assemble_body, extract_markers, format_sources
from .extract import DraftExtraction, DraftFact, to_ndjson
from .graph import (
    DraftEdge,
    DraftEntity,
    DraftGraph,
    edges_to_ndjson,
    entities_to_ndjson,
    entity_id,
)
from .promote import PromotionDecision, merge_bodies
from .reconcile import ReconciliationDecision

DraftFn = Callable[..., DraftPage]
ExtractDraftFn = Callable[..., DraftExtraction]
GraphDraftFn = Callable[..., DraftGraph]  # (source_text, source_id=...) -> draft graph
DecideFn = Callable[..., PromotionDecision]  # (candidate_text, candidates) -> decision
ReconcileDecideFn = Callable[..., ReconciliationDecision]  # (pair, span_a, span_b) -> decision
AnswerDraftFn = Callable[..., DraftAnswer]  # (question, evidence=...) -> draft answer

# Drive scriptoria through the *running interpreter*, not a bare `scrip` on PATH:
# `uv tool install scrip-harness` installs scriptoria into the harness's own
# environment but only exposes the harness's entry point, so a PATH `scrip` may be
# missing or a different version. `-m scrip.cli` always runs the bundled one.
DEFAULT_SCRIP_CMD = (sys.executable, "-m", "scrip.cli")

# Same conservative shape scrip enforces — no path separators, '..', or leading dot.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class CompileError(RuntimeError):
    """A compile step failed (bad slug, marker mismatch, an unresolved quote, or a
    scrip command erred)."""


class ExtractError(RuntimeError):
    """An extract step failed (bad slug, quotes still failing after the bounded
    retries, or a scrip command erred)."""


class GraphError(RuntimeError):
    """A graph-drafting step failed (bad slug, missing source, an empty draft, or a
    scrip command erred). Entities/edges carry no anchors, so there is no
    quote-retry loop — a structurally bad record is a hard error, not a finding."""


class PromoteError(RuntimeError):
    """A promote step failed (missing page, a scrip command erred, or the middle
    band was reached with no decider)."""


class ReconcileError(RuntimeError):
    """A reconcile step failed (a scrip command erred, or the model returned an
    invalid decision such as supersede without a winner)."""


class AnswerError(RuntimeError):
    """An answer step failed (the vault is not green, evidence/citations are
    invalid, or the model returned unsupported citations)."""


def _scrip(
    cmd: Sequence[str], args: list[str], input_text: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*cmd, *args], capture_output=True, text=True, input=input_text
    )


def _read_sources(
    root: Path,
    slug: str,
    sources: Sequence[str] | None,
    error_cls: type[Exception],
) -> tuple[list[str], dict[str, str], str, str]:
    """Resolve and read the raw sources a COMPILE/EXTRACT draws from, shared by both.

    ``sources`` is a list of raw ids (``["raw/a", "raw/b"]``), defaulting to the
    single ``raw/<slug>``. Each is validated (``raw/`` prefix + slug shape) and read.
    Returns ``(source_ids, valid_sources, source_text, draft_source_id)``: with one
    source the prompt text is byte-identical to a single-source run; with several it
    is the labelled ``----- SOURCE <id> -----`` concatenation and ``draft_source_id``
    is the comma-joined ids, so the model can attribute each quote to its source."""
    source_ids = list(sources) if sources else [f"raw/{slug}"]
    valid_sources: dict[str, str] = {}
    for sid in source_ids:
        if not sid.startswith("raw/"):
            raise error_cls(f"source id {sid!r} must start with 'raw/'")
        s_slug = sid[len("raw/"):]
        if not _SLUG_RE.fullmatch(s_slug):
            raise error_cls(f"invalid source id {sid!r}")
        try:
            valid_sources[sid] = (
                (root / "vault" / "raw" / f"{s_slug}.md").read_text(encoding="utf-8")
            )
        except OSError as e:
            raise error_cls(f"cannot read {sid}: {e}") from e
    if len(source_ids) == 1:
        source_text = valid_sources[source_ids[0]]
        draft_source_id = source_ids[0]
    else:
        source_text = format_sources([(sid, valid_sources[sid]) for sid in source_ids])
        draft_source_id = ",".join(source_ids)
    return source_ids, valid_sources, source_text, draft_source_id


def compile_page(
    root,
    slug: str,
    *,
    kind: str = "concept",
    sources: Sequence[str] | None = None,
    draft_fn: DraftFn,
    scrip_cmd: Sequence[str] = DEFAULT_SCRIP_CMD,
    max_quote_retries: int = 2,
) -> Path:
    """Compile ``raw/<slug>`` (or several ``sources``) into ``wiki/<kind>s/<slug>.md``
    and leave it green.

    ``sources`` is a list of raw source ids (e.g. ``["raw/a", "raw/b"]``), defaulting
    to the single ``raw/<slug>``. With several, each claim's ``source_id`` says which
    source its quote is from, its anchor is minted against that source, and the
    page's ``derived-from`` lists them all.

    ``draft_fn(source_text, source_id=...)`` returns a :class:`DraftPage` — inject
    a stub in tests; production passes ``model.draft_page``. On an AMBIGUOUS/BROKEN
    quote it is called again with ``failures=[...]`` (one per failing claim, in
    order) and must return one corrected claim per failure — the prose body is kept
    from the first draft, so the ``[^a1]..[^aN]`` markers never move (COMPILE drops
    nothing). Bounded by ``max_quote_retries``; then raises :class:`CompileError`,
    so a bad draft never produces a stamped-but-broken page."""
    root = Path(root)
    if not _SLUG_RE.fullmatch(slug):  # fullmatch: reject a trailing newline (match + $ would not)
        raise CompileError(
            f"invalid slug {slug!r}: use letters/digits/'.'/'_'/'-', with no path "
            f"separators, '..', or leading dot"
        )
    source_ids, valid_sources, source_text, draft_source_id = _read_sources(
        root, slug, sources, CompileError
    )
    draft = draft_fn(source_text, source_id=draft_source_id)

    # The model's inline markers must be exactly [^a1]..[^aN] in order for the N
    # claims. scrip verify only checks footnote *definitions* resolve, so without
    # this a misnumbered/missing/extra marker could be stamped with uncited prose.
    markers = extract_markers(draft.body)
    expected = [f"a{i}" for i in range(1, len(draft.claims) + 1)]
    if markers != expected:
        raise CompileError(
            f"draft footnote markers {markers} do not match claims {expected} in "
            f"first-appearance order (foreign or malformed labels are rejected)"
        )

    # Mint a verified anchor per claim. scrip anchor exits non-zero on a quote that
    # is not present or not unique; instead of failing on the first, collect every
    # failing claim (scrip anchor --json reports its BROKEN/AMBIGUOUS status even on
    # exit 1), ask the model to correct exactly those — one per failure, in order —
    # and re-mint. The body is fixed, so each corrected claim keeps its marker slot.
    claims = list(draft.claims)
    retries = 0
    while True:
        footnotes: list[str] = []
        failures: list[dict] = []
        for i, claim in enumerate(claims):
            # resolve which source this claim's quote is from: explicit source_id,
            # or the sole source. An unknown or (with several sources) missing
            # source_id is a structural error, not a retryable quote failure.
            csrc = claim.source_id or (source_ids[0] if len(source_ids) == 1 else "")
            if csrc not in valid_sources:
                if claim.source_id:
                    raise CompileError(
                        f"claim {i + 1} cites source {claim.source_id!r} not among "
                        f"the compile's sources {source_ids}"
                    )
                raise CompileError(
                    f"claim {i + 1} has no source_id but the compile has multiple "
                    f"sources {source_ids}; set source_id to the quote's source"
                )
            r = _scrip(
                scrip_cmd,
                ["anchor", claim.quote, "--source", csrc, "--label", f"a{i + 1}",
                 "--json", "--root", str(root)],
            )
            if r.returncode == 0:
                footnotes.append(json.loads(r.stdout)["footnote"])
                continue
            try:
                status = json.loads(r.stdout).get("status", "BROKEN")
            except json.JSONDecodeError:
                status = "BROKEN"
            failures.append(
                {"index": i, "status": status, "quote": claim.quote,
                 "detail": r.stderr.strip()}
            )
        if not failures:
            break
        if retries >= max_quote_retries:
            detail = "; ".join(f"{f['status']} {f['quote']!r}" for f in failures)
            raise CompileError(
                f"{len(failures)} quote(s) still failed after {retries} retr"
                f"{'y' if retries == 1 else 'ies'}: {detail}"
            )
        retries += 1
        replacements = list(draft_fn(source_text, source_id=draft_source_id, failures=failures).claims)
        if len(replacements) != len(failures):
            raise CompileError(
                f"retry returned {len(replacements)} claim(s) for {len(failures)} "
                f"failure(s) — must be one corrected claim per failure, in order"
            )
        for failure, replacement in zip(failures, replacements, strict=True):
            if not replacement.quote.strip():
                raise CompileError(
                    "a retry replacement had an empty quote; COMPILE keeps every "
                    "claim (the body's markers are positional) — correct the quote "
                    "instead of dropping it"
                )
            claims[failure["index"]] = replacement

    r = _scrip(
        scrip_cmd,
        ["new", kind, slug, "--from", ",".join(source_ids), "--title", draft.title, "--root", str(root)],
    )
    if r.returncode != 0:
        raise CompileError(f"scrip new failed (exit {r.returncode}): {r.stderr.strip()}")

    # Fill the scaffold's body with the synthesized prose + minted footnotes.
    page = root / "vault" / "wiki" / f"{kind}s" / f"{slug}.md"
    meta, _ = frontmatter.load(page)
    page.write_text(frontmatter.dump(meta, assemble_body(draft, footnotes)), encoding="utf-8")

    r = _scrip(scrip_cmd, ["stamp", str(page), "--root", str(root)])
    if r.returncode != 0:
        raise CompileError(f"scrip stamp failed (exit {r.returncode}): {r.stderr.strip()}")
    r = _scrip(scrip_cmd, ["verify", "--root", str(root)])
    if r.returncode != 0:
        raise CompileError(f"scrip verify failed after compile:\n{r.stdout}{r.stderr}")
    return page


def extract_facts(
    root,
    slug: str,
    *,
    sources: Sequence[str] | None = None,
    draft_fn: ExtractDraftFn,
    scrip_cmd: Sequence[str] = DEFAULT_SCRIP_CMD,
    max_quote_retries: int = 2,
) -> dict:
    """Extract claims from ``raw/<slug>`` (or several ``sources``) into ``facts/``
    and leave the vault green.

    ``sources`` is a list of raw source ids (e.g. ``["raw/a", "raw/b"]``), defaulting
    to the single ``raw/<slug>``. With several, each claim's ``source_id`` says which
    source its quote is from and its anchor is minted against that source; a claim
    with no ``source_id`` (or one naming a source not in ``sources``) is rejected
    before anything is written.

    ``draft_fn(source_text, source_id=...)`` returns a :class:`DraftExtraction`;
    on a quote failure it is called again with ``failures=[...]`` (the per-record
    findings from ``scrip fact add``) and must return one replacement claim per
    failure, in order — an empty replacement quote drops that claim. The batch is
    all-or-nothing inside scrip, so each retry resubmits the full corrected set.
    Returns ``{"appended", "skipped", "contradictions"}``.
    """
    root = Path(root)
    if not _SLUG_RE.fullmatch(slug):  # fullmatch: reject a trailing newline (match + $ would not)
        raise ExtractError(
            f"invalid slug {slug!r}: use letters/digits/'.'/'_'/'-', with no path "
            f"separators, '..', or leading dot"
        )
    source_ids, valid_sources, source_text, draft_source_id = _read_sources(
        root, slug, sources, ExtractError
    )
    draft = draft_fn(source_text, source_id=draft_source_id)
    claims = list(draft.claims)
    if not claims:
        raise ExtractError(f"the draft proposed no claims for {draft_source_id}")

    # Resolve each claim's source before writing: with one source it defaults there;
    # with several the model must attribute every claim, and an unknown or missing
    # source_id is a structural error (fail before scrip is touched, nothing written),
    # not a retryable quote finding. scrip then mints each anchor against that source.
    # Run on every batch — including the retry-corrected one — so a replacement can
    # never set source_id to a `raw/*` outside the run's sources and smuggle in a
    # claim from an unrequested source.
    default_source = source_ids[0] if len(source_ids) == 1 else ""

    def _check_sources(batch: list[DraftFact]) -> None:
        for i, claim in enumerate(batch):
            csrc = claim.source_id or default_source
            if csrc not in valid_sources:
                if claim.source_id:
                    raise ExtractError(
                        f"claim {i + 1} cites source {claim.source_id!r} not among the "
                        f"extract's sources {source_ids}"
                    )
                raise ExtractError(
                    f"claim {i + 1} has no source_id but the extract has multiple "
                    f"sources {source_ids}; set source_id to the quote's source"
                )

    # Submit; on per-record quote findings (exit 1, nothing written) ask the
    # model to fix exactly the failing quotes and resubmit the corrected batch.
    retries = 0
    while True:
        _check_sources(claims)
        r = _scrip(
            scrip_cmd,
            ["fact", "add", "--table", "claims", "--stdin", "--json", "--root", str(root)],
            input_text=to_ndjson(claims, default_source),
        )
        if r.returncode == 0:
            try:
                added = json.loads(r.stdout)
            except json.JSONDecodeError as e:
                raise ExtractError(
                    f"could not parse scrip fact add output: {e}\n{r.stdout}"
                ) from e
            break
        if r.returncode != 1:
            raise ExtractError(
                f"scrip fact add failed (exit {r.returncode}): {r.stderr.strip()}"
            )
        try:
            failures = json.loads(r.stdout)["failures"]
        except (json.JSONDecodeError, KeyError) as e:
            raise ExtractError(
                f"could not parse scrip fact add failures: {e}\n{r.stdout}"
            ) from e
        if retries >= max_quote_retries:
            detail = "; ".join(
                f"{f['status']} {f.get('quote', '')!r}" for f in failures
            )
            raise ExtractError(
                f"{len(failures)} quote(s) still failed after {retries} retr"
                f"{'y' if retries == 1 else 'ies'}: {detail}"
            )
        retries += 1
        revised = draft_fn(source_text, source_id=draft_source_id, failures=failures)
        replacements = list(revised.claims)
        if len(replacements) != len(failures):
            raise ExtractError(
                f"retry returned {len(replacements)} claim(s) for {len(failures)} "
                f"failure(s) — must be one per failure, in order (an empty quote "
                f"drops the claim)"
            )
        dropped: list[int] = []
        for failure, replacement in zip(failures, replacements, strict=True):
            i = failure["index"]
            if replacement.quote.strip():
                # A retry fixes the quote, not the attribution: keep the original
                # claim's source_id when the replacement omits it, so a multi-source
                # claim stays minted against the right source.
                if not replacement.source_id:
                    replacement.source_id = claims[i].source_id
                claims[i] = replacement
            else:
                dropped.append(i)
        for i in sorted(dropped, reverse=True):
            del claims[i]
        if not claims:
            raise ExtractError("every claim was dropped during quote retries")

    # Stamp the facts set scrip left honestly STALE, then prove the vault green.
    if added["appended"]:
        meta_path = root / "vault" / "facts" / "_meta.yaml"
        r = _scrip(scrip_cmd, ["stamp", str(meta_path), "--root", str(root)])
        if r.returncode != 0:
            raise ExtractError(f"scrip stamp failed (exit {r.returncode}): {r.stderr.strip()}")
    r = _scrip(scrip_cmd, ["verify", "--root", str(root)])
    if r.returncode != 0:
        raise ExtractError(f"scrip verify failed after extract:\n{r.stdout}{r.stderr}")

    # Surface contradiction candidates for RECONCILE — detection is scrip's,
    # adjudication stays the operator's.
    r = _scrip(scrip_cmd, ["query", "contradictions", "--json", "--root", str(root)])
    if r.returncode != 0:
        raise ExtractError(
            f"scrip query contradictions failed (exit {r.returncode}): {r.stderr.strip()}"
        )
    return {
        "appended": added["appended"],
        "skipped": added["skipped"],
        "contradictions": json.loads(r.stdout),
    }


def _append_log(root: Path, line: str) -> None:
    log = root / "vault" / "wiki" / "log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


def _existing_entity_ids(root: Path) -> dict[str, str]:
    """Map ``name -> entity_id`` for entities already in ``entities.ndjson`` so a
    drafted edge may point at an entity from a prior run. Malformed rows are
    skipped here — scrip status/verify is the authority on file validity."""
    out: dict[str, str] = {}
    try:
        text = (root / "vault" / "facts" / "entities.ndjson").read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        name, eid = rec.get("name"), rec.get("entity_id")
        if isinstance(name, str) and isinstance(eid, str):
            out.setdefault(name, eid)
    return out


def _ensure_source_tracked(root: Path, source_id: str) -> None:
    """Record ``source_id`` in ``facts/_meta.yaml`` ``derived-from`` so the graph
    facts go STALE when that source changes.

    ``scrip fact add`` adds this provenance link itself only for *claims* (they
    carry a ``source_id``); entities and edges do not, so without this a
    graph-only facts set would be staleness-blind to the raw source it was drafted
    from. This declares the dependency edge the entity/edge schema cannot carry —
    it is not a re-implementation of scrip's hashing: ``scrip stamp`` still
    computes the ``input-hash`` over the resulting ``derived-from`` set. Done under
    scrip's write lock, mirroring scrip's own meta writes."""
    import yaml

    from scrip import lock

    meta_path = root / "vault" / "facts" / "_meta.yaml"
    with lock.write_lock(root):
        try:
            data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        except OSError:
            return  # no meta yet; scrip creates it on the append that precedes this
        if not isinstance(data, dict):
            return
        derived = list(data.get("derived-from") or [])
        if source_id in derived:
            return
        derived.append(source_id)
        data["derived-from"] = derived
        data.pop("input-hash", None)  # force a fresh stamp over the new source set
        meta_path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )


def _fact_add(scrip_cmd: Sequence[str], root: Path, table: str, ndjson: str) -> dict:
    """Append a batch to ``facts/<table>`` and return scrip's ``{appended, skipped}``.
    Entities/edges have no quote findings, so any non-zero exit is a hard error
    (the runner's own guards already rejected dangling/unsluggable records)."""
    r = _scrip(
        scrip_cmd,
        ["fact", "add", "--table", table, "--stdin", "--json", "--root", str(root)],
        input_text=ndjson,
    )
    if r.returncode != 0:
        raise GraphError(
            f"scrip fact add --table {table} failed (exit {r.returncode}): "
            f"{r.stderr.strip() or r.stdout.strip()}"
        )
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise GraphError(f"could not parse scrip fact add output: {e}\n{r.stdout}") from e


def draft_graph_facts(
    root,
    slug: str,
    *,
    draft_fn: GraphDraftFn,
    scrip_cmd: Sequence[str] = DEFAULT_SCRIP_CMD,
) -> dict:
    """Draft entities + edges from ``raw/<slug>`` into ``facts/`` and leave the
    vault green.

    ``draft_fn(source_text, source_id=...)`` returns a :class:`DraftGraph`. There
    is no quote-retry loop (entities/edges carry no anchors). Instead the runner
    enforces two honesty guards before writing: an entity whose ``name`` has no
    usable slug is **skipped**, and an edge is **dropped** unless both endpoints
    resolve to a real entity — drafted in this pass or already in
    ``entities.ndjson``. Returns
    ``{"entities", "edges", "dropped_edges", "skipped_entities"}``.
    """
    root = Path(root)
    if not _SLUG_RE.fullmatch(slug):  # fullmatch: reject a trailing newline
        raise GraphError(
            f"invalid slug {slug!r}: use letters/digits/'.'/'_'/'-', with no path "
            f"separators, '..', or leading dot"
        )
    source_id = f"raw/{slug}"
    try:
        source_text = (root / "vault" / "raw" / f"{slug}.md").read_text(encoding="utf-8")
    except OSError as e:
        raise GraphError(f"cannot read {source_id}: {e}") from e

    draft = draft_fn(source_text, source_id=source_id)

    # Mint ids and build name->id. Drafted entities win on a name collision so an
    # entity's appended row and the edges pointing at it use the same id; existing
    # entities fill in names this pass did not redraft.
    # Skip entities the writer would reject (no usable slug, or a blank `kind`),
    # so the entities batch cannot fail on model data — its append must succeed
    # before the edges batch runs (the two tables are separate, non-transactional
    # `fact add` calls, so a mid-stage rejection would leave entities committed
    # without their edges).
    kept_entities: list[DraftEntity] = []
    skipped_entities: list[str] = []
    name_to_id: dict[str, str] = {}
    for e in draft.entities:
        eid = entity_id(e.name)
        if not eid or not e.kind.strip():
            skipped_entities.append(e.name)
            continue
        kept_entities.append(e)
        name_to_id[e.name] = eid
    for name, eid in _existing_entity_ids(root).items():
        name_to_id.setdefault(name, eid)

    # The honesty guard: keep only edges whose endpoints are real entities and
    # whose `kind` is non-empty (a blank kind is the other reachable writer
    # rejection — dropping it keeps the edges batch from failing after entities
    # have already been committed).
    kept_edges: list[DraftEdge] = []
    dropped_edges: list[dict] = []
    for edge in draft.edges:
        if edge.src in name_to_id and edge.dst in name_to_id and edge.kind.strip():
            kept_edges.append(edge)
        else:
            dropped_edges.append({"src": edge.src, "dst": edge.dst, "kind": edge.kind})

    if not kept_entities and not kept_edges:
        raise GraphError(f"the draft proposed no entities or edges for {source_id}")

    empty = {"appended": [], "skipped": []}
    added_entities = (
        _fact_add(scrip_cmd, root, "entities", entities_to_ndjson(kept_entities))
        if kept_entities
        else dict(empty)
    )
    added_edges = (
        _fact_add(scrip_cmd, root, "edges", edges_to_ndjson(kept_edges, name_to_id))
        if kept_edges
        else dict(empty)
    )

    # Any append leaves the facts set honestly STALE; link the source so future
    # edits to it stale the graph, then stamp and prove the vault green.
    if added_entities["appended"] or added_edges["appended"]:
        _ensure_source_tracked(root, source_id)
        meta_path = root / "vault" / "facts" / "_meta.yaml"
        r = _scrip(scrip_cmd, ["stamp", str(meta_path), "--root", str(root)])
        if r.returncode != 0:
            raise GraphError(f"scrip stamp failed (exit {r.returncode}): {r.stderr.strip()}")
    r = _scrip(scrip_cmd, ["verify", "--root", str(root)])
    if r.returncode != 0:
        raise GraphError(f"scrip verify failed after graph:\n{r.stdout}{r.stderr}")

    n_ent, n_edge = len(added_entities["appended"]), len(added_edges["appended"])
    note = (
        f"- {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} GRAPH "
        f"{source_id}: +{n_ent} entit{'y' if n_ent == 1 else 'ies'}, +{n_edge} edge(s)"
    )
    if dropped_edges:
        note += f", {len(dropped_edges)} edge(s) dropped (unknown endpoint)"
    if skipped_entities:
        note += f", {len(skipped_entities)} entity name(s) skipped (no slug)"
    _append_log(root, note)

    return {
        "entities": added_entities,
        "edges": added_edges,
        "dropped_edges": dropped_edges,
        "skipped_entities": skipped_entities,
    }


def _scrip_json(
    scrip_cmd: Sequence[str],
    args: list[str],
    *,
    error_cls: type[RuntimeError],
    ok: set[int] | None = None,
) -> tuple[int, object]:
    ok = ok or {0}
    r = _scrip(scrip_cmd, args)
    if r.returncode not in ok:
        raise error_cls(
            f"scrip {' '.join(args[:2])} failed (exit {r.returncode}): "
            f"{r.stderr.strip() or r.stdout.strip()}"
        )
    try:
        return r.returncode, json.loads(r.stdout or "null")
    except json.JSONDecodeError as e:
        raise error_cls(
            f"could not parse scrip {' '.join(args[:2])} output: {e}\n{r.stdout}"
        ) from e


def _slugify(s: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (slug or "answer")[:60].strip("-") or "answer"


def _read_wiki_pages(root: Path, question: str, top: int) -> list[dict]:
    pages: list[dict] = []
    wd = root / "vault" / "wiki"
    if not wd.is_dir():
        return pages
    for path in sorted(wd.rglob("*.md")):
        if path.name in {"index.md", "log.md"} or path.name.startswith("_"):
            continue
        try:
            meta, body = frontmatter.load(path)
        except Exception:  # noqa: BLE001 - malformed pages are caught by scrip status/verify
            continue
        text = body.strip()
        title = str(meta.get("title") or path.stem) if meta else path.stem
        score = overlap_score(question, f"{title} {text}")
        if score <= 0:
            continue
        pages.append(
            {
                "ref": str(path.relative_to(root)),
                "id": meta.get("id") if meta else None,
                "title": title,
                "excerpt": text[:1200],
                "score": score,
            }
        )
    pages.sort(key=lambda p: (-p["score"], p["ref"]))
    return pages[:top]


def _rank_claims(question: str, claims: list[dict], top: int) -> list[dict]:
    ranked: list[dict] = []
    for rec in claims:
        tags = rec.get("tags") or []
        text = " ".join(
            str(rec.get(k) or "")
            for k in ("claim_text", "subject", "predicate", "object", "source_id")
        )
        text += " " + " ".join(str(t) for t in tags)
        score = overlap_score(question, text)
        if score <= 0:
            continue
        ranked.append(
            {
                "ref": rec.get("claim_id"),
                "source_id": rec.get("source_id"),
                "text": rec.get("claim_text"),
                "triple": [rec.get("subject"), rec.get("predicate"), rec.get("object")],
                "polarity": rec.get("polarity"),
                "tags": tags,
                "score": score,
            }
        )
    ranked.sort(key=lambda c: (-c["score"], str(c["ref"])))
    return ranked[:top]


def _gather_answer_evidence(
    root: Path,
    question: str,
    *,
    scrip_cmd: Sequence[str],
    k: int,
    min_compiled: int,
) -> dict:
    claims: list[dict] = []
    if (root / "vault" / "facts" / "claims.ndjson").exists():
        _, rows = _scrip_json(
            scrip_cmd,
            ["query", "claims", "--json", "--root", str(root)],
            error_cls=AnswerError,
        )
        assert isinstance(rows, list)
        claims = rows
    ranked_claims = _rank_claims(question, claims, k)
    pages = _read_wiki_pages(root, question, k)

    raw_blocks: list[dict] = []
    # Wiki pages are context-only: the model may read them, but final citations
    # must be claim ids or raw quotes. Do not let non-citable page context satisfy
    # the fallback threshold, or a wiki-heavy/facts-light vault dead-ends with no
    # raw evidence the answer can legally cite.
    top_claim_score = ranked_claims[0]["score"] if ranked_claims else 0
    strong_claim_threshold = max(2, min(4, len(tokenize(question)) // 2))
    if len(ranked_claims) < min_compiled or top_claim_score < strong_claim_threshold:
        _, search = _scrip_json(
            scrip_cmd,
            ["search", question, "-k", str(k), "--json", "--root", str(root)],
            error_cls=AnswerError,
        )
        assert isinstance(search, dict)
        raw_blocks = [
            {
                "ref": f"{r.get('source_id')}#{r.get('block_id')}",
                "source_id": r.get("source_id"),
                "snippet": r.get("snippet"),
                "score": r.get("score"),
                "method": r.get("method"),
            }
            for r in search.get("results", [])
        ]

    return {
        "claims": ranked_claims,
        "wiki_pages": pages,
        "raw_blocks": raw_blocks,
        "policy": {
            "claim_citations": "cite by claim_id",
            "raw_citations": "cite by source_id plus verbatim quote",
            "wiki_pages": "context only; do not cite directly",
        },
    }


def _answer_footnotes(
    root: Path,
    draft: DraftAnswer,
    evidence: dict,
    *,
    scrip_cmd: Sequence[str],
) -> list[str]:
    markers = extract_markers(draft.body)
    expected = [f"a{i}" for i in range(1, len(draft.citations) + 1)]
    citation_markers = [c.marker for c in draft.citations]
    if not draft.citations:
        raise AnswerError("answer draft has no citations")
    if markers != expected or citation_markers != expected:
        raise AnswerError(
            f"draft markers {markers} and citation records {citation_markers} "
            f"must be exactly {expected}"
        )

    allowed_claims = {c["ref"] for c in evidence["claims"] if c.get("ref")}
    allowed_sources = {
        c["source_id"] for c in evidence["claims"] if c.get("source_id")
    } | {
        r["source_id"] for r in evidence["raw_blocks"] if r.get("source_id")
    }

    footnotes: list[str] = []
    for c in draft.citations:
        if c.kind == "claim":
            if c.claim_id not in allowed_claims:
                raise AnswerError(f"citation {c.marker} references ungathered claim {c.claim_id!r}")
            _, span = _scrip_json(
                scrip_cmd,
                ["span", "--claim", c.claim_id, "--json", "--root", str(root)],
                error_cls=AnswerError,
                ok={0, 1},
            )
            assert isinstance(span, dict)
            if span.get("status") != "OK":
                raise AnswerError(
                    f"claim citation {c.claim_id} did not resolve uniquely: {span.get('status')}"
                )
            text = str(span.get("text") or "")
            label = text[:72].replace("\n", " ")
            footnotes.append(
                f'[^{c.marker}]: anchor={span["target"]} claim={c.claim_id}  "{label}"'
            )
        else:
            if c.source_id not in allowed_sources:
                raise AnswerError(f"citation {c.marker} references ungathered source {c.source_id!r}")
            if not c.quote.strip():
                raise AnswerError(f"citation {c.marker} has an empty raw quote")
            r = _scrip(
                scrip_cmd,
                [
                    "anchor",
                    c.quote,
                    "--source",
                    c.source_id,
                    "--label",
                    c.marker,
                    "--json",
                    "--root",
                    str(root),
                ],
            )
            if r.returncode != 0:
                raise AnswerError(
                    f"raw citation {c.marker} did not resolve uniquely "
                    f"(scrip anchor exit {r.returncode}): {c.quote!r}\n{r.stderr.strip()}"
                )
            footnotes.append(json.loads(r.stdout)["footnote"])
    return footnotes


def _unique_exploration_path(root: Path, question: str) -> Path:
    base = _slugify(question)
    d = root / "vault" / "wiki" / "explorations"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{base}.md"
    if not path.exists():
        return path
    for i in range(2, 1000):
        candidate = d / f"{base}-{i}.md"
        if not candidate.exists():
            return candidate
    raise AnswerError(f"too many saved answers for slug {base!r}")


def answer_question(
    root,
    question: str,
    *,
    draft_fn: AnswerDraftFn,
    scrip_cmd: Sequence[str] = DEFAULT_SCRIP_CMD,
    k: int = 6,
    min_compiled: int = 4,
    allow_stale: bool = False,
    allow_open_contradictions: bool = False,
    save: bool = False,
) -> dict:
    """Answer a question via the answer ladder and return ``{answer, evidence,
    saved}``.

    The vault must verify cleanly. Stale artifacts and open contradiction pairs
    are refused by default. Model output is accepted only after every citation is
    checked by `scrip span` or minted by `scrip anchor`.
    """
    root = Path(root)
    if not question.strip():
        raise AnswerError("question must not be empty")

    status_rc, status = _scrip_json(
        scrip_cmd,
        ["status", "--json", "--root", str(root)],
        error_cls=AnswerError,
        ok={0, 1},
    )
    assert isinstance(status, dict)
    if status_rc == 1 and not allow_stale:
        stale = ", ".join(s["id"] for s in status.get("stale", []))
        raise AnswerError(f"refusing to answer with stale artifact(s): {stale}")

    verify_rc, verify = _scrip_json(
        scrip_cmd,
        ["verify", "--json", "--root", str(root)],
        error_cls=AnswerError,
        ok={0, 1},
    )
    assert isinstance(verify, dict)
    if verify_rc != 0:
        raise AnswerError(
            f"refusing to answer with unresolved citations: "
            f"{len(verify.get('broken', []))} broken, {len(verify.get('ambiguous', []))} ambiguous"
        )

    contradictions: list = []
    if (root / "vault" / "facts" / "claims.ndjson").exists():
        _, rows = _scrip_json(
            scrip_cmd,
            ["query", "contradictions", "--json", "--root", str(root)],
            error_cls=AnswerError,
        )
        assert isinstance(rows, list)
        contradictions = rows
    if contradictions and not allow_open_contradictions:
        raise AnswerError(
            f"refusing to answer with {len(contradictions)} open contradiction(s); "
            "run scrip-harness reconcile or pass allow_open_contradictions"
        )

    evidence = _gather_answer_evidence(
        root, question, scrip_cmd=scrip_cmd, k=k, min_compiled=min_compiled
    )
    if not (evidence["claims"] or evidence["wiki_pages"] or evidence["raw_blocks"]):
        raise AnswerError("no relevant compiled or raw evidence found")

    draft = draft_fn(question, evidence=evidence)
    footnotes = _answer_footnotes(root, draft, evidence, scrip_cmd=scrip_cmd)
    answer = draft.body.rstrip() + "\n\n" + "\n".join(footnotes) + "\n"

    saved_path = None
    if save:
        path = _unique_exploration_path(root, question)
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = (
            "---\n"
            f"query: {json.dumps(question, ensure_ascii=False)}\n"
            f"answered-at: {created}\n"
            "---\n\n"
            f"{answer}"
        )
        path.write_text(body, encoding="utf-8")
        # Saved explorations live under wiki/, so prove the minted footnotes keep
        # vault-wide verification green before reporting success.
        r = _scrip(scrip_cmd, ["verify", "--root", str(root)])
        if r.returncode != 0:
            path.unlink(missing_ok=True)
            raise AnswerError(f"scrip verify failed after saving answer:\n{r.stdout}{r.stderr}")
        saved_path = str(path.relative_to(root))
        _append_log(root, f"- ANSWER: saved {saved_path} for {question!r}")

    return {"answer": answer, "evidence": evidence, "saved": saved_path}


def promote_page(
    root,
    slug: str,
    *,
    kind: str = "concept",
    decide_fn: DecideFn | None = None,
    merge_threshold: float = 0.5,
    keep_threshold: float = 0.25,
    scrip_cmd: Sequence[str] = DEFAULT_SCRIP_CMD,
    dry_run: bool = False,
) -> dict:
    """Promote a freshly compiled page: score it against existing pages with
    ``scrip similar``, then keep it or merge it into the best match.

    Banding on the top candidate's combined score: ``>= merge_threshold`` →
    merge (deterministic, no model); ``< keep_threshold`` → keep; in between →
    ``decide_fn(candidate_text, candidates)`` returns a ``PromotionDecision``
    (the only model use). On merge the absorbed page is appended into the target
    (footnotes renumbered), its sources/​id folded into the target's
    ``derived-from``/``supersedes``, then the target is re-stamped and the vault
    re-verified. Returns a dict describing the action.
    """
    root = Path(root)
    if not _SLUG_RE.fullmatch(slug):  # guard before building any path we might unlink
        raise PromoteError(
            f"invalid slug {slug!r}: use letters/digits/'.'/'_'/'-', with no path "
            f"separators, '..', or leading dot"
        )
    page = root / "vault" / "wiki" / f"{kind}s" / f"{slug}.md"
    if not page.exists():
        raise PromoteError(f"no such {kind} page: {page.relative_to(root)}")
    meta, body = frontmatter.load(page)
    cand_id = meta.get("id") or f"{kind}/{slug}"
    title = meta.get("title") or slug
    sources = list(meta.get("derived-from") or [])

    r = _scrip(
        scrip_cmd,
        ["similar", "--title", title, "--from", ",".join(sources), "--kind", kind,
         "--exclude", cand_id, "--top", "5", "--json", "--root", str(root)],
    )
    if r.returncode != 0:
        raise PromoteError(f"scrip similar failed (exit {r.returncode}): {r.stderr.strip()}")
    candidates = json.loads(r.stdout)["candidates"]
    if not candidates:
        return {"action": "keep", "target": None, "reason": "no candidates"}

    top = candidates[0]
    score = top["scores"]["combined"]
    if score >= merge_threshold:
        target_id = top["id"]
    elif score < keep_threshold:
        return {"action": "keep", "target": None, "reason": f"top score {score:.3f} below keep threshold"}
    else:
        if decide_fn is None:
            raise PromoteError(
                f"middle band (top score {score:.3f}) needs a decider; none given"
            )
        decision = decide_fn(page.read_text(encoding="utf-8"), candidates)
        if decision.decision != "merge":
            return {"action": "keep", "target": None, "reason": "decided keep"}
        target_id = decision.target_id

    target = next((c for c in candidates if c["id"] == target_id), None)
    if target is None:
        raise PromoteError(f"merge target {target_id!r} is not among the scored candidates")

    if dry_run:
        return {"action": "merge", "target": target_id, "dry_run": True,
                "score": score, "absorbed": cand_id}

    target_page = root / target["path"]
    original_target = target_page.read_bytes()  # bytes: rollback must be exact (CRLF, encoding)
    t_meta, t_body = frontmatter.load(target_page)
    new_body = merge_bodies(t_body, body)
    df = list(t_meta.get("derived-from") or [])
    for s in sources:
        if s not in df:
            df.append(s)
    t_meta["derived-from"] = df
    sup = list(t_meta.get("supersedes") or [])
    if cand_id not in sup:
        sup.append(cand_id)
    t_meta["supersedes"] = sup
    confs = [c for c in (t_meta.get("confidence"), meta.get("confidence"))
             if isinstance(c, (int, float))]
    if confs:
        t_meta["confidence"] = min(confs)
    target_page.write_text(frontmatter.dump(t_meta, new_body), encoding="utf-8")

    # The merge is atomic. The absorbed page is deleted only after stamp + verify
    # succeed (no data loss), and on failure the target is restored to its
    # original bytes — so a failed promote leaves the vault byte-for-byte
    # unchanged and a rerun after fixing the cause cannot duplicate content. Until
    # the unlink both pages exist and verify cleanly (footnotes resolve against
    # raw/, not each other).
    try:
        r = _scrip(scrip_cmd, ["stamp", str(target_page), "--root", str(root)])
        if r.returncode != 0:
            raise PromoteError(f"scrip stamp failed (exit {r.returncode}): {r.stderr.strip()}")
        r = _scrip(scrip_cmd, ["verify", "--root", str(root)])
        if r.returncode != 0:
            raise PromoteError(f"scrip verify failed after merge:\n{r.stdout}{r.stderr}")
    except PromoteError:
        target_page.write_bytes(original_target)  # roll back the merge, byte-for-byte
        raise
    page.unlink()  # absorbed page removed; its id lives on in the target's supersedes
    _append_log(root, f"- PROMOTE: merged {cand_id} into {target_id}")
    return {"action": "merge", "target": target_id, "absorbed": cand_id}


def _span(scrip_cmd: Sequence[str], root: Path, claim_id: str) -> dict:
    """Fetch a claim's resolved span via `scrip span` → ``{status, text}``."""
    r = _scrip(scrip_cmd, ["span", "--claim", claim_id, "--json", "--root", str(root)])
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise ReconcileError(
            f"scrip span --claim {claim_id} gave no parseable output: {e}\n{r.stderr}"
        ) from e


def reconcile_contradictions(
    root,
    *,
    decide_fn: ReconcileDecideFn,
    scrip_cmd: Sequence[str] = DEFAULT_SCRIP_CMD,
    dry_run: bool = False,
) -> dict:
    """Adjudicate every open contradiction. For each pair from `scrip query
    contradictions`, read both cited spans (`scrip span`), ask ``decide_fn`` for a
    :class:`ReconciliationDecision`, then record them append-only with `scrip fact
    add --table reconciliations`, log to wiki/log.md, and re-stamp + re-verify.
    ``dry_run`` reports the decisions without writing. Returns a summary.
    """
    root = Path(root)
    r = _scrip(scrip_cmd, ["query", "contradictions", "--json", "--root", str(root)])
    if r.returncode != 0:
        raise ReconcileError(f"scrip query contradictions failed (exit {r.returncode}): {r.stderr.strip()}")
    pairs = json.loads(r.stdout)
    if not pairs:
        return {"pairs": 0, "reconciled": []}

    records: list[dict] = []
    # A `qualify` also authors a nuancing `polarity: qualifies` claim; collect each
    # with the source its verbatim quote is from, to append in one batch below.
    qualify_claims: list[tuple[DraftFact, str]] = []
    for pair in pairs:
        ca, cb = pair["claim_a"], pair["claim_b"]
        # Read both spans first and refuse unresolved evidence BEFORE asking the
        # model or recording anything — never adjudicate (and thereby suppress) a
        # contradiction on an anchor that doesn't resolve uniquely.
        sa, sb = _span(scrip_cmd, root, ca), _span(scrip_cmd, root, cb)
        if sa["status"] != "OK" or sb["status"] != "OK":
            raise ReconcileError(
                f"cannot reconcile {ca}/{cb}: anchor did not resolve uniquely "
                f"({ca}={sa['status']}, {cb}={sb['status']}) — fix it first (scrip verify)"
            )
        decision = decide_fn(pair, sa["text"], sb["text"])
        rec = {"decision": decision.decision, "claim_a": ca, "claim_b": cb}
        if decision.decision == "supersede":
            if decision.winner not in ("a", "b"):
                raise ReconcileError(
                    f"supersede for {ca}/{cb} needs winner 'a' or 'b', got {decision.winner!r}"
                )
            rec["winner"] = ca if decision.winner == "a" else cb
        elif decision.decision == "qualify":
            # The qualify must carry the verbatim quote + source + condition needed
            # to author the claim — the load-bearing half of the decision. (The page
            # caveat is left to a view, not baked into a stamped page.)
            if (
                not decision.qualifier_quote.strip()
                or decision.qualifier_source not in ("a", "b")
                or not decision.qualifier_object.strip()
            ):
                raise ReconcileError(
                    f"qualify for {ca}/{cb} needs qualifier_quote, qualifier_source "
                    f"'a'|'b', and qualifier_object"
                )
            src = pair["source_a"] if decision.qualifier_source == "a" else pair["source_b"]
            qualify_claims.append(
                (
                    DraftFact(
                        quote=decision.qualifier_quote,
                        subject=pair["subject"],
                        predicate=pair["predicate"],
                        object=decision.qualifier_object,
                        polarity="qualifies",
                        claim_text=decision.rationale,
                    ),
                    src,
                )
            )
        if decision.rationale:
            rec["rationale"] = decision.rationale
        records.append(rec)

    if dry_run:
        return {"pairs": len(pairs), "dry_run": True, "decisions": records}

    # Author the nuancing qualifies claims FIRST. scrip mints their anchors
    # all-or-nothing (a quote that doesn't resolve fails here), so on failure we
    # abort before recording any reconciliation — never suppress a pair without the
    # nuance it promised. A qualifies claim cannot re-open a contradiction
    # (detection is asserts-vs-denies only).
    qualified: list = []
    if qualify_claims:
        claims_ndjson = "".join(to_ndjson([f], src) for f, src in qualify_claims)
        r = _scrip(
            scrip_cmd,
            ["fact", "add", "--table", "claims", "--stdin", "--json", "--root", str(root)],
            input_text=claims_ndjson,
        )
        if r.returncode != 0:
            raise ReconcileError(
                f"could not author qualifies claim(s) (scrip fact add exit "
                f"{r.returncode}): {r.stderr.strip() or r.stdout.strip()}"
            )
        qualified = json.loads(r.stdout)["appended"]

    ndjson = "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in records)
    r = _scrip(
        scrip_cmd,
        ["fact", "add", "--table", "reconciliations", "--stdin", "--json", "--root", str(root)],
        input_text=ndjson,
    )
    if r.returncode != 0:
        raise ReconcileError(f"scrip fact add failed (exit {r.returncode}): {r.stderr.strip()}")
    added = json.loads(r.stdout)
    for rec in records:
        tail = f" (winner {rec['winner']})" if rec["decision"] == "supersede" else ""
        _append_log(root, f"- RECONCILE: {rec['decision']} {rec['claim_a']} vs {rec['claim_b']}{tail}")

    # Any append (claims or reconciliations) drops the facts set's input-hash, so
    # stamp when either wrote, then prove the vault green.
    if qualified or added["appended"]:
        r = _scrip(scrip_cmd, ["stamp", str(root / "vault" / "facts" / "_meta.yaml"), "--root", str(root)])
        if r.returncode != 0:
            raise ReconcileError(f"scrip stamp failed (exit {r.returncode}): {r.stderr.strip()}")
    r = _scrip(scrip_cmd, ["verify", "--root", str(root)])
    if r.returncode != 0:
        raise ReconcileError(f"scrip verify failed after reconcile:\n{r.stdout}{r.stderr}")
    return {
        "pairs": len(pairs),
        "reconciled": added["appended"],
        "skipped": added["skipped"],
        "qualified": qualified,
    }

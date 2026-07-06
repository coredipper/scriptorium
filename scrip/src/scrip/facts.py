"""Validated, locked writers for the facts/ layer — behind ``scrip fact add``.

The agent (or harness) *proposes* records; scrip owns everything checkable,
mirroring how ``scrip anchor`` mints citations for wiki prose:

- a proposed claim carries a verbatim ``quote`` — never an ``anchor``,
  ``claim_id``, or ``extracted_at``; those are minted here, and the anchor is
  verified to resolve uniquely in the stored source text;
- the batch is **all-or-nothing**: one unresolvable quote (or conflicting
  entity id) means nothing is appended, and every failure is reported with its
  input index so the caller can retry just the failing records;
- exact duplicates (same source, normalized quote, triple, and polarity) are
  skipped and reported, so re-running an extraction is safe;
- quote verification, ids, and the append all happen under the advisory write
  lock; claim sources are merged into ``facts/_meta.yaml`` ``derived-from`` and
  every append (any table) drops the set's ``input-hash`` — the facts set
  honestly shows STALE until ``scrip stamp`` re-blesses it.
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader

from . import anchors, facts_dir, lock
from .errors import DataError, UsageError

_POLARITIES = ("asserts", "denies", "qualifies")

# table name -> file under vault/facts/
_FILES = {
    "claims": "claims.ndjson",
    "entities": "entities.ndjson",
    "edges": "graph.ndjson",
    "reconciliations": "reconciliations.ndjson",
}

# Fields scrip mints itself; proposing them is a schema error, not a finding.
_SCRIP_OWNED = ("claim_id", "anchor", "extracted_at")
_RECON_OWNED = ("reconciliation_id", "at")

_CLAIM_REQUIRED = ("quote", "source_id", "subject", "predicate", "object", "polarity", "confidence")
_CLAIM_ALLOWED = frozenset((*_CLAIM_REQUIRED, "claim_text", "tags"))
_ENTITY_REQUIRED = ("entity_id", "name", "kind")
_ENTITY_ALLOWED = frozenset((*_ENTITY_REQUIRED, "tags"))
_EDGE_REQUIRED = ("src", "dst", "kind")
# An edge may optionally be *cited*: a verbatim ``quote`` + ``source_id`` whose
# ``anchor`` scrip mints+verifies exactly as for a claim. Bare edges stay
# structural. ``anchor`` remains scrip-owned (proposing it is a schema error).
_EDGE_ALLOWED = frozenset((*_EDGE_REQUIRED, "quote", "source_id"))
_DECISIONS = ("supersede", "qualify", "keep-both")
_RECON_REQUIRED = ("decision", "claim_a", "claim_b")
_RECON_ALLOWED = frozenset((*_RECON_REQUIRED, "winner", "rationale"))

# Same conservative shape ``cli._safe_slug`` enforces — no path separators,
# '..', or leading dot — applied to source ids arriving as record *data*.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_CLAIM_ID_RE = re.compile(r"clm_(\d+)")
_RECON_ID_RE = re.compile(r"rec_(\d+)")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Input parsing & structural validation (DataError, exit 3)
# --------------------------------------------------------------------------- #
def parse_ndjson(text: str) -> list[dict]:
    """Parse proposed records (one JSON object per line). Malformed input is a
    :class:`DataError` with its line number; an empty input is a usage error."""
    records: list[dict] = []
    # Split on "\n" only, not str.splitlines(): NDJSON records are newline-
    # delimited and may legally contain U+2028/U+2029/NEL inside a JSON string,
    # which splitlines() would wrongly treat as record breaks. trailing \r (from
    # \r\n) and the trailing empty element from a final newline are dropped below.
    for lineno, raw_line in enumerate(io.StringIO(text, newline="\n"), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise DataError(f"input line {lineno}: invalid JSON: {e}") from e
        if not isinstance(rec, dict):
            raise DataError(f"input line {lineno}: expected a JSON object")
        records.append(rec)
    if not records:
        raise UsageError("no records in input")
    return records


def _check_str(rec: dict, key: str, index: int, *, allow_blank: bool = False) -> None:
    v = rec[key]
    if not isinstance(v, str) or (not allow_blank and not v.strip()):
        raise DataError(f"record {index}: '{key}' must be a non-empty string")


def _check_tags(rec: dict, index: int) -> None:
    tags = rec.get("tags")
    if tags is None:
        return
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise DataError(f"record {index}: 'tags' must be a list of strings")


def _check_shape(
    rec: dict,
    index: int,
    required: tuple[str, ...],
    allowed: frozenset[str],
    owned: tuple[str, ...] = _SCRIP_OWNED,
) -> None:
    present = [k for k in owned if k in rec]
    if present:
        raise DataError(
            f"record {index}: scrip mints {', '.join(present)} itself — do not "
            f"propose precomputed ids/anchors/timestamps"
        )
    unknown = sorted(rec.keys() - allowed)
    if unknown:
        raise DataError(f"record {index}: unknown field(s): {', '.join(unknown)}")
    missing = sorted(k for k in required if k not in rec)
    if missing:
        raise DataError(f"record {index}: missing required field(s): {', '.join(missing)}")


def _validate(table: str, rec: dict, index: int) -> None:
    if table == "claims":
        _check_shape(rec, index, _CLAIM_REQUIRED, _CLAIM_ALLOWED)
        # the quote's *emptiness* is a per-record finding, not a schema error
        _check_str(rec, "quote", index, allow_blank=True)
        for key in ("source_id", "subject", "predicate", "object"):
            _check_str(rec, key, index)
        if "claim_text" in rec:
            _check_str(rec, "claim_text", index, allow_blank=True)
        if rec["polarity"] not in _POLARITIES:
            raise DataError(
                f"record {index}: polarity must be one of {', '.join(_POLARITIES)}"
            )
        c = rec["confidence"]
        if isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1:
            raise DataError(f"record {index}: confidence must be a number in [0, 1]")
        _check_tags(rec, index)
    elif table == "entities":
        _check_shape(rec, index, _ENTITY_REQUIRED, _ENTITY_ALLOWED)
        for key in _ENTITY_REQUIRED:
            _check_str(rec, key, index)
        eid = rec["entity_id"]
        if not (eid.startswith("entity/") and _SLUG_RE.fullmatch(eid[len("entity/") :])):
            raise DataError(f"record {index}: entity_id must look like entity/<slug>")
        _check_tags(rec, index)
    elif table == "edges":
        _check_shape(rec, index, _EDGE_REQUIRED, _EDGE_ALLOWED)
        for key in _EDGE_REQUIRED:
            _check_str(rec, key, index)
        if "quote" in rec or "source_id" in rec:
            # both or neither: a quote needs a source to anchor against
            missing = [k for k in ("quote", "source_id") if k not in rec]
            if missing:
                raise DataError(
                    f"record {index}: a cited edge needs both 'quote' and 'source_id' "
                    f"(missing: {', '.join(missing)})"
                )
            _check_str(rec, "source_id", index)
            # quote emptiness is a per-record finding (EMPTY_QUOTE), not a schema error
            _check_str(rec, "quote", index, allow_blank=True)
    else:  # reconciliations
        _check_shape(rec, index, _RECON_REQUIRED, _RECON_ALLOWED, owned=_RECON_OWNED)
        for key in ("decision", "claim_a", "claim_b"):
            _check_str(rec, key, index)
        if rec["decision"] not in _DECISIONS:
            raise DataError(f"record {index}: decision must be one of {', '.join(_DECISIONS)}")
        if "rationale" in rec:
            _check_str(rec, "rationale", index, allow_blank=True)
        # winner is required for (and only for) supersede, and must be one of the pair
        if rec["decision"] == "supersede":
            winner = rec.get("winner")
            if winner not in (rec["claim_a"], rec["claim_b"]):
                raise DataError(
                    f"record {index}: supersede needs 'winner' = claim_a or claim_b"
                )
        elif "winner" in rec:
            raise DataError(f"record {index}: 'winner' is only valid for decision 'supersede'")


# --------------------------------------------------------------------------- #
# Claim content checks (per-record findings, exit 1)
# --------------------------------------------------------------------------- #
def _resolve_claim(
    root: Path, rec: dict, index: int, src_cache: dict[str, str | None]
) -> tuple[dict | None, dict | None]:
    """Mint+verify the anchor for one proposed claim. Returns
    ``(failure, resolved)`` — exactly one is non-None. ``resolved`` carries the
    normalized ``source_id``, the minted ``anchor``, and its ``qh``."""

    def failure(status: str, detail: str, source_id: str) -> tuple[dict, None]:
        return (
            {
                "index": index,
                "status": status,
                "source_id": source_id,
                "quote": rec["quote"],
                "detail": detail,
            },
            None,
        )

    given = rec["source_id"]
    source_id = given if given.startswith("raw/") else f"raw/{given}"
    slug = source_id[len("raw/") :]
    if not _SLUG_RE.fullmatch(slug):
        return failure("INVALID_SOURCE", "unsafe source id (path separators or '..')", given)

    if source_id not in src_cache:
        try:
            src_cache[source_id] = anchors.source_text(root, source_id)
        except DataError:
            src_cache[source_id] = None
    text = src_cache[source_id]
    if text is None:
        return failure("MISSING_SOURCE", "source does not exist in vault/raw/", source_id)

    if not anchors.normalize(rec["quote"]):
        return failure("EMPTY_QUOTE", "quote is empty after normalization", source_id)

    anchor = anchors.make_anchor(text, rec["quote"])
    status = anchors.resolve(text, anchor)
    if status != "OK":
        remedy = (
            "lengthen the quote until it is unique"
            if status == "AMBIGUOUS"
            else "the quote must appear verbatim in the source"
        )
        return failure(status, remedy, source_id)

    qh = anchors.parse_anchor(anchor)["qh"]
    return None, {"source_id": source_id, "anchor": anchor, "qh": qh}


# --------------------------------------------------------------------------- #
# Existing-table reads & keys
# --------------------------------------------------------------------------- #
def _ends_with_newline(path: Path) -> bool:
    """Whether the file's final byte is a newline (an empty/absent file counts as
    terminated, so no separator is prepended before the next append)."""
    if not path.exists() or path.stat().st_size == 0:
        return True
    with path.open("rb") as f:
        f.seek(-1, 2)
        return f.read(1) == b"\n"


def _read_table(path: Path) -> tuple[list[dict], bool]:
    """Read an NDJSON table, returning ``(records, ends_with_newline)``. Streams the
    file line-by-line rather than loading it whole. Malformed lines are a
    :class:`DataError` — the vault on disk violates the contract."""
    if not path.exists():
        return [], True
    ends_newline = _ends_with_newline(path)
    records: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise DataError(f"{path.name}:{lineno}: invalid JSON: {e}") from e
            records.append(rec)
    return records, ends_newline


def claim_source_anchor(root: Path, claim_id: str) -> tuple[str, str]:
    """Return ``(source_id, anchor)`` for a claim, for `scrip span --claim`.
    Raises :class:`DataError` if the claim is missing or lacks the fields."""
    records, _ = _read_table(facts_dir(root) / "claims.ndjson")
    for rec in records:
        if rec.get("claim_id") == claim_id:
            sid, anchor = rec.get("source_id"), rec.get("anchor")
            if not isinstance(sid, str) or not isinstance(anchor, str):
                raise DataError(f"claim {claim_id} is missing source_id/anchor")
            return sid, anchor
    raise DataError(f"no such claim: {claim_id}")


def _claim_key(source_id: str, qh: str, rec: dict) -> tuple:
    return (
        source_id,
        qh,
        rec.get("subject"),
        rec.get("predicate"),
        rec.get("object"),
        rec.get("polarity"),
    )


def _existing_claim_keys(existing: list[dict]) -> dict[tuple, str]:
    keys: dict[tuple, str] = {}
    for rec in existing:
        anchor = rec.get("anchor")
        if not isinstance(anchor, str):
            continue
        qh = anchors.parse_anchor(anchor)["qh"]
        keys[_claim_key(rec.get("source_id", ""), qh, rec)] = str(rec.get("claim_id", ""))
    return keys


def _next_claim_id(existing: list[dict]) -> tuple[int, int]:
    """Return ``(next_number, pad_width)`` continuing the ``clm_NNNN`` sequence."""
    numbers = [
        int(m.group(1))
        for rec in existing
        if (m := _CLAIM_ID_RE.fullmatch(str(rec.get("claim_id", ""))))
    ]
    highest = max(numbers, default=0)
    return highest + 1, max(4, len(str(highest)))


def _next_recon_id(existing: list[dict]) -> tuple[int, int]:
    """Return ``(next_number, pad_width)`` continuing the ``rec_NNNN`` sequence."""
    numbers = [
        int(m.group(1))
        for rec in existing
        if (m := _RECON_ID_RE.fullmatch(str(rec.get("reconciliation_id", ""))))
    ]
    highest = max(numbers, default=0)
    return highest + 1, max(4, len(str(highest)))


# --------------------------------------------------------------------------- #
# facts/_meta.yaml: merge derived-from, never stamp
# --------------------------------------------------------------------------- #
def _load_meta(root: Path) -> dict:
    """Parse (or default) ``facts/_meta.yaml``. Called *before* any append so a
    malformed file fails the whole add — claims must never land with their
    source missing from ``derived-from`` (an undetectable staleness lie)."""
    p = facts_dir(root) / "_meta.yaml"
    if not p.exists():
        return {
            "id": "facts/core",
            "type": "facts.set",
            "derived-from": [],
            "members": [
                "facts/entities.ndjson",
                "facts/claims.ndjson",
                "facts/graph.ndjson",
            ],
            "confidence": 0.0,
        }
    try:
        data = yaml.load(p.read_text(encoding="utf-8"), Loader=SafeLoader) or {}
    except yaml.YAMLError as e:
        raise DataError(f"invalid facts/_meta.yaml: {e}") from e
    if not isinstance(data, dict):
        raise DataError("invalid facts/_meta.yaml: expected a mapping")
    return data


def _write_meta(root: Path, data: dict, new_sources: list[str]) -> None:
    derived = list(data.get("derived-from") or [])
    for sid in new_sources:
        if sid not in derived:
            derived.append(sid)
    data["derived-from"] = derived
    # Drop the stamp on EVERY append: with an unchanged derived-from the
    # recomputed input-hash would still match the stored one, and status would
    # report OK over facts nobody has blessed. Removing input-hash forces STALE
    # ("no input-hash recorded") until `scrip stamp vault/facts/_meta.yaml`.
    # last-compiled is kept as the historical record of the last bless.
    data.pop("input-hash", None)
    (facts_dir(root) / "_meta.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# The writer
# --------------------------------------------------------------------------- #
def add(root: Path, table: str, proposals: list[dict]) -> dict:
    """Validate ``proposals`` and append them to ``facts/`` all-or-nothing.

    Returns ``{"table", "appended", "skipped", "failures"}``; the caller maps a
    non-empty ``failures`` to exit 1. Structural problems raise
    :class:`DataError`/:class:`UsageError` instead.
    """
    if table not in _FILES:
        raise UsageError(f"unknown facts table: {table}")
    for i, rec in enumerate(proposals):
        _validate(table, rec, i)

    failures: list[dict] = []
    resolved: list[dict | None] = [None] * len(proposals)
    path = facts_dir(root) / _FILES[table]
    with lock.write_lock(root):
        # Resolve quotes INSIDE the lock: raw/ only changes via a *locked*
        # `ingest --reingest`, so holding the lock from verification through
        # append closes the window where a re-ingest could land between the
        # two and silently break the just-minted anchors. Claims always carry a
        # quote; an edge does only when it is *cited*.
        if table == "claims" or table == "edges":
            src_cache: dict[str, str | None] = {}
            for i, rec in enumerate(proposals):
                if table == "edges" and "quote" not in rec:
                    continue  # bare edge: nothing to anchor
                fail, res = _resolve_claim(root, rec, i, src_cache)
                if fail:
                    failures.append(fail)
                else:
                    resolved[i] = res
            if failures:
                return {"table": table, "appended": [], "skipped": [], "failures": failures}

        existing, ends_with_newline = _read_table(path)
        meta = _load_meta(root)  # parse before appending: fail whole, not half
        appended: list[dict] = []
        skipped: list[dict] = []

        if table == "claims":
            keys = _existing_claim_keys(existing)
            number, width = _next_claim_id(existing)
            now = _now()
            for i, rec in enumerate(proposals):
                res = resolved[i]
                assert res is not None  # failures returned above
                key = _claim_key(res["source_id"], res["qh"], rec)
                if key in keys:
                    skipped.append({"index": i, "reason": "duplicate", "existing_id": keys[key]})
                    continue
                cid = f"clm_{number:0{width}d}"
                number += 1
                full = {
                    "claim_id": cid,
                    "subject": rec["subject"],
                    "predicate": rec["predicate"],
                    "object": rec["object"],
                    "claim_text": rec.get("claim_text") or rec["quote"],
                    "source_id": res["source_id"],
                    "anchor": res["anchor"],
                    "confidence": rec["confidence"],
                    "polarity": rec["polarity"],
                    "extracted_at": now,
                    "tags": rec.get("tags") or [],
                }
                keys[key] = cid
                appended.append(full)
        elif table == "entities":
            def canon(rec: dict) -> dict:
                return {
                    "entity_id": rec["entity_id"],
                    "name": rec["name"],
                    "kind": rec["kind"],
                    "tags": rec.get("tags") or [],
                }

            byid = {rec.get("entity_id"): canon(rec) for rec in existing if "entity_id" in rec
                    and isinstance(rec.get("name"), str) and isinstance(rec.get("kind"), str)}
            for i, rec in enumerate(proposals):
                new = canon(rec)
                seen = byid.get(new["entity_id"])
                if seen is None:
                    byid[new["entity_id"]] = new
                    appended.append(new)
                elif seen == new:
                    skipped.append(
                        {"index": i, "reason": "duplicate", "existing_id": new["entity_id"]}
                    )
                else:
                    failures.append(
                        {
                            "index": i,
                            "status": "ID_CONFLICT",
                            "entity_id": new["entity_id"],
                            "detail": "an entity with this id already exists with different fields",
                        }
                    )
        elif table == "edges":
            seen_edges = {
                (rec.get("src"), rec.get("dst"), rec.get("kind")) for rec in existing
            }
            for i, rec in enumerate(proposals):
                key = (rec["src"], rec["dst"], rec["kind"])
                if key in seen_edges:
                    skipped.append({"index": i, "reason": "duplicate", "existing_id": None})
                    continue
                seen_edges.add(key)
                full = {"src": rec["src"], "dst": rec["dst"], "kind": rec["kind"]}
                res = resolved[i]
                if res is not None:  # cited edge: carry the minted provenance
                    full["source_id"] = res["source_id"]
                    full["anchor"] = res["anchor"]
                appended.append(full)
        else:  # reconciliations
            claim_ids = {c.get("claim_id") for c in _read_table(facts_dir(root) / "claims.ndjson")[0]}
            for i, rec in enumerate(proposals):
                refs = [rec["claim_a"], rec["claim_b"]]
                if rec["decision"] == "supersede":
                    refs.append(rec["winner"])
                missing = next((r for r in refs if r not in claim_ids), None)
                if missing is not None:
                    failures.append({
                        "index": i, "status": "MISSING_CLAIM", "claim": missing,
                        "detail": f"{missing!r} is not a claim in claims.ndjson",
                    })
            if failures:
                return {"table": table, "appended": [], "skipped": [], "failures": failures}
            seen_pairs = {frozenset((r.get("claim_a"), r.get("claim_b"))) for r in existing}
            number, width = _next_recon_id(existing)
            now = _now()
            for i, rec in enumerate(proposals):
                pair = frozenset((rec["claim_a"], rec["claim_b"]))
                if pair in seen_pairs:
                    skipped.append({"index": i, "reason": "duplicate", "existing_id": None})
                    continue
                seen_pairs.add(pair)
                rid = f"rec_{number:0{width}d}"
                number += 1
                full = {
                    "reconciliation_id": rid,
                    "decision": rec["decision"],
                    "claim_a": rec["claim_a"],
                    "claim_b": rec["claim_b"],
                }
                if rec["decision"] == "supersede":
                    full["winner"] = rec["winner"]
                if rec.get("rationale"):
                    full["rationale"] = rec["rationale"]
                full["at"] = now
                appended.append(full)

        if failures:
            return {"table": table, "appended": [], "skipped": skipped, "failures": failures}

        if appended:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in appended)
            with open(path, "a", encoding="utf-8") as f:
                if not ends_with_newline:
                    f.write("\n")
                f.write(payload)
            new_sources: list[str] = []
            if table in ("claims", "edges"):
                for rec in appended:
                    sid = rec.get("source_id")  # cited edges carry one; bare edges don't
                    if sid and sid not in new_sources:
                        new_sources.append(sid)
            _write_meta(root, meta, new_sources)

    return {"table": table, "appended": appended, "skipped": skipped, "failures": []}

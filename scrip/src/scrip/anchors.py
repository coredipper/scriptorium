"""Content-anchored provenance — the integrity check behind ``scrip verify``.

A citation does not point at a line number (which rots the instant a source is
reformatted). It points at a hash of the *normalized quote*:

    qh:<sha256-hex>|loc:<fractional-start>|len:<normalized-char-len>

``verify`` re-locates the quote by sliding a length-``len`` window over the
*normalized* source text and looking for a window whose hash equals ``qh``. The
hash is taken over text we control and store in ``vault/raw/`` (never the live
PDF/HTML), so re-extracting a PDF can never silently break a citation — only a
deliberate re-ingest can, and that surfaces as a normal staleness event.

Normalization (identical at write- and verify-time) is what gives reflow- and
case-invariance: NFC → collapse whitespace runs to one space → strip → lower.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path

from . import facts_dir, hashing, raw_dir, wiki_dir
from .errors import DataError

_FOOTNOTE = re.compile(r"^\[\^([^\]]+)\]:\s*anchor=(\S+)")

# The canonical normalization lives in ``hashing`` so blocks and anchors share
# one definition; re-exported here for callers that import ``anchors.normalize``.
normalize = hashing.normalize


def _qh(normalized_quote: str) -> str:
    return hashlib.sha256(normalized_quote.encode("utf-8")).hexdigest()


def make_anchor(source_text: str, quote: str) -> str:
    """Build an anchor for ``quote`` as it appears in ``source_text``.

    ``loc`` is a positional hint (fraction of the way through the normalized
    source); resolution does not depend on it being exact.
    """
    ns = normalize(source_text)
    nq = normalize(quote)
    if not nq:
        raise DataError("cannot anchor an empty quote")
    idx = ns.find(nq)
    loc = (idx / len(ns)) if (idx >= 0 and ns) else 0.0
    return f"qh:{_qh(nq)}|loc:{loc:.4f}|len:{len(nq)}"


def parse_anchor(anchor: str) -> dict:
    parts: dict[str, str] = {}
    for seg in anchor.split("|"):
        if ":" in seg:
            k, v = seg.split(":", 1)
            parts[k] = v
    if "qh" not in parts or "len" not in parts:
        raise DataError(f"malformed anchor (need qh and len): {anchor}")
    try:
        return {
            "qh": parts["qh"],
            "len": int(parts["len"]),
            "loc": float(parts.get("loc", 0.0)),
        }
    except ValueError as e:
        raise DataError(f"malformed anchor numerics: {anchor}") from e


def resolve(source_text: str, anchor: str) -> str:
    """Return ``OK`` | ``AMBIGUOUS`` | ``BROKEN`` for ``anchor`` in ``source_text``."""
    a = parse_anchor(anchor)
    ns = normalize(source_text)
    n, target = a["len"], a["qh"]
    length = len(ns)
    if n <= 0 or n > length:
        return "BROKEN"
    matches = 0
    for start in range(length - n + 1):
        window = ns[start : start + n]
        if hashlib.sha256(window.encode("utf-8")).hexdigest() == target:
            matches += 1
            if matches > 1:
                break
    if matches == 0:
        return "BROKEN"
    return "OK" if matches == 1 else "AMBIGUOUS"


def span(source_text: str, anchor: str) -> tuple[str, str | None]:
    """Return ``(status, cited_text)`` for ``anchor`` in ``source_text``.

    Same verdicts as :func:`resolve`, but also returns the matched span (the
    normalized cited text) so a caller can *read* what an anchor cites. For
    ``AMBIGUOUS`` the window nearest the anchor's ``loc`` hint is returned; for
    ``BROKEN`` the text is ``None``.
    """
    a = parse_anchor(anchor)
    ns = normalize(source_text)
    n, target, loc = a["len"], a["qh"], a["loc"]
    length = len(ns)
    if n <= 0 or n > length:
        return "BROKEN", None
    hits = [
        start
        for start in range(length - n + 1)
        if hashlib.sha256(ns[start : start + n].encode("utf-8")).hexdigest() == target
    ]
    if not hits:
        return "BROKEN", None
    if len(hits) == 1:
        return "OK", ns[hits[0] : hits[0] + n]
    nearest = min(hits, key=lambda s: abs(s - loc * length))
    return "AMBIGUOUS", ns[nearest : nearest + n]


# --------------------------------------------------------------------------- #
# Vault-wide verification
# --------------------------------------------------------------------------- #
def _source_text(root: Path, source_id: str, cache: dict[str, str]) -> str:
    if source_id in cache:
        return cache[source_id]
    if not source_id.startswith("raw/"):
        raise DataError(f"source_id must start with 'raw/': {source_id}")
    p = raw_dir(root) / (source_id[len("raw/") :] + ".md")
    if not p.exists():
        raise DataError(f"reference to missing source: {source_id}")
    cache[source_id] = p.read_text(encoding="utf-8")
    return cache[source_id]


def source_text(root: Path, source_id: str) -> str:
    """Public read of a raw source's canonical text (raises ``DataError`` if the
    source id is malformed or the file is missing). Used by ``scrip anchor``."""
    return _source_text(root, source_id, {})


def _iter_footnote_anchors(path: Path) -> Iterator[dict]:
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _FOOTNOTE.match(line)
        if not m:
            continue
        target = m.group(2)
        if "#" not in target:
            continue
        source_id, anchor = target.split("#", 1)
        yield {"fn": m.group(1), "source_id": source_id, "anchor": anchor}


def verify_vault(root: Path) -> dict:
    """Resolve every claim anchor and wiki footnote anchor; check referenced
    sources exist and claim ids are unique.

    Raises :class:`DataError` (exit 3) for structural problems — bad JSON,
    missing source files, duplicate claim ids. Unresolvable anchors are returned
    as ``broken`` (exit 1), not raised: the data is well-formed, the citation
    just no longer points at existing text.
    """
    src_cache: dict[str, str] = {}
    broken: list[dict] = []
    ambiguous: list[dict] = []
    checked = 0
    ok = 0

    def record(where: str, ref: dict, status: str) -> None:
        nonlocal checked, ok
        checked += 1
        entry = {"where": where, "source_id": ref["source_id"], "anchor": ref["anchor"]}
        if status == "OK":
            ok += 1
        elif status == "AMBIGUOUS":
            ambiguous.append(entry)
        else:
            broken.append(entry)

    claims_path = facts_dir(root) / "claims.ndjson"
    if claims_path.exists():
        seen: set[str] = set()
        for lineno, raw_line in enumerate(
            claims_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise DataError(f"claims.ndjson:{lineno}: invalid JSON: {e}") from e
            for key in ("claim_id", "source_id", "anchor"):
                if key not in rec:
                    raise DataError(f"claims.ndjson:{lineno}: missing '{key}'")
            cid = rec["claim_id"]
            if cid in seen:
                raise DataError(f"duplicate claim_id: {cid}")
            seen.add(cid)
            text = _source_text(root, rec["source_id"], src_cache)
            record(f"claim:{cid}", rec, resolve(text, rec["anchor"]))

    wd = wiki_dir(root)
    if wd.is_dir():
        for path in sorted(wd.rglob("*.md")):
            rel = path.relative_to(root)
            for ref in _iter_footnote_anchors(path):
                text = _source_text(root, ref["source_id"], src_cache)
                record(f"wiki:{rel}#{ref['fn']}", ref, resolve(text, ref["anchor"]))

    return {"checked": checked, "ok": ok, "ambiguous": ambiguous, "broken": broken}


def print_verify(result: dict) -> None:
    print(
        f"checked {result['checked']} anchor(s): "
        f"{result['ok']} OK, {len(result['ambiguous'])} AMBIGUOUS, "
        f"{len(result['broken'])} BROKEN"
    )
    for r in result["ambiguous"]:
        print(f"  ~ AMBIGUOUS {r['where']} -> {r['source_id']}")
    for r in result["broken"]:
        print(f"  ✗ BROKEN     {r['where']} -> {r['source_id']}")
    if not result["broken"] and not result["ambiguous"]:
        print("all citations resolve.")

"""Deterministic topic-overlap scoring for PROMOTE step 1 (`scrip similar`).

Ranks existing wiki pages by how much a proposed topic overlaps each, from three
file-derived signals:

- **title** — Jaccard of normalized title tokens (the §6 normalization).
- **sources** — Jaccard of `derived-from` source ids (block suffix stripped).
- **tags** — Jaccard of tag sets. Pages carry no `tags` frontmatter (SPEC §4),
  so a page's tags are *derived*: the union of `tags` over claims whose
  `source_id` is one of the page's sources.

`combined` is a weighted sum (sources dominates — shared sources is the strongest
same-topic signal). This is **purely informational**: it reports scores and
leaves the High/Middle/Low merge decision of AGENT.md PROMOTE to the caller,
exactly as `query contradictions` leaves adjudication to the agent. No lock, no
model, no DuckDB.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from . import facts_dir, frontmatter
from .errors import DataError
from .graph import scan_derived
from .hashing import normalize

DEFAULT_WEIGHTS = {"title": 0.25, "sources": 0.5, "tags": 0.25}


def _tokens(title: str) -> set[str]:
    return set(normalize(title).split())


def _strip_block(dep: str) -> str:
    """`raw/x#b3` -> `raw/x` (block-scoped deps share their whole source)."""
    return dep.split("#", 1)[0]


def _source_set(derived_from: Iterable[str]) -> set[str]:
    return {_strip_block(d) for d in derived_from}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _source_tags(root: Path) -> dict[str, set[str]]:
    """Map each `source_id` to the union of `tags` over its claims. Built once
    per run from facts/claims.ndjson (parsed directly — no DuckDB dependency)."""
    out: dict[str, set[str]] = {}
    p = facts_dir(root) / "claims.ndjson"
    if not p.exists():
        return out
    for lineno, raw_line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise DataError(f"claims.ndjson:{lineno}: invalid JSON: {e}") from e
        if not isinstance(rec, dict):
            raise DataError(f"claims.ndjson:{lineno}: expected a JSON object")
        sid = rec.get("source_id")
        if not isinstance(sid, str):
            continue
        tags = rec.get("tags")
        if tags is None:
            continue
        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
            raise DataError(f"claims.ndjson:{lineno}: 'tags' must be a list of strings")
        out.setdefault(sid, set()).update(tags)
    return out


def _page_tags(sources: set[str], source_tags: Mapping[str, set[str]]) -> set[str]:
    out: set[str] = set()
    for s in sources:
        out |= source_tags.get(s, set())
    return out


def compute_similar(
    root: str | Path,
    *,
    title: str,
    sources: Iterable[str],
    kind: str = "concept",
    exclude: Iterable[str] | None = None,
    top: int | None = None,
    weights: Mapping[str, float] | None = None,
) -> dict:
    """Score existing `kind` wiki pages against the proposed (title, sources).

    Returns ``{proposed, weights, candidates}`` with candidates sorted by
    ``combined`` desc then id asc, truncated to ``top``.
    """
    root = Path(root)
    w = dict(weights or DEFAULT_WEIGHTS)
    skip = set(exclude or ())
    prop_sources = _source_set(sources)
    prop_tokens = _tokens(title)
    source_tags = _source_tags(root)
    prop_tags = _page_tags(prop_sources, source_tags)

    want_type = f"wiki.{kind}"
    candidates: list[dict] = []
    for cid, d in scan_derived(root).items():
        if d.get("type") != want_type or cid in skip:
            continue  # other-kind pages and the facts.set row are dropped here
        c_sources = _source_set(d["derived_from"])
        meta, _ = frontmatter.load(root / d["path"])
        c_title = (meta.get("title") if meta else "") or ""
        c_tags = _page_tags(c_sources, source_tags)

        title_s = _jaccard(prop_tokens, _tokens(c_title))
        sources_s = _jaccard(prop_sources, c_sources)
        tags_s = _jaccard(prop_tags, c_tags)
        combined = w["title"] * title_s + w["sources"] * sources_s + w["tags"] * tags_s
        candidates.append(
            {
                "id": cid,
                "title": c_title,
                "path": d["path"],
                "kind": kind,
                "scores": {
                    "title": round(title_s, 6),
                    "sources": round(sources_s, 6),
                    "tags": round(tags_s, 6),
                    "combined": round(combined, 6),
                },
                "shared": {
                    "sources": sorted(prop_sources & c_sources),
                    "tags": sorted(prop_tags & c_tags),
                },
            }
        )

    candidates.sort(key=lambda c: (-c["scores"]["combined"], c["id"]))
    if top is not None:
        candidates = candidates[:top]
    return {
        "proposed": {"title": title, "derived_from": list(sources), "kind": kind},
        "weights": w,
        "candidates": candidates,
    }


def print_similar(result: dict) -> None:
    p = result["proposed"]
    print(f'proposed: "{p["title"]}"  ({p["kind"]}, from {len(p["derived_from"])} source(s))')
    cands = result["candidates"]
    if not cands:
        print(f"no existing {p['kind']} pages to compare.")
        return
    for c in cands:
        s = c["scores"]
        print(f'  {s["combined"]:.3f}  {c["id"]}  "{c["title"]}"')
        print(
            f'         sources {s["sources"]:.2f}  tags {s["tags"]:.2f}  title {s["title"]:.2f}'
            f'   shared sources: {len(c["shared"]["sources"])}, tags: {len(c["shared"]["tags"])}'
        )
    print(f"({len(cands)} candidate(s))")

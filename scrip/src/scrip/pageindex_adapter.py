"""Optional PageIndex cache adapter for long-document retrieval.

PageIndex is treated like embeddings: a regenerable cache under ``.kb/``, never
the source of truth. The only durable text remains ``vault/raw/<slug>.md``; every
search result snippet persisted here must be copied verbatim from that raw text
so a later answer can still cite it with ``scrip anchor``.

The real backend is deliberately optional. Tests monkeypatch ``_get_backend``;
production can provide a module exposing ``build``/``build_index`` and optionally
``search``. Without a backend, the CLI reports an unavailable adapter and normal
``scrip search`` falls back to embeddings/grep.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import hashing, raw_dir
from .errors import DataError

INDEX_SCHEMA = 1

_backend = None
_backend_tried = False


def _pageindex_dir(root: Path) -> Path:
    return root / ".kb" / "pageindex"


def _source_id(source: str) -> str:
    sid = source if source.startswith("raw/") else f"raw/{source}"
    slug = sid[len("raw/") :]
    if "/" in slug or "\\" in slug or slug.startswith(".") or ".." in slug:
        raise DataError(f"unsafe source id: {source}")
    return sid


def _source_path(root: Path, source_id: str) -> Path:
    p = raw_dir(root) / f"{source_id[len('raw/'):]}.md"
    if not p.exists():
        raise DataError(f"source does not exist: {source_id}")
    return p


def _cache_dir(root: Path, source_id: str) -> Path:
    return _pageindex_dir(root) / source_id[len("raw/") :]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_backend():
    """Return an optional PageIndex backend module/object.

    The adapter accepts either ``pageindex`` or ``page_index`` as import names.
    A usable backend exposes ``build`` or ``build_index``; ``search`` is optional
    because cached records can still be ranked lexically.
    """
    global _backend, _backend_tried
    if _backend_tried:
        return _backend
    _backend_tried = True
    for name in ("pageindex", "page_index"):
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        if any(hasattr(mod, attr) for attr in ("build", "build_index")):
            _backend = mod
            break
    return _backend


def available() -> bool:
    return _get_backend() is not None


def _backend_name(backend) -> str:
    return getattr(backend, "__name__", backend.__class__.__name__)


def _backend_version(backend) -> str:
    return str(getattr(backend, "__version__", "unknown"))


def _call_build(backend, *, source_id: str, text: str):
    if hasattr(backend, "build_index"):
        return backend.build_index(source_id=source_id, text=text)
    if hasattr(backend, "build"):
        return backend.build(source_id=source_id, text=text)
    if callable(backend):
        return backend(source_id=source_id, text=text)
    raise RuntimeError("PageIndex backend does not expose build/build_index")


def _call_search(backend, *, query: str, items: list[dict], k: int):
    if backend is not None and hasattr(backend, "search"):
        return backend.search(query=query, items=items, k=k)
    return _lexical_rank(query, items, k)


def _candidate_records(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("items", "sections", "nodes", "results"):
            val = raw.get(key)
            if isinstance(val, list):
                return val
    return []


def _coerce_items(raw, *, source_id: str, text: str) -> list[dict]:
    """Normalize backend records and keep only snippets present in raw text."""
    items: list[dict] = []
    for i, rec in enumerate(_candidate_records(raw)):
        if not isinstance(rec, dict):
            continue
        snippet = str(rec.get("snippet") or rec.get("text") or rec.get("content") or "")
        span = rec.get("span_hint") or rec.get("span")
        if (
            isinstance(span, list)
            and len(span) == 2
            and all(isinstance(n, int) for n in span)
            and 0 <= span[0] < span[1] <= len(text)
        ):
            # Prefer the canonical raw slice. Backend summaries are not citable.
            snippet = text[span[0] : span[1]].strip()
        if not snippet:
            continue
        start = text.find(snippet)
        if start < 0:
            # The contract requires verbatim evidence; discard summaries.
            continue
        span_hint = [start, start + len(snippet)]
        items.append(
            {
                "source_id": source_id,
                "section_id": str(rec.get("section_id") or rec.get("id") or i),
                "snippet": snippet,
                "span_hint": span_hint,
                "score": float(rec.get("score") or 0.0),
                "method": "pageindex",
            }
        )
    return items


def _cached_item_maps(items: list[dict]) -> tuple[dict[tuple[str, str], dict], dict[str, list[dict]]]:
    by_section: dict[tuple[str, str], dict] = {}
    by_snippet: dict[str, list[dict]] = {}
    for item in items:
        source_id = item.get("source_id")
        section_id = item.get("section_id")
        snippet = item.get("snippet")
        if isinstance(source_id, str) and section_id is not None:
            by_section[(source_id, str(section_id))] = item
        if isinstance(snippet, str):
            by_snippet.setdefault(snippet, []).append(item)
    return by_section, by_snippet


def _float_score(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _match_cached_item(
    rec: dict, by_section: dict[tuple[str, str], dict], by_snippet: dict[str, list[dict]]
) -> dict | None:
    source_id = rec.get("source_id")
    if isinstance(source_id, str):
        try:
            source_id = _source_id(source_id)
        except DataError:
            source_id = None
    else:
        source_id = None
    section_id = rec.get("section_id") or rec.get("id")
    if source_id is not None and section_id is not None:
        item = by_section.get((source_id, str(section_id)))
        if item is not None:
            return item
    snippet = rec.get("snippet") or rec.get("text") or rec.get("content")
    if isinstance(snippet, str):
        for item in by_snippet.get(snippet, []):
            if source_id is None or item.get("source_id") == source_id:
                if section_id is None or str(item.get("section_id")) == str(section_id):
                    return item
    return None


def _canonical_search_results(raw, items: list[dict], k: int) -> list[dict]:
    by_section, by_snippet = _cached_item_maps(items)
    results: list[dict] = []
    seen: set[tuple[str, str, tuple[int, ...]]] = set()
    for rec in _candidate_records(raw):
        if not isinstance(rec, dict):
            continue
        item = _match_cached_item(rec, by_section, by_snippet)
        if item is None:
            continue
        span = item.get("span_hint")
        span_key = tuple(span) if isinstance(span, list) and all(isinstance(n, int) for n in span) else ()
        key = (str(item.get("source_id")), str(item.get("section_id")), span_key)
        if key in seen:
            continue
        seen.add(key)
        out = dict(item)
        out["score"] = _float_score(rec.get("score"), _float_score(item.get("score"), 0.0))
        out["method"] = "pageindex"
        results.append(out)
        if len(results) >= k:
            break
    return results


def build_index(root: Path, source: str) -> dict:
    """Build a PageIndex cache for one raw source.

    Returns ``{"status": "built"|"unavailable", ...}`` rather than raising for
    a missing backend so the CLI can fail soft like ``scrip index``.
    """
    backend = _get_backend()
    if backend is None:
        return {
            "status": "unavailable",
            "message": (
                "PageIndex backend not installed; see docs/pageindex-adapter.md. "
                "Normal `scrip search` still falls back to embeddings/grep."
            ),
        }
    source_id = _source_id(source)
    path = _source_path(root, source_id)
    text = path.read_text(encoding="utf-8")
    raw = _call_build(backend, source_id=source_id, text=text)
    items = _coerce_items(raw, source_id=source_id, text=text)
    d = _cache_dir(root, source_id)
    d.mkdir(parents=True, exist_ok=True)
    raw_hash = hashing.content_hash_file(path)
    (d / "tree.json").write_text(
        json.dumps({"source_id": source_id, "items": items}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    (d / "meta.json").write_text(
        json.dumps(
            {
                "source_id": source_id,
                "raw_content_hash": raw_hash,
                "backend": _backend_name(backend),
                "backend_version": _backend_version(backend),
                "schema": INDEX_SCHEMA,
                "created_at": _now(),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"status": "built", "source_id": source_id, "sections_indexed": len(items)}


def _load_cached(root: Path, source_id: str | None = None) -> tuple[list[dict], bool]:
    base = _pageindex_dir(root)
    if not base.is_dir():
        return [], False
    dirs = (
        [_cache_dir(root, _source_id(source_id))]
        if source_id
        else sorted(p for p in base.iterdir() if p.is_dir())
    )
    items: list[dict] = []
    stale = False
    for d in dirs:
        tree_p, meta_p = d / "tree.json", d / "meta.json"
        if not tree_p.exists() or not meta_p.exists():
            continue
        try:
            tree = json.loads(tree_p.read_text(encoding="utf-8"))
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        sid = meta.get("source_id") or tree.get("source_id")
        if not isinstance(sid, str):
            continue
        try:
            source_path = _source_path(root, sid)
            current = hashing.content_hash_file(source_path)
            text = source_path.read_text(encoding="utf-8")
        except DataError:
            stale = True
            continue
        if meta.get("schema") != INDEX_SCHEMA:
            stale = True
            continue
        if meta.get("raw_content_hash") != current:
            stale = True
        vals = tree.get("items") if isinstance(tree, dict) else None
        if isinstance(vals, list):
            items.extend(_revalidate_cached_items(vals, source_id=sid, text=text))
    return items, stale


def _revalidate_cached_items(raw_items: list, *, source_id: str, text: str) -> list[dict]:
    items: list[dict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        cached_source = item.get("source_id")
        if isinstance(cached_source, str):
            try:
                if _source_id(cached_source) != source_id:
                    continue
            except DataError:
                continue
        snippet = item.get("snippet")
        if not isinstance(snippet, str) or not snippet:
            continue
        start = text.find(snippet)
        if start < 0:
            continue
        out = dict(item)
        out["source_id"] = source_id
        out["snippet"] = snippet
        out["span_hint"] = [start, start + len(snippet)]
        out["score"] = _float_score(item.get("score"), 0.0)
        out["method"] = "pageindex"
        items.append(out)
    return items


def _terms(query: str) -> list[str]:
    return [t for t in hashing.normalize(query).split() if t]


def _lexical_rank(query: str, items: list[dict], k: int) -> list[dict]:
    terms = _terms(query)
    ranked: list[dict] = []
    for item in items:
        low = str(item.get("snippet") or "").lower()
        score = sum(low.count(t) for t in terms)
        if score <= 0:
            continue
        out = dict(item)
        out["score"] = float(score)
        out["method"] = "pageindex"
        ranked.append(out)
    ranked.sort(key=lambda r: (-float(r["score"]), str(r.get("source_id")), str(r.get("section_id"))))
    return ranked[:k]


def search(root: Path, query: str, k: int = 5, source_id: str | None = None) -> dict | None:
    """Return ``{method, stale_index, results}``, or ``None`` with no cache."""
    items, stale = _load_cached(root, source_id)
    if not items:
        return None
    backend = _get_backend()
    raw_results = _call_search(backend, query=query, items=items, k=k)
    results = _canonical_search_results(raw_results, items, k)
    return {"method": "pageindex", "stale_index": stale, "results": results}

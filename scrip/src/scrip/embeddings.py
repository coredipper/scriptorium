"""Embeddings backend for the retrieval rung (rung 4 of the answer ladder).

This is an *optional adapter*, not part of the core contract. Install it with:

    uv tool install './scrip[embeddings]'      # or: pip install 'scrip[embeddings]'

If the backend (model2vec) is not installed, `available()` is False and callers
fall back to lexical grep — the vault stays fully valid either way. The index is
a regenerable cache under ``.kb/embeddings/``; it is never the source of truth.

Indexing is block-level (the same deterministic blocks the staleness engine
uses) and the index is stamped with a fingerprint of the raw content hashes, so
`scrip search` can warn when the index has drifted from the sources.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import blocks as blocks_mod
from . import hashing, raw_dir

MODEL_NAME = "minishlab/potion-base-8M"

# Bump when the block-id scheme or stored index layout changes, so an index built
# under an older scheme is detected as stale even when raw *content* is unchanged.
# 2: content-derived block ids (SPEC v2) — a v1 index held positional ids.
INDEX_SCHEMA = 2

_model = None
_model_tried = False


def _embeddings_dir(root: Path) -> Path:
    return root / ".kb" / "embeddings"


def _get_model():
    """Lazily load the static embedding model; cache it; return None if the
    backend or the model weights are unavailable (offline, not installed)."""
    global _model, _model_tried
    if _model_tried:
        return _model
    _model_tried = True
    import os

    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    try:
        from model2vec import StaticModel
    except Exception:
        return None
    try:
        _model = StaticModel.from_pretrained(MODEL_NAME)
    except Exception:
        _model = None
    return _model


def available() -> bool:
    return _get_model() is not None


def _iter_blocks(root: Path):
    for path in sorted(raw_dir(root).glob("*.md")):
        source_id = "raw/" + path.stem
        text = path.read_text(encoding="utf-8")
        for b in blocks_mod.split_blocks(text):
            s, e = b["span"]
            chunk = text[s:e].strip()
            if chunk:
                yield {
                    "source_id": source_id,
                    "block_id": b["block_id"],
                    "span": [s, e],
                    "text": chunk,
                }


def _fingerprint(root: Path) -> str:
    deps = {
        "raw/" + p.stem: hashing.content_hash_file(p)
        for p in sorted(raw_dir(root).glob("*.md"))
    }
    content = hashing.input_hash(deps) if deps else "sha256:empty"
    # Fold in the block-id scheme version: raw content alone is not enough, since
    # the v1→v2 switch changed block ids without changing any source bytes. An
    # index built under an older scheme therefore reads as stale (drift warned by
    # `scrip search`) instead of silently returning ids that no longer resolve.
    return hashing.sha256_text(f"schema:{INDEX_SCHEMA}\n{content}")


def build_index(root: Path) -> int:
    """Embed every raw block and persist vectors + metadata. Returns block count."""
    model = _get_model()
    if model is None:
        raise RuntimeError("no embeddings backend available")
    import numpy as np

    items = list(_iter_blocks(root))
    if items:
        embs = np.asarray(model.encode([it["text"] for it in items]), dtype="float32")
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = embs / norms
    else:
        vecs = np.zeros((0, 0), dtype="float32")

    d = _embeddings_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    np.save(d / "vectors.npy", vecs)
    (d / "meta.json").write_text(
        json.dumps(
            {"model": MODEL_NAME, "fingerprint": _fingerprint(root), "items": items},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return len(items)


def vector_search(root: Path, query: str, k: int = 5):
    """Return ``(results, index_is_stale)`` or ``None`` when there is no usable
    backend/index (so the caller can fall back to grep)."""
    model = _get_model()
    d = _embeddings_dir(root)
    if model is None or not (d / "vectors.npy").exists() or not (d / "meta.json").exists():
        return None
    import numpy as np

    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    items = meta["items"]
    vecs = np.load(d / "vectors.npy")
    stale = meta.get("fingerprint") != _fingerprint(root)
    if vecs.shape[0] == 0:
        return [], stale

    q = np.asarray(model.encode([query]), dtype="float32")[0]
    q = q / (float(np.linalg.norm(q)) or 1.0)
    sims = vecs @ q
    top = np.argsort(-sims)[:k]
    results = [
        {
            "source_id": items[i]["source_id"],
            "block_id": items[i]["block_id"],
            "score": float(sims[i]),
            "snippet": items[i]["text"][:200],
            "method": "embeddings",
        }
        for i in top
    ]
    return results, stale

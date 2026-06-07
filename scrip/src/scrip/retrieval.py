"""Rung 4 retrieval: find source blocks for an uncompiled question.

Prefers the embeddings index when present; otherwise falls back to lexical grep.
Either way the result is a list of source blocks to synthesize from — retrieval
locates sources, it does not answer.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import blocks as blocks_mod
from . import embeddings, raw_dir

_WORD = re.compile(r"\w+")


def grep_search(root: Path, query: str, k: int = 5) -> list[dict]:
    terms = [t for t in _WORD.findall(query.lower()) if t]
    hits: list[dict] = []
    for path in sorted(raw_dir(root).glob("*.md")):
        source_id = "raw/" + path.stem
        text = path.read_text(encoding="utf-8")
        for b in blocks_mod.split_blocks(text):
            s, e = b["span"]
            chunk = text[s:e]
            low = chunk.lower()
            score = sum(low.count(t) for t in terms)
            if score > 0:
                hits.append(
                    {
                        "source_id": source_id,
                        "block_id": b["block_id"],
                        "score": score,
                        "snippet": chunk.strip()[:200],
                        "method": "grep",
                    }
                )
    hits.sort(key=lambda r: -r["score"])
    return hits[:k]


def search(root: Path, query: str, k: int = 5) -> dict:
    """Return ``{method, stale_index, results}``."""
    v = embeddings.vector_search(root, query, k)
    if v is not None:
        results, stale = v
        return {"method": "embeddings", "stale_index": stale, "results": results}
    return {"method": "grep", "stale_index": False, "results": grep_search(root, query, k)}

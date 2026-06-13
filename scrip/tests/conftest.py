"""Shared test fixtures: a builder for synthetic scriptorium vaults.

The ``kb`` fixture yields a builder that writes a real on-disk vault under a
tmp dir, computing correct ``input-hash`` stamps so artifacts start fresh.
Tests then mutate sources and assert the dirty set. No network, no LLM.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scrip import anchors, blocks, frontmatter, hashing


class KB:
    def __init__(self, root: Path):
        self.root = root
        self.sources: dict[str, str] = {}

    # --- raw sources ------------------------------------------------------
    def add_raw(self, slug: str, text: str) -> str:
        (self.root / "vault" / "raw" / f"{slug}.md").write_text(text, encoding="utf-8")
        rid = f"raw/{slug}"
        self.sources[rid] = text
        return rid

    def block_id(self, slug: str, contains: str) -> str:
        """Return the block_id of the first block in ``raw/<slug>`` whose sliced
        text contains ``contains`` (for constructing block-scoped deps)."""
        text = self.sources[f"raw/{slug}"]
        for b in blocks.split_blocks(text):
            s, e = b["span"]
            if contains in text[s:e]:
                return b["block_id"]
        raise KeyError(f"no block containing {contains!r} in raw/{slug}")

    def _dep_hash(self, dep: str) -> str | None:
        """Resolve a (possibly block-scoped) dep id to its current hash, mirroring
        ``graph._dep_hash`` so fixture stamps match what status recomputes."""
        if "#" in dep:
            base, bid = dep.split("#", 1)
            text = self.sources.get(base)
            if text is None:
                return None
            for b in blocks.split_blocks(text):
                if b["block_id"] == bid:
                    return b["hash"]
            return None
        text = self.sources.get(dep)
        return hashing.sha256_bytes(text.encode("utf-8")) if text is not None else None

    def mutate_raw(self, slug: str, text: str) -> None:
        p = self.root / "vault" / "raw" / f"{slug}.md"
        p.write_text(text, encoding="utf-8")
        # Force a cache miss even if the edit lands within filesystem mtime
        # resolution, so cache-vs-no-cache stay equivalent in tests.
        st = p.stat()
        os.utime(p, (st.st_atime, st.st_mtime + 10))
        self.sources[f"raw/{slug}"] = text

    # --- derived artifacts -----------------------------------------------
    def add_wiki(
        self,
        slug: str,
        derived_from: list[str],
        *,
        stamp: bool = True,
        body: str = "Body.\n",
        title: str | None = None,
        kind: str = "concept",
    ) -> str:
        deps = {
            sid: h
            for sid in derived_from
            if (h := self._dep_hash(sid)) is not None
        }
        meta: dict = {
            "id": f"{kind}/{slug}",
            "type": f"wiki.{kind}",
            "title": title or slug,
            "derived-from": list(derived_from),
        }
        if stamp:
            meta["input-hash"] = hashing.input_hash(deps)
        meta["last-compiled"] = "2026-01-01T00:00:00Z"
        meta["confidence"] = 0.9
        subdir = "concepts" if kind == "concept" else "entities"
        path = self.root / "vault" / "wiki" / subdir / f"{slug}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(frontmatter.dump(meta, body), encoding="utf-8")
        return meta["id"]

    # --- facts / claims ---------------------------------------------------
    def add_claim_record(self, rec: dict) -> dict:
        p = self.root / "vault" / "facts" / "claims.ndjson"
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def add_claim(
        self,
        claim_id: str,
        source_slug: str,
        quote: str,
        *,
        anchor: str | None = None,
        subject: str = "s",
        predicate: str = "p",
        obj: str = "o",
        polarity: str = "asserts",
        tags: list[str] | None = None,
        confidence: float = 0.9,
    ) -> dict:
        sid = f"raw/{source_slug}"
        if anchor is None:
            anchor = anchors.make_anchor(self.sources[sid], quote)
        return self.add_claim_record(
            {
                "claim_id": claim_id,
                "source_id": sid,
                "anchor": anchor,
                "claim_text": quote,
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "polarity": polarity,
                "confidence": confidence,
                "tags": tags or [],
            }
        )


@pytest.fixture
def kb(tmp_path: Path) -> KB:
    root = tmp_path / "kb"
    for d in ("vault/raw", "vault/wiki/concepts", "vault/facts", ".kb"):
        (root / d).mkdir(parents=True)
    (root / "SPEC.md").write_text("marker\n", encoding="utf-8")
    return KB(root)

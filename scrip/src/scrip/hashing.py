"""Content hashing — the substrate of the dependency graph.

All hashes are namespaced strings ``sha256:<hexdigest>`` so they are
self-describing in the manifest and frontmatter.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping
from pathlib import Path


def normalize(text: str) -> str:
    """Canonical text normalization shared by provenance anchors and block ids.

    NFC → collapse every run of whitespace to a single space → strip ends →
    lowercase. Keeping one definition here (the leaf both ``anchors`` and
    ``blocks`` import) means anchor identity and block identity can never drift.
    """
    t = unicodedata.normalize("NFC", text)
    # Using split() and join() is significantly faster than regex for whitespace normalization
    return " ".join(t.split()).lower()


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return _digest(data)


def sha256_text(text: str) -> str:
    return _digest(text.encode("utf-8"))


def content_hash_file(path: str | Path) -> str:
    """Hash a raw source by its exact bytes.

    Raw sources are immutable, so the byte hash is the canonical identity. Any
    change to the bytes is, by definition, a new version that must propagate
    staleness to dependents.
    """
    return _digest(Path(path).read_bytes())


def input_hash(deps: Mapping[str, str]) -> str:
    """Compose a single hash from a dependency map ``{dep_id: content_hash}``.

    Sorting the ``"id:hash"`` pairs makes the result independent of the order in
    which dependencies are declared, so re-ordering a page's ``derived-from``
    never marks it stale. ``dep_id`` may be a source id (``raw/x``) or a
    block-scoped id (``raw/x#b3``).
    """
    parts = sorted(f"{dep_id}:{h}" for dep_id, h in deps.items())
    return sha256_text("\n".join(parts))

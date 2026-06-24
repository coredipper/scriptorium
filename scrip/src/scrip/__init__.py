"""scrip — the deterministic keeper of a scriptorium knowledge base.

The agent owns judgment (synthesis, extraction, reconciliation). ``scrip`` owns
only what LLMs are unreliable or expensive at: content hashing, staleness
detection over a dependency graph, provenance-anchor integrity, and structured
queries over the facts layer.

Files are the source of truth. Everything ``scrip`` computes is derivable from
the files on disk; ``.kb/manifest.json`` is only a speed cache.
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.6.0"

# --- canonical vault layout ------------------------------------------------
# ``root`` is the repo/instance root: the directory containing ``vault/``.
# The data layers live under ``vault/``; the manifest cache lives under ``.kb/``.


def vault_dir(root: Path) -> Path:
    return root / "vault"


def raw_dir(root: Path) -> Path:
    return root / "vault" / "raw"


def facts_dir(root: Path) -> Path:
    return root / "vault" / "facts"


def wiki_dir(root: Path) -> Path:
    return root / "vault" / "wiki"


def manifest_path(root: Path) -> Path:
    return root / ".kb" / "manifest.json"


def lock_path(root: Path) -> Path:
    return root / ".kb" / "lock"

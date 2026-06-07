"""The dependency-graph cache: ``.kb/manifest.json``.

This is a *cache, not a source of truth*. Everything in it is recomputable from
the files in ``vault/``. ``scrip`` reads it only to skip re-hashing unchanged
sources and to name which source changed; deleting it and rebuilding must yield
an identical dirty set (enforced by tests). Writes are atomic so a crash never
leaves a torn manifest.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import manifest_path

VERSION = 1


def load(root: Path) -> dict | None:
    """Return the cached manifest, or ``None`` on absent/corrupt/old cache
    (treated as a cache miss — never an error)."""
    p = manifest_path(root)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return None
    return data


def save(root: Path, data: dict) -> None:
    """Atomically write the manifest (tmp file + ``os.replace``)."""
    p = manifest_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp, p)  # atomic on POSIX


def build(raw: dict, derived: dict) -> dict:
    """Assemble a manifest dict from scanned raw + derived state."""
    return {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "raw": {
            rid: {
                "path": r["path"],
                "mtime": r["mtime"],
                "size": r["size"],
                "content_hash": r["content_hash"],
                "blocks": r["blocks"],
            }
            for rid, r in raw.items()
        },
        "derived": {
            did: {
                "path": d["path"],
                "type": d["type"],
                "derived_from": d["derived_from"],
                "input_hash": d["input_hash"],
                "last_compiled": d.get("last_compiled"),
            }
            for did, d in derived.items()
        },
    }

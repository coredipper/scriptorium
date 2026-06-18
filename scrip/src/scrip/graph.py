"""The dependency graph and the dirty-set computation behind ``scrip status``.

Staleness is decided entirely from files: for each derived artifact we recompose
the expected ``input-hash`` from the *current* hashes of its declared
dependencies and compare it to the stored one. A mismatch (or a vanished source,
or a missing stamp) means STALE. Raw sources nobody depends on are UNCOMPILED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import blocks as blocks_mod
from . import facts_dir, frontmatter, hashing, raw_dir, wiki_dir
from . import manifest as manifest_mod
from .errors import DataError


# --------------------------------------------------------------------------- #
# Scanning
# --------------------------------------------------------------------------- #
def scan_raw(root: Path, cache: dict | None = None, fast: bool = False) -> dict:
    """Hash every ``vault/raw/*.md`` source (+ its blocks) from its current bytes.

    By default hashing is **always** performed: status correctness must never
    depend on a cache that could hide a byte change (e.g. an edit that preserves
    both mtime and size). For small/medium vaults this is cheap.

    With ``fast=True`` and a cached entry whose ``(mtime, size)`` match the file,
    the cached ``content_hash``/``blocks`` are reused instead of re-reading and
    re-hashing — an opt-in acceleration that trades the always-re-hash guarantee
    for speed (an edit preserving both mtime and size is missed). See SPEC §8.
    """
    out: dict = {}
    rd = raw_dir(root)
    if not rd.is_dir():
        return out
    cache_raw = (cache or {}).get("raw", {}) if fast else {}
    for path in sorted(rd.glob("*.md")):
        rid = "raw/" + path.stem
        st = path.stat()
        prev = cache_raw.get(rid)
        if (
            fast
            and prev
            and prev.get("mtime") == st.st_mtime
            and prev.get("size") == st.st_size
            and prev.get("content_hash")
            and prev.get("blocks") is not None
        ):
            out[rid] = {
                "path": str(path.relative_to(root)),
                "content_hash": prev["content_hash"],
                "blocks": prev["blocks"],
                "mtime": st.st_mtime,
                "size": st.st_size,
            }
            continue
        data = path.read_bytes()
        out[rid] = {
            "path": str(path.relative_to(root)),
            "content_hash": hashing.sha256_bytes(data),
            "blocks": blocks_mod.split_blocks(data.decode("utf-8")),
            "mtime": st.st_mtime,
            "size": st.st_size,
        }
    return out


def scan_derived(root: Path) -> dict:
    """Collect derived artifacts: wiki pages declaring ``derived-from`` plus the
    ``facts/_meta.yaml`` set."""
    out: dict = {}
    wd = wiki_dir(root)
    if wd.is_dir():
        for path in sorted(wd.rglob("*.md")):
            meta, _ = frontmatter.load(path)
            if not meta or "derived-from" not in meta:
                continue  # index.md, log.md, hand notes: not tracked artifacts
            where = str(path.relative_to(root))
            did = frontmatter.as_str(meta, "id", where) or where
            out[did] = {
                "path": where,
                "type": frontmatter.as_str(meta, "type", where) or "wiki",
                "derived_from": frontmatter.as_str_list(meta, "derived-from", where),
                "input_hash": frontmatter.as_str(meta, "input-hash", where),
                "last_compiled": frontmatter.as_str(meta, "last-compiled", where),
            }
    fmeta = facts_dir(root) / "_meta.yaml"
    if fmeta.exists():
        try:
            data = yaml.safe_load(fmeta.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise DataError(f"invalid facts/_meta.yaml: {e}") from e
        if isinstance(data, dict) and "derived-from" in data:
            where = str(fmeta.relative_to(root))
            did = frontmatter.as_str(data, "id", where) or "facts/core"
            out[did] = {
                "path": where,
                "type": frontmatter.as_str(data, "type", where) or "facts.set",
                "derived_from": frontmatter.as_str_list(data, "derived-from", where),
                "input_hash": frontmatter.as_str(data, "input-hash", where),
                "last_compiled": frontmatter.as_str(data, "last-compiled", where),
            }
    return out


def _dep_hash(dep_id: str, raw: dict) -> str | None:
    """Resolve a dependency id to its current hash. ``raw/x`` -> file hash;
    ``raw/x#b3`` -> block hash. ``None`` if the source or block is gone."""
    if "#" in dep_id:
        base, block_id = dep_id.split("#", 1)
        r = raw.get(base)
        if not r:
            return None
        # ⚡ Bolt: Replace O(n) loop with O(1) hash map lookup for blocks
        if "_blocks_map" not in r:
            r["_blocks_map"] = {b["block_id"]: b["hash"] for b in r["blocks"]}
        return r["_blocks_map"].get(block_id)
    r = raw.get(dep_id)
    return r["content_hash"] if r else None


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
def compute_status(
    root: Path, use_cache: bool = True, rebuild: bool = False, fast: bool = False
) -> dict:
    # The cache annotates *which* source changed; by default staleness itself is
    # computed from freshly-hashed files (see scan_raw). ``fast`` additionally
    # lets scan_raw trust the cached hash when (mtime, size) match — but only when
    # the cache is in use: ``fast`` must never override ``use_cache=False``, or
    # ``--no-cache --fast`` would silently read the manifest it was told to ignore.
    cache = manifest_mod.load(root) if use_cache else None
    raw = scan_raw(root, cache=cache, fast=fast and use_cache)
    derived = scan_derived(root)

    # Which sources changed vs the cached hashes (best-effort annotation only).
    cache_raw = (cache or {}).get("raw", {})
    changed_raw: set[str] = set()
    for rid, r in raw.items():
        prev = cache_raw.get(rid)
        if prev is not None and prev.get("content_hash") != r["content_hash"]:
            changed_raw.add(rid)

    stale: list[dict] = []
    ok: list[dict] = []
    referenced: set[str] = set()

    for did, d in derived.items():
        deps: dict[str, str] = {}
        missing: list[str] = []
        for dep in d["derived_from"]:
            referenced.add(dep.split("#", 1)[0])
            h = _dep_hash(dep, raw)
            if h is None:
                missing.append(dep)
            else:
                deps[dep] = h

        if missing:
            reason = f"missing source(s): {', '.join(missing)}"
        elif not d["input_hash"]:
            reason = "no input-hash recorded (needs compile)"
        elif hashing.input_hash(deps) != d["input_hash"]:
            reason = "input-hash mismatch (source changed)"
        else:
            reason = None

        if reason:
            changed = sorted(
                {
                    dep.split("#", 1)[0]
                    for dep in d["derived_from"]
                    if dep.split("#", 1)[0] in changed_raw
                }
            )
            stale.append(
                {
                    "id": did,
                    "path": d["path"],
                    "reason": reason,
                    "changed_sources": changed,
                }
            )
        else:
            ok.append({"id": did, "path": d["path"]})

    uncompiled = [
        {"id": rid, "path": r["path"]}
        for rid, r in raw.items()
        if rid not in referenced
    ]

    if rebuild:
        manifest_mod.save(root, manifest_mod.build(raw, derived))

    return {
        "root": str(root),
        "stale": sorted(stale, key=lambda x: x["id"]),
        "ok": sorted(ok, key=lambda x: x["id"]),
        "uncompiled": sorted(uncompiled, key=lambda x: x["id"]),
    }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp_artifacts(root: Path, paths: list[str] | None = None) -> list[dict]:
    """Write the correct ``input-hash`` + ``last-compiled`` into derived files.

    This is the deterministic half of COMPILE: the agent authors the prose and
    declares ``derived-from``; ``scrip stamp`` records the provenance hash so it
    is always trustworthy. With no ``paths``, every derived artifact is stamped.
    """
    raw = scan_raw(root)
    derived = scan_derived(root)

    if paths:
        wanted = set()
        for p in paths:
            pp = Path(p)
            wanted.add(str(pp.relative_to(root)) if pp.is_absolute() else str(pp))
        targets = [(did, d) for did, d in derived.items() if d["path"] in wanted]
        missing = wanted - {d["path"] for _, d in targets}
        if missing:
            raise DataError(f"not a tracked derived artifact: {', '.join(sorted(missing))}")
    else:
        targets = list(derived.items())

    stamped: list[dict] = []
    now = _now()
    for did, d in targets:
        deps: dict[str, str] = {}
        for dep in d["derived_from"]:
            h = _dep_hash(dep, raw)
            if h is None:
                raise DataError(f"{d['path']}: cannot stamp; missing dependency {dep}")
            deps[dep] = h
        ih = hashing.input_hash(deps)
        path = root / d["path"]
        if path.name == "_meta.yaml":
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            data["input-hash"] = ih
            data["last-compiled"] = now
            path.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
        else:
            meta, body = frontmatter.load(path)
            meta["input-hash"] = ih
            meta["last-compiled"] = now
            path.write_text(frontmatter.dump(meta, body), encoding="utf-8")
        stamped.append({"id": did, "path": d["path"], "input_hash": ih})
    return stamped


def print_status(result: dict) -> None:
    stale, ok, unc = result["stale"], result["ok"], result["uncompiled"]
    if stale:
        print(f"STALE ({len(stale)})")
        for s in stale:
            tag = (
                f"  [changed: {', '.join(s['changed_sources'])}]"
                if s["changed_sources"]
                else ""
            )
            print(f"  ✗ {s['id']} — {s['reason']}{tag}")
    if unc:
        print(f"UNCOMPILED ({len(unc)})")
        for u in unc:
            print(f"  · {u['id']} ({u['path']})")
    print(f"OK ({len(ok)})")
    for o in ok:
        print(f"  ✓ {o['id']}")
    if not stale and not unc:
        print("all artifacts fresh.")

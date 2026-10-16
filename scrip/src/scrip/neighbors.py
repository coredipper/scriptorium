"""Focused neighborhood views over ``facts/graph.ndjson``.

``scrip query edges`` dumps the whole edge list; past a few dozen edges that is
the usual unreadable hairball. This module answers the narrower question "what
is connected to this one node, within N hops?" — deterministic, read-only, and
read through the same DuckDB lens as ``scrip query`` so the two cannot drift.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from . import facts_dir
from . import query as query_mod
from .errors import DataError, UsageError

MAX_DEPTH = 3
DIRECTIONS = ("both", "out", "in")


def _has_rows(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as f:
        return any(line.strip() for line in f)


def _load(root: Path, name: str, fname: str) -> list[dict]:
    # An absent or empty table is simply no rows: DuckDB has no view for it.
    if not _has_rows(facts_dir(root) / fname):
        return []
    _, rows = query_mod.run(root, name=name)
    return rows


def _node_summary(node: str, entity: dict | None) -> dict:
    out: dict = {"id": node}
    if entity:
        out["name"] = entity.get("name")
        out["kind"] = entity.get("kind")
    return out


def neighborhood(
    root: Path,
    node: str,
    *,
    depth: int = 1,
    kinds: list[str] | None = None,
    direction: str = "both",
    limit: int = 50,
) -> dict:
    """Return the edges within ``depth`` hops of ``node`` and the nodes they touch
    (entity name/kind when the node is an entity, else id only).

    Walks breadth-first; each edge is reported once, at the hop it is first
    reached. Order is deterministic: by hop, then ``src``, ``dst``, ``kind``.
    ``truncated`` is true when ``limit`` cut edges off."""
    if not 1 <= depth <= MAX_DEPTH:
        raise UsageError(f"--depth must be between 1 and {MAX_DEPTH}")
    if direction not in DIRECTIONS:
        raise UsageError(f"--direction must be one of: {', '.join(DIRECTIONS)}")
    if limit < 1:
        raise UsageError("--limit must be at least 1")

    entities = _load(root, "entities", "entities.ndjson")
    edges = _load(root, "edges", "graph.ndjson")
    entity_by_id = {
        str(e["entity_id"]): e for e in entities if isinstance(e.get("entity_id"), str)
    }
    wanted = set(kinds) if kinds else None

    out_adj: dict[str, list[int]] = {}
    in_adj: dict[str, list[int]] = {}
    known = set(entity_by_id)
    for i, e in enumerate(edges):
        src, dst = str(e.get("src") or ""), str(e.get("dst") or "")
        known.update((src, dst))
        if wanted is not None and e.get("kind") not in wanted:
            continue
        out_adj.setdefault(src, []).append(i)
        in_adj.setdefault(dst, []).append(i)
    if node not in known:
        raise DataError(f"no such node: {node}")

    seen_edges: set[int] = set()
    found: list[tuple[int, int]] = []  # (hop, edge index)
    visited = {node}
    frontier: deque[tuple[str, int]] = deque([(node, 0)])
    while frontier:
        cur, hop = frontier.popleft()
        if hop == depth:
            continue
        steps: list[tuple[int, str]] = []
        if direction in ("both", "out"):
            steps += [(i, str(edges[i].get("dst") or "")) for i in out_adj.get(cur, [])]
        if direction in ("both", "in"):
            steps += [(i, str(edges[i].get("src") or "")) for i in in_adj.get(cur, [])]
        for i, other in steps:
            if i not in seen_edges:
                seen_edges.add(i)
                found.append((hop + 1, i))
            if other not in visited:
                visited.add(other)
                frontier.append((other, hop + 1))

    def _key(item: tuple[int, int]) -> tuple:
        hop, i = item
        e = edges[i]
        return (hop, str(e.get("src") or ""), str(e.get("dst") or ""), str(e.get("kind") or ""))

    found.sort(key=_key)
    truncated = len(found) > limit
    found = found[:limit]

    out_edges: list[dict] = []
    touched = {node}
    for hop, i in found:
        e = edges[i]
        rec = {"src": e.get("src"), "dst": e.get("dst"), "kind": e.get("kind"), "hop": hop}
        for key in ("source_id", "anchor"):
            if e.get(key):
                rec[key] = e[key]
        out_edges.append(rec)
        touched.update((str(rec["src"]), str(rec["dst"])))

    return {
        "root": node,
        "depth": depth,
        "nodes": [_node_summary(n, entity_by_id.get(n)) for n in sorted(touched)],
        "edges": out_edges,
        "truncated": truncated,
    }


def print_neighborhood(result: dict) -> None:
    names = {n["id"]: n for n in result["nodes"]}
    root = result["root"]

    def _label(node: str) -> str:
        ent = names.get(node, {})
        bits = [ent.get("name") or "", f"({ent['kind']})" if ent.get("kind") else ""]
        return " ".join(b for b in bits if b)

    print(f"{root}  {_label(root)}".rstrip())
    rows = []
    for e in result["edges"]:
        src, dst = str(e["src"]), str(e["dst"])
        if src == root:
            arrow, other = "->", dst
        elif dst == root:
            arrow, other = "<-", src
        else:
            arrow, other = f"{src} ->", dst
        cite = f"  [cited {e['source_id']}#{e['anchor']}]" if e.get("anchor") else ""
        indent = "  " * e["hop"]
        rows.append(f"{indent}{arrow} {e['kind']}  {other}  {_label(other)}".rstrip() + cite)
    for line in rows:
        print(line)
    n_edges, n_nodes = len(result["edges"]), len(result["nodes"])
    more = " (truncated; raise --limit)" if result["truncated"] else ""
    print(
        f"{n_edges} edge{'s' if n_edges != 1 else ''}, "
        f"{n_nodes} node{'s' if n_nodes != 1 else ''} (depth {result['depth']}){more}"
    )

"""Deterministic pieces of the graph-drafting loop: the structured entity/edge
schema, prompt construction, entity-id slugging, and the NDJSON that
``scrip fact add --table entities|edges`` consumes. No network, no scrip —
unit-testable.

Unlike claims, entities and edges carry no provenance anchor (scrip's edge schema
is exactly ``src``/``dst``/``kind``), so there is no quote to machine-verify and no
retry loop. The honesty guard lives in the runner: an edge is dropped unless both
endpoints resolve to a real entity (drafted here or already on disk)."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel

GRAPH_SYSTEM = (
    "You are the scribe for a scriptorium knowledge base. From the single source "
    "you are given, draft the knowledge graph it describes as structured records.\n"
    "Rules:\n"
    "- Propose only entities and relationships the source supports; do not add "
    "outside knowledge.\n"
    "- An `entity` is a named thing (a tool, concept, person, system). Give a short "
    "`name` and a coarse `kind` (e.g. tool, concept, person, method). Reuse the "
    "exact same `name` for the same thing everywhere.\n"
    "- An `edge` is a typed relationship `src -> dst`. Both `src` and `dst` MUST be "
    "the `name` of an entity you also list; edges to anything else are discarded.\n"
    "- `kind` on an edge is a short lowercase relationship label (e.g. "
    "`alternative-to`, `part-of`, `builds-on`, `cites`).\n"
    "- Entities and edges are structural and uncited — keep them conservative and "
    "few; prefer omitting a relationship to guessing one."
)

# Conservative slug shape scrip enforces for entity ids: must start with an
# alphanumeric and contain only [A-Za-z0-9._-]. We additionally lowercase.
_NON_SLUG = re.compile(r"[^a-z0-9._-]+")
_TRIM_EDGES = re.compile(r"^[^a-z0-9]+|[^a-z0-9]+$")


class DraftEntity(BaseModel):
    name: str
    kind: str
    tags: list[str] = []


class DraftEdge(BaseModel):
    src: str
    """The `name` of the source entity (mapped to its entity id by the runner)."""
    dst: str
    """The `name` of the destination entity."""
    kind: str


class DraftGraph(BaseModel):
    entities: list[DraftEntity]
    edges: list[DraftEdge]


def slug(name: str) -> str:
    """Derive a scrip-valid entity slug from a free-text name: lowercase,
    whitespace and disallowed characters collapse to ``-``, and the result is
    trimmed to start and end on an alphanumeric. Returns ``""`` when nothing
    usable remains — the runner treats that as "skip this entity"."""
    s = re.sub(r"\s+", "-", name.strip().lower())
    s = _NON_SLUG.sub("-", s)
    s = re.sub(r"-{2,}", "-", s)
    return _TRIM_EDGES.sub("", s)


def entity_id(name: str) -> str:
    """``entity/<slug>`` for a name, or ``""`` if the name has no usable slug."""
    s = slug(name)
    return f"entity/{s}" if s else ""


def build_graph_prompt(source_text: str) -> str:
    return (
        "Draft the entities and the typed relationships among them from the source "
        "below. Every edge's `src`/`dst` must be the `name` of an entity you also "
        "list.\n\n----- SOURCE -----\n" + source_text
    )


def entities_to_ndjson(entities: list[DraftEntity]) -> str:
    """Serialize entities as ``scrip fact add --table entities --stdin`` expects.
    The entity id is minted from the name; empty ``tags`` are omitted so scrip
    applies its defaults. Callers must pre-filter entities whose name has no
    usable slug (see :func:`entity_id`)."""
    lines = []
    for e in entities:
        rec: dict = {"entity_id": entity_id(e.name), "name": e.name, "kind": e.kind}
        if e.tags:
            rec["tags"] = e.tags
        lines.append(json.dumps(rec, ensure_ascii=False))
    return "".join(line + "\n" for line in lines)


def edges_to_ndjson(edges: list[DraftEdge], name_to_id: dict[str, str]) -> str:
    """Serialize edges as ``scrip fact add --table edges --stdin`` expects, mapping
    each endpoint *name* to its entity id via ``name_to_id``. The edge schema is
    exactly ``src``/``dst``/``kind`` (scrip rejects any extra field). Callers must
    pre-filter edges whose endpoints are absent from ``name_to_id``."""
    lines = []
    for e in edges:
        rec = {"src": name_to_id[e.src], "dst": name_to_id[e.dst], "kind": e.kind}
        lines.append(json.dumps(rec, ensure_ascii=False))
    return "".join(line + "\n" for line in lines)

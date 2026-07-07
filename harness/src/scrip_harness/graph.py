"""Deterministic pieces of the graph-drafting loop: the structured entity/edge
schema, prompt construction, entity-id slugging, and the NDJSON that
``scrip fact add --table entities|edges`` consumes. No network, no scrip —
unit-testable.

Entities are structural (no anchor). An edge MAY be *cited*: if it carries a
verbatim ``quote``, scrip mints+verifies an anchor for it (``source_id`` + the
quote), exactly as for a claim; a bare edge stays ``src``/``dst``/``kind``. The
honesty guards live in the runner: an edge is dropped unless both endpoints
resolve to a real entity (drafted here or already on disk), and a cited edge whose
quote does not verify is degraded to a bare edge rather than failing the batch."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

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
    "- An edge MAY be *cited*: add a short, **verbatim** `quote` from the source that "
    "states the relationship, and scrip will anchor it. Copy the span exactly — never "
    "paraphrase or invent one. Omit `quote` when no single span states the relation; an "
    "unverifiable quote is simply dropped, leaving a structural edge.\n"
    "- Keep entities and edges conservative and few; prefer omitting a relationship to "
    "guessing one."
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
    quote: str = ""
    """Optional verbatim span from the source that states the relationship. When
    present, the edge is *cited* and scrip mints+verifies an anchor for it; an
    unverifiable quote is dropped (the edge degrades to bare)."""


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


def _ontology_guidance(ontology: Mapping[str, Any] | None) -> str:
    if not ontology or not ontology.get("active"):
        return ""
    lines = ["\n\nLOCAL ONTOLOGY:"]
    entity_kinds = ontology.get("entity_kinds") or []
    edge_kinds = ontology.get("edge_kinds") or []
    if entity_kinds:
        lines.append("- Use entity `kind` values only from: " + ", ".join(entity_kinds) + ".")
    if edge_kinds:
        lines.append("- Use edge `kind` values only from: " + ", ".join(edge_kinds) + ".")
    return "\n".join(lines)


def build_graph_prompt(source_text: str, ontology: Mapping[str, Any] | None = None) -> str:
    return (
        "Draft the entities and the typed relationships among them from the source "
        "below. Every edge's `src`/`dst` must be the `name` of an entity you also "
        "list. Where a single verbatim span states a relationship, copy it into the "
        "edge's `quote`; otherwise leave `quote` empty."
        + _ontology_guidance(ontology)
        + "\n\n----- SOURCE -----\n"
        + source_text
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


def edge_records(
    edges: list[DraftEdge], name_to_id: dict[str, str], source_id: str = ""
) -> list[dict]:
    """Build the edge records ``scrip fact add --table edges`` consumes, mapping
    each endpoint *name* to its entity id via ``name_to_id``. A bare edge is
    exactly ``src``/``dst``/``kind``; an edge with a non-blank ``quote`` (and a
    ``source_id`` to anchor against) is *cited* — it additionally carries the
    verbatim ``quote`` and ``source_id``. Callers must pre-filter edges whose
    endpoints are absent from ``name_to_id``."""
    records: list[dict] = []
    for e in edges:
        rec: dict = {"src": name_to_id[e.src], "dst": name_to_id[e.dst], "kind": e.kind}
        if source_id and e.quote.strip():
            rec["quote"] = e.quote
            rec["source_id"] = source_id
        records.append(rec)
    return records


def edges_to_ndjson(
    edges: list[DraftEdge], name_to_id: dict[str, str], source_id: str = ""
) -> str:
    """Serialize :func:`edge_records` as ``scrip fact add --table edges --stdin``
    expects (one JSON object per line)."""
    return "".join(
        json.dumps(rec, ensure_ascii=False) + "\n"
        for rec in edge_records(edges, name_to_id, source_id)
    )

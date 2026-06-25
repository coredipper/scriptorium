"""Structured queries over the facts layer, via DuckDB.

The ``facts/*.ndjson`` files are read directly as SQL views — no import step, no
database file, no sync. DuckDB is a pure query lens over the files, which stay
the source of truth and diff cleanly in git. Inverting MotherDuck: rather than
caching external tables *into* prose, we make the facts *extracted from* prose
queryable as data.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from . import facts_dir
from .errors import DataError, UsageError

# view name -> file under vault/facts/
_VIEWS = {
    "claims": "claims.ndjson",
    "entities": "entities.ndjson",
    "edges": "graph.ndjson",
    "reconciliations": "reconciliations.ndjson",
}

_NAMED = {
    "claims": "SELECT * FROM claims",
    "entities": "SELECT * FROM entities",
    "edges": "SELECT * FROM edges",
    "reconciliations": "SELECT * FROM reconciliations",
    # contradiction *candidates*: same subject+predicate, opposing polarity,
    # from different sources, AND not yet adjudicated (no reconciliation record
    # for the pair, either order) — so RECONCILE makes the set converge.
    # Detection is deterministic; adjudication is the agent's job.
    "contradictions": """
        SELECT a.claim_id AS claim_a, b.claim_id AS claim_b,
               a.subject, a.predicate,
               a.source_id AS source_a, b.source_id AS source_b
        FROM claims a
        JOIN claims b
          ON a.subject = b.subject AND a.predicate = b.predicate
        WHERE a.polarity = 'asserts'
          AND b.polarity = 'denies'
          AND a.source_id <> b.source_id
          AND NOT EXISTS (
            SELECT 1 FROM reconciliations r
            WHERE (r.claim_a = a.claim_id AND r.claim_b = b.claim_id)
               OR (r.claim_a = b.claim_id AND r.claim_b = a.claim_id)
          )
    """,
}

_FILTERABLE = {"claims", "entities", "edges", "reconciliations"}


def _create_empty_reconciliations_view(con: duckdb.DuckDBPyConnection) -> None:
    # Always present (empty stub) so `contradictions` can anti-join it and raw SQL
    # over its columns works even before any reconciliation exists.
    con.execute(
        "CREATE VIEW reconciliations AS SELECT "
        "NULL::VARCHAR AS reconciliation_id, NULL::VARCHAR AS decision, "
        "NULL::VARCHAR AS claim_a, NULL::VARCHAR AS claim_b, "
        "NULL::VARCHAR AS winner, NULL::VARCHAR AS rationale, "
        "NULL::VARCHAR AS at WHERE FALSE"
    )


def _has_rows(path: Path) -> bool:
    with path.open(encoding="utf-8") as f:
        return any(line.strip() for line in f)


def _connect(root: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    fd = facts_dir(root)
    for view, fname in _VIEWS.items():
        p = fd / fname
        if p.exists() and (view != "reconciliations" or _has_rows(p)):
            con.execute(
                f"CREATE VIEW {view} AS "
                f"SELECT * FROM read_ndjson_auto('{p.as_posix()}')"
            )
        elif view == "reconciliations":
            _create_empty_reconciliations_view(con)
    return con


def run(
    root: Path,
    *,
    name: str | None = None,
    sql: str | None = None,
    where: str | None = None,
    limit: int | None = None,
) -> tuple[list[str], list[dict]]:
    """Return ``(columns, rows)`` where ``rows`` is a list of JSON-able dicts."""
    con = _connect(root)
    try:
        if sql:
            query = sql
        elif name:
            if name not in _NAMED:
                raise UsageError(f"unknown named query: {name}")
            query = _NAMED[name]
            if where:
                if name not in _FILTERABLE:
                    raise UsageError(f"--where is not supported for '{name}'")
                if ";" in where:
                    raise UsageError("--where must be a single expression")
                query += f" WHERE {where}"
            if limit is not None:
                query += f" LIMIT {int(limit)}"
        else:
            raise UsageError("provide a named query or --sql")

        try:
            cur = con.execute(query)
        except duckdb.Error as e:
            raise DataError(f"query failed: {e}") from e

        columns = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(columns, r, strict=True)) for r in cur.fetchall()]
        return columns, rows
    finally:
        con.close()


def _fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def print_table(columns: list[str], rows: list[dict]) -> None:
    if not columns:
        print("(no result set)")
        return
    cells = [{c: _fmt(r.get(c)) for c in columns} for r in rows]
    widths = {c: len(c) for c in columns}
    for row in cells:
        for c in columns:
            widths[c] = max(widths[c], len(row[c]))
    print(" | ".join(c.ljust(widths[c]) for c in columns))
    print("-+-".join("-" * widths[c] for c in columns))
    for row in cells:
        print(" | ".join(row[c].ljust(widths[c]) for c in columns))
    print(f"({len(rows)} row{'s' if len(rows) != 1 else ''})")

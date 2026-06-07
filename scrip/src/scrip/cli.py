"""Command-line entry point for ``scrip``.

Dispatches to the four subcommands. Logic modules (``graph``, ``anchors``,
``query``) are imported lazily inside handlers so ``scrip --help`` works even
before those modules exist, and so importing the CLI never pulls in DuckDB
unless a query is actually run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, errors


# --------------------------------------------------------------------------- #
# Root resolution
# --------------------------------------------------------------------------- #
def resolve_root(root_arg: str | None) -> Path:
    """Return the scriptorium root.

    With ``--root`` the path is used verbatim (must be a directory). Otherwise we
    walk up from the cwd for the nearest ancestor that looks like an instance: a
    directory containing ``vault/`` plus either ``SPEC.md`` or ``.kb/``.
    """
    if root_arg:
        root = Path(root_arg).expanduser().resolve()
        if not root.is_dir():
            raise errors.UsageError(f"--root is not a directory: {root}")
        return root

    cur = Path.cwd().resolve()
    for cand in (cur, *cur.parents):
        if (cand / "vault").is_dir() and (
            (cand / "SPEC.md").exists() or (cand / ".kb").is_dir()
        ):
            return cand
    raise errors.UsageError(
        "could not locate a scriptorium root (looked for a parent with vault/ and "
        "SPEC.md or .kb/). Pass --root explicitly."
    )


def _emit(payload: dict) -> None:
    """Print a JSON payload as indented JSON (shared by handlers)."""
    print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Subcommand handlers  ->  return an int exit code
# --------------------------------------------------------------------------- #
def cmd_status(args: argparse.Namespace) -> int:
    from . import graph

    root = resolve_root(args.root)
    result = graph.compute_status(
        root, use_cache=not args.no_cache, rebuild=args.rebuild_manifest
    )
    if args.json:
        _emit(result)
    else:
        graph.print_status(result)
    return 1 if result["stale"] else 0


def cmd_verify(args: argparse.Namespace) -> int:
    from . import anchors

    root = resolve_root(args.root)
    result = anchors.verify_vault(root)
    if args.json:
        _emit(result)
    else:
        anchors.print_verify(result)
    failed = bool(result["broken"]) or (args.strict and bool(result["ambiguous"]))
    return 1 if failed else 0


def cmd_stamp(args: argparse.Namespace) -> int:
    from . import graph

    root = resolve_root(args.root)
    stamped = graph.stamp_artifacts(root, args.paths or None)
    if args.json:
        _emit({"stamped": stamped})
    else:
        for s in stamped:
            print(f"  stamped {s['id']}  ({s['input_hash'][:23]}…)")
        print(f"{len(stamped)} artifact(s) stamped")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    from . import query

    root = resolve_root(args.root)
    columns, rows = query.run(
        root,
        name=args.name,
        sql=args.sql,
        where=args.where,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(rows, default=str, ensure_ascii=False))
    else:
        query.print_table(columns, rows)
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from . import embeddings

    root = resolve_root(args.root)
    if not embeddings.available():
        msg = (
            "embeddings backend not installed; rung 4 falls back to grep. "
            "Enable it with:  uv tool install './scrip[embeddings]'  "
            "(or: pip install 'scrip[embeddings]')"
        )
        if args.json:
            _emit({"status": "unavailable", "message": msg})
        else:
            print(msg)
        return 0
    n = embeddings.build_index(root)
    if args.json:
        _emit({"status": "built", "blocks_indexed": n})
    else:
        print(f"indexed {n} block(s) into .kb/embeddings/")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from . import retrieval

    root = resolve_root(args.root)
    out = retrieval.search(root, args.query, k=args.k)
    if args.json:
        _emit(out)
    else:
        tag = out["method"] + (" — INDEX STALE, rebuild with `scrip index`" if out["stale_index"] else "")
        print(f"[{tag}] top {len(out['results'])} for: {args.query!r}")
        for r in out["results"]:
            score = f"{r['score']:.3f}" if isinstance(r["score"], float) else str(r["score"])
            print(f"  {r['source_id']}#{r['block_id']}  ({score})")
            print(f"    {r['snippet']}")
        if not out["results"]:
            print("  (no matches)")
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root", metavar="DIR", help="scriptorium root (default: auto-detect)"
    )
    common.add_argument(
        "--json", action="store_true", help="machine-readable JSON output"
    )

    p = argparse.ArgumentParser(
        prog="scrip",
        description="Deterministic keeper for an agent-compiled knowledge base: "
        "staleness, provenance integrity, and fact queries.",
    )
    p.add_argument("--version", action="version", version=f"scrip {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    ps = sub.add_parser(
        "status",
        parents=[common],
        help="report STALE / OK / UNCOMPILED artifacts from the dependency graph",
    )
    ps.add_argument(
        "--no-cache",
        action="store_true",
        help="ignore .kb/manifest.json; recompute everything from files",
    )
    ps.add_argument(
        "--rebuild-manifest",
        action="store_true",
        help="regenerate .kb/manifest.json from files after computing status",
    )
    ps.set_defaults(func=cmd_status)

    pv = sub.add_parser(
        "verify",
        parents=[common],
        help="check that every provenance anchor still resolves to its source",
    )
    pv.add_argument(
        "--strict",
        action="store_true",
        help="treat AMBIGUOUS anchors as failures too",
    )
    pv.set_defaults(func=cmd_verify)

    pst = sub.add_parser(
        "stamp",
        parents=[common],
        help="write correct input-hash + last-compiled into derived artifacts",
    )
    pst.add_argument(
        "paths",
        nargs="*",
        help="derived files to stamp (default: all tracked artifacts)",
    )
    pst.set_defaults(func=cmd_stamp)

    pq = sub.add_parser(
        "query",
        parents=[common],
        help="run a structured query over the facts/ layer (DuckDB)",
    )
    pq.add_argument(
        "name",
        nargs="?",
        choices=["claims", "entities", "edges", "contradictions"],
        help="a named query (omit when using --sql)",
    )
    pq.add_argument("--sql", help="raw DuckDB SQL (views: claims, entities, edges)")
    pq.add_argument("--where", help="SQL WHERE expression appended to a named query")
    pq.add_argument("--limit", type=int, help="row limit for a named query")
    pq.set_defaults(func=cmd_query)

    pi = sub.add_parser(
        "index",
        parents=[common],
        help="build the embeddings index over vault/raw/ (rung 4); no-op if backend absent",
    )
    pi.set_defaults(func=cmd_index)

    psr = sub.add_parser(
        "search",
        parents=[common],
        help="retrieve source blocks for a question (embeddings if indexed, else grep)",
    )
    psr.add_argument("query", help="the question / search text")
    psr.add_argument("-k", type=int, default=5, help="number of results (default 5)")
    psr.set_defaults(func=cmd_search)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except errors.ScripError as e:
        print(f"scrip: {e}", file=sys.stderr)
        return e.exit_code
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001 -- last-resort: map to exit code 4
        print(f"scrip: internal error: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())

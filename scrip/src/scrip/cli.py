"""Command-line entry point for ``scrip``.

Dispatches to the four subcommands. Logic modules (``graph``, ``anchors``,
``query``) are imported lazily inside handlers so ``scrip --help`` works even
before those modules exist, and so importing the CLI never pulls in DuckDB
unless a query is actually run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import __version__, errors

# A slug names a single path component (a source or page). Forbid anything that
# could escape its directory: path separators, '..', absolute paths, leading dot.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _safe_slug(slug: str, what: str = "slug") -> str:
    if not _SLUG_RE.match(slug):
        raise errors.UsageError(
            f"invalid {what} {slug!r}: use letters/digits/'.'/'_'/'-', "
            f"with no path separators, '..', or leading dot"
        )
    return slug


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
    # Ambiguous anchors fail by default: a citation that does not resolve
    # *uniquely* is a provenance weakness the protocol requires fixing.
    failed = bool(result["broken"]) or (
        not args.allow_ambiguous and bool(result["ambiguous"])
    )
    return 1 if failed else 0


def cmd_stamp(args: argparse.Namespace) -> int:
    from . import graph, lock

    root = resolve_root(args.root)
    with lock.write_lock(root):
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


def cmd_unlock(args: argparse.Namespace) -> int:
    from . import lock

    root = resolve_root(args.root)
    removed = lock.unlock(root, force=args.force)
    if args.json:
        _emit({"removed": removed})
    else:
        print("removed .kb/lock" if removed else "no lock to remove")
    return 0


def cmd_anchor(args: argparse.Namespace) -> int:
    from . import anchors

    root = resolve_root(args.root)
    source_id = args.source if args.source.startswith("raw/") else f"raw/{args.source}"
    _safe_slug(source_id[len("raw/") :], "source")
    text = anchors.source_text(root, source_id)
    anchor = anchors.make_anchor(text, args.quote)
    status = anchors.resolve(text, anchor)
    target = f"{source_id}#{anchor}"
    label = args.quote[:48].replace("\n", " ").strip()
    footnote = f'[^{args.label}]: anchor={target}  "{label}"'
    if args.json:
        _emit(
            {
                "source_id": source_id,
                "anchor": anchor,
                "target": target,
                "status": status,
                "label": args.label,
                "footnote": footnote,
            }
        )
    else:
        print(f"{target}   [{status}]")
        print(footnote)
    # Mirror `verify`: a citation must resolve to exactly one span. AMBIGUOUS or
    # BROKEN exits 1 so the agent lengthens the quote until unique.
    return 0 if status == "OK" else 1


def cmd_new(args: argparse.Namespace) -> int:
    from . import frontmatter, lock, raw_dir, wiki_dir

    root = resolve_root(args.root)
    _safe_slug(args.slug)
    raw_ids: list[str] = []
    for s in (s.strip() for s in args.sources.split(",")):
        if not s:
            continue
        sid = s if s.startswith("raw/") else f"raw/{s}"
        slug = sid.split("#", 1)[0][len("raw/") :]
        _safe_slug(slug, "source")
        if not (raw_dir(root) / f"{slug}.md").exists():
            raise errors.DataError(f"declared source does not exist: {sid}")
        raw_ids.append(sid)
    if not raw_ids:
        raise errors.UsageError("--from requires at least one source id")

    subdir = "concepts" if args.kind == "concept" else "entities"
    path = wiki_dir(root) / subdir / f"{args.slug}.md"

    meta = {
        "id": f"{args.kind}/{args.slug}",
        "type": f"wiki.{args.kind}",
        "title": args.title or args.slug,
        "derived-from": raw_ids,
        "confidence": 0.0,
    }
    body = (
        "<!-- Draft: synthesize from the sources in derived-from; cite each claim "
        "with a footnote anchor (`scrip anchor`), then `scrip stamp` + `scrip verify`. -->\n"
    )
    # Create exclusively *inside* the lock: the existence check and the write are
    # one atomic step, so two concurrent `new`s for the same slug can't both pass
    # an earlier check and clobber each other.
    with lock.write_lock(root):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "x", encoding="utf-8") as f:
                f.write(frontmatter.dump(meta, body))
        except FileExistsError:
            raise errors.UsageError(
                f"refusing to overwrite existing page: {path.relative_to(root)}"
            ) from None

    rel = str(path.relative_to(root))
    if args.json:
        _emit({"created": rel, "id": meta["id"]})
    else:
        print(f"created {rel}  (id {meta['id']})")
        print("  fill the body, cite with `scrip anchor`, then `scrip stamp` + `scrip verify`")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from . import ingest, lock

    root = resolve_root(args.root)
    slug = _safe_slug(args.slug or ingest.default_slug(args.source))
    data, kind, charset = ingest.fetch(args.source)
    text = ingest.extract_text(data, kind, charset)
    found = ingest.extract_metadata(data, kind, charset)
    meta = ingest.build_meta(
        source=args.source,
        title=args.title or found.get("title"),
        author=args.author or found.get("author"),
    )
    with lock.write_lock(root):
        written = ingest.write_source(root, slug, text, meta, overwrite=args.reingest)
    if args.json:
        _emit({"ingested": written["id"], "path": written["path"], "kind": kind})
    else:
        print(f"ingested {written['id']}  ({written['path']}, {kind})")
        print("  next: compile a page (`scrip new` + `scrip anchor`), then `scrip stamp`")
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
        "--allow-ambiguous",
        action="store_true",
        help="downgrade AMBIGUOUS anchors to a warning (default: they fail)",
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

    pul = sub.add_parser(
        "unlock",
        parents=[common],
        help="remove a stale .kb/lock (use --force to break a live one)",
    )
    pul.add_argument(
        "--force",
        action="store_true",
        help="remove the lock even if its holder still looks alive",
    )
    pul.set_defaults(func=cmd_unlock)

    pa = sub.add_parser(
        "anchor",
        parents=[common],
        help="mint a verified provenance anchor for a quote in a source",
    )
    pa.add_argument("quote", help="the exact quoted text, as it appears in the source")
    pa.add_argument(
        "--source",
        required=True,
        metavar="raw/<slug>",
        help="source id the quote is drawn from (the 'raw/' prefix is optional)",
    )
    pa.add_argument("--label", default="a1", help="footnote label (default: a1)")
    pa.set_defaults(func=cmd_anchor)

    pn = sub.add_parser(
        "new",
        parents=[common],
        help="scaffold a new wiki page (frontmatter only) for the agent to fill",
    )
    pn.add_argument("kind", choices=["concept", "entity"])
    pn.add_argument("slug", help="page slug, e.g. compilation-over-retrieval")
    pn.add_argument(
        "--from",
        dest="sources",
        required=True,
        metavar="raw/a,raw/b",
        help="comma-separated source ids for derived-from",
    )
    pn.add_argument("--title", help="human title (default: the slug)")
    pn.set_defaults(func=cmd_new)

    pin = sub.add_parser(
        "ingest",
        parents=[common],
        help="fetch/read a source, extract canonical text, write raw/<slug>.md + .meta.yaml",
    )
    pin.add_argument("source", help="a URL or a local file (.md/.txt/.html/.pdf)")
    pin.add_argument("--slug", help="vault slug (default: derived from the source name)")
    pin.add_argument("--title", help="bibliographic title for the .meta.yaml sidecar")
    pin.add_argument("--author", help="bibliographic author for the .meta.yaml sidecar")
    pin.add_argument(
        "--reingest",
        action="store_true",
        help="replace an existing raw source (a deliberate, tracked re-ingest)",
    )
    pin.set_defaults(func=cmd_ingest)

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

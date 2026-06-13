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
    # fullmatch (not match): `match` + `$` would accept a trailing newline, which
    # could split a `raw/<slug>#…` footnote target across lines.
    if not _SLUG_RE.fullmatch(slug):
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

    if args.fast and args.no_cache:
        raise errors.UsageError(
            "--fast cannot be combined with --no-cache: --fast reuses the manifest "
            "cache to skip re-hashing, which --no-cache disables"
        )
    root = resolve_root(args.root)
    result = graph.compute_status(
        root,
        use_cache=not args.no_cache,
        rebuild=args.rebuild_manifest,
        fast=args.fast,
    )
    if args.json:
        _emit(result)
    else:
        graph.print_status(result)
    return 1 if result["stale"] else 0


def _watch_summary(root: Path, fast: bool = False) -> dict:
    """One watch cycle: compute status + verify and return a counts summary.
    Factored out of the loop so it is unit-testable."""
    from . import anchors, graph

    status = graph.compute_status(root, fast=fast)
    verify = anchors.verify_vault(root)
    return {
        "stale": len(status["stale"]),
        "ok": len(status["ok"]),
        "broken": len(verify["broken"]),
        "ambiguous": len(verify["ambiguous"]),
    }


def cmd_watch(args: argparse.Namespace) -> int:
    import time
    from datetime import datetime, timezone

    from . import vault_dir

    root = resolve_root(args.root)
    vd = vault_dir(root)

    def signature() -> tuple:
        sig = []
        if vd.is_dir():
            for p in sorted(vd.rglob("*")):
                if p.is_file():
                    st = p.stat()
                    sig.append((str(p), st.st_mtime, st.st_size))
        return tuple(sig)

    print(f"watching {vd} every {args.interval}s — Ctrl-C to stop")
    last: tuple | None = None
    try:
        while True:
            sig = signature()
            if sig != last:
                last = sig
                stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                try:
                    s = _watch_summary(root, fast=args.fast)
                except errors.ScripError as e:
                    print(f"[{stamp}] data error: {e}")
                else:
                    clean = not (s["stale"] or s["broken"] or s["ambiguous"])
                    mark = "ok" if clean else "FINDINGS"
                    print(
                        f"[{stamp}] {mark} — stale={s['stale']} broken={s['broken']} "
                        f"ambiguous={s['ambiguous']} ok={s['ok']}"
                    )
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


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
            "Enable it with:  uv tool install 'scriptoria[embeddings]'  "
            "(or: pip install 'scriptoria[embeddings]')"
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


def _parse_source_ids(raw: str) -> list[str]:
    """Parse a comma-separated `--from` value into validated source ids, WITHOUT
    requiring the sources to exist (unlike `cmd_new`): scoring a not-yet-ingested
    proposed topic is legitimate. Keeps the traversal-safety check."""
    ids: list[str] = []
    for s in (part.strip() for part in raw.split(",")):
        if not s:
            continue
        sid = s if s.startswith("raw/") else f"raw/{s}"
        _safe_slug(sid.split("#", 1)[0][len("raw/") :], "source")
        ids.append(sid)
    if not ids:
        raise errors.UsageError("--from requires at least one source id")
    return ids


def cmd_similar(args: argparse.Namespace) -> int:
    from . import similar

    root = resolve_root(args.root)
    sources = _parse_source_ids(args.sources)
    result = similar.compute_similar(
        root,
        title=args.title,
        sources=sources,
        kind=args.kind,
        exclude=set(args.exclude),
        top=args.top,
    )
    if args.json:
        _emit(result)
    else:
        similar.print_similar(result)
    return 0


def cmd_fact_add(args: argparse.Namespace) -> int:
    from . import facts

    root = resolve_root(args.root)
    if args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            raise errors.UsageError(f"cannot read --file: {e}") from e
    else:
        text = sys.stdin.read()
    result = facts.add(root, args.table, facts.parse_ndjson(text))
    if args.json:
        _emit(result)
    else:
        for r in result["appended"]:
            ident = r.get("claim_id") or r.get("entity_id") or f"{r['src']} -> {r['dst']}"
            print(f"  appended {ident}")
        for s in result["skipped"]:
            print(f"  = record {s['index']} skipped (duplicate)")
        for f in result["failures"]:
            print(f"  ✗ record {f['index']}: {f['status']} — {f['detail']}")
        if result["failures"]:
            print(
                f"nothing appended: {len(result['failures'])} record(s) failed "
                f"(the batch is all-or-nothing)"
            )
        else:
            print(f"{len(result['appended'])} record(s) appended to facts/")
            if result["appended"]:
                print("  next: `scrip stamp vault/facts/_meta.yaml`, then `scrip verify`")
    return 1 if result["failures"] else 0


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
    ps.add_argument(
        "--fast",
        action="store_true",
        help="trust (mtime,size) to skip re-hashing unchanged sources — faster, but "
        "can miss an edit that preserves both (SPEC §8); plain status always re-hashes",
    )
    ps.set_defaults(func=cmd_status)

    pw = sub.add_parser(
        "watch",
        parents=[common],
        help="re-run status + verify whenever the vault changes (poll loop)",
    )
    pw.add_argument(
        "--interval", type=float, default=2.0, help="poll interval in seconds (default 2)"
    )
    pw.add_argument(
        "--fast", action="store_true", help="use the --fast status path while watching"
    )
    pw.set_defaults(func=cmd_watch)

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

    psim = sub.add_parser(
        "similar",
        parents=[common],
        help="score existing wiki pages by topic overlap with a proposed page (PROMOTE step 1)",
    )
    psim.add_argument(
        "--title", required=True, help="proposed page title (tokenized for title overlap)"
    )
    psim.add_argument(
        "--from",
        dest="sources",
        required=True,
        metavar="raw/a,raw/b",
        help="comma-separated source ids the proposed page would derive from",
    )
    psim.add_argument(
        "--kind",
        choices=["concept", "entity"],
        default="concept",
        help="score only candidates of this kind (default: concept)",
    )
    psim.add_argument(
        "--exclude",
        metavar="ID",
        action="append",
        default=[],
        help="page id to skip (repeatable); use when re-scoring an existing page",
    )
    psim.add_argument("--top", type=int, metavar="N", help="limit to the N highest-scoring candidates")
    psim.set_defaults(func=cmd_similar)

    pfact = sub.add_parser(
        "fact",
        help="validated writers for the facts/ layer (claims mint verified anchors)",
    )
    fact_sub = pfact.add_subparsers(dest="fact_command", required=True, metavar="<action>")
    pfa = fact_sub.add_parser(
        "add",
        parents=[common],
        help="validate proposed NDJSON records and append them all-or-nothing; "
        "claims carry a verbatim `quote` and scrip mints the anchor/id/timestamp",
    )
    pfa.add_argument(
        "--table",
        choices=["claims", "entities", "edges"],
        default="claims",
        help="facts table to append to (default: claims)",
    )
    fact_in = pfa.add_mutually_exclusive_group(required=True)
    fact_in.add_argument("--file", metavar="NDJSON", help="read proposed records from a file")
    fact_in.add_argument(
        "--stdin", action="store_true", help="read proposed records from stdin"
    )
    pfa.set_defaults(func=cmd_fact_add)

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

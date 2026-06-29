"""``scrip-harness compile|extract <slug>`` — run the AGENT.md COMPILE or
EXTRACT step for one source.

This is the model-driven entry point. It resolves the scriptorium root, calls
a configured model provider to draft the page or the claims, and hands every
verifiable step to ``scrip``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast


def _resolve_root(root_arg: str | None) -> Path:
    if root_arg:
        return Path(root_arg).expanduser()
    cur = Path.cwd().resolve()
    for cand in (cur, *cur.parents):
        if (cand / "vault").is_dir() and ((cand / "SPEC.md").exists() or (cand / ".kb").is_dir()):
            return cand
    raise SystemExit("scrip-harness: could not locate a scriptorium root; pass --root")


def _normalize_sources(raw: str) -> list[str]:
    """Split a comma-separated ``--from`` value into normalized ``raw/<slug>`` ids:
    strip whitespace around each part *before* the ``raw/`` prefix check, and drop
    empty parts. An all-empty value yields ``[]`` (the caller rejects it)."""
    return [
        p if p.startswith("raw/") else f"raw/{p}"
        for p in (part.strip() for part in raw.split(","))
        if p
    ]


def _add_model_args(parser: argparse.ArgumentParser, *, include_provider: bool = True) -> None:
    if include_provider:
        parser.add_argument(
            "--provider",
            choices=["auto", "anthropic", "openai", "gemini"],
            default="auto",
            help="model provider (default: auto; checks Anthropic, OpenAI, then Gemini keys)",
        )
    parser.add_argument(
        "--model",
        help="provider model id (default: provider-specific; override with this flag)",
    )
    parser.add_argument(
        "--api-key-file",
        help=(
            "provider API key file. Defaults include ~/veed/var/openai for OpenAI "
            "and ~/veed/var/gemini for Gemini"
        ),
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="scrip-harness",
        description="Runnable scriptorium compile loop (drives scrip + Claude).",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")
    pc = sub.add_parser(
        "compile",
        help="synthesize wiki/<kind>s/<slug> from raw/<slug> (or several --from "
        "sources) via a model provider, then stamp + verify",
    )
    pc.add_argument("slug")
    pc.add_argument("--kind", choices=["concept", "entity"], default="concept")
    pc.add_argument(
        "--from", dest="sources", metavar="raw/a,raw/b",
        help="comma-separated source ids to synthesize the page from "
        "(default: raw/<slug>)",
    )
    pc.add_argument("--root")
    _add_model_args(pc)
    pe = sub.add_parser(
        "extract",
        help="extract claims from raw/<slug> (or several --from sources) into facts/ "
        "via a model provider (anchors minted and verified by `scrip fact add`), "
        "then stamp + verify",
    )
    pe.add_argument("slug")
    pe.add_argument(
        "--from", dest="sources", metavar="raw/a,raw/b",
        help="comma-separated source ids to extract claims from (default: raw/<slug>); "
        "each claim is attributed to one of them",
    )
    pe.add_argument("--root")
    _add_model_args(pe)
    pg = sub.add_parser(
        "graph",
        help="draft entities + edges from raw/<slug> into facts/ via a model "
        "provider (validated by `scrip fact add --table entities|edges`), then "
        "stamp + verify",
    )
    pg.add_argument("slug")
    pg.add_argument("--root")
    _add_model_args(pg)
    pp = sub.add_parser(
        "promote",
        help="score a compiled page against existing pages (`scrip similar`) and "
        "merge it into the best match or keep it — model used only in the middle band",
    )
    pp.add_argument("slug")
    pp.add_argument("--kind", choices=["concept", "entity"], default="concept")
    pp.add_argument("--root")
    _add_model_args(pp)
    pp.add_argument(
        "--merge-threshold", type=float, default=0.5,
        help="combined score at/above which to merge without asking the model (default 0.5)",
    )
    pp.add_argument(
        "--keep-threshold", type=float, default=0.25,
        help="combined score below which to keep the page as-is (default 0.25)",
    )
    pp.add_argument(
        "--dry-run", action="store_true",
        help="report the decision without mutating any page",
    )
    pp.add_argument(
        "--resynthesize", action="store_true",
        help="on merge, re-draft the target as one coherent page over the union of "
        "both pages' sources (re-mints anchors) instead of appending the absorbed body",
    )
    prc = sub.add_parser(
        "reconcile",
        help="adjudicate every open contradiction via a model provider and record the "
        "decisions (`scrip fact add --table reconciliations`), then re-verify",
    )
    prc.add_argument("--root")
    _add_model_args(prc)
    prc.add_argument(
        "--dry-run", action="store_true", help="report decisions without recording them"
    )
    pa = sub.add_parser(
        "answer",
        help="answer a question from fresh wiki/facts first, falling back to raw search; "
        "all citations are verified by scrip",
    )
    pa.add_argument("question")
    pa.add_argument("--root")
    _add_model_args(pa)
    pa.add_argument("-k", type=int, default=6, help="evidence items per layer (default 6)")
    pa.add_argument(
        "--save",
        action="store_true",
        help="save the answer to vault/wiki/explorations/ after verification",
    )
    pa.add_argument(
        "--allow-stale",
        action="store_true",
        help="answer even when scrip status reports stale artifacts",
    )
    pa.add_argument(
        "--allow-open-contradictions",
        action="store_true",
        help="answer even when scrip query contradictions returns open pairs",
    )
    args = p.parse_args(argv)

    from . import model as model_mod
    from .runner import (
        AnswerError,
        CompileError,
        ExtractError,
        GraphError,
        PromoteError,
        ReconcileError,
        answer_question,
        compile_page,
        draft_graph_facts,
        extract_facts,
        promote_page,
        reconcile_contradictions,
    )

    root = _resolve_root(args.root)
    chosen_model = args.model
    chosen_provider = cast(model_mod.Provider, getattr(args, "provider", "auto"))
    api_key_file = cast(str | None, getattr(args, "api_key_file", None))

    if args.command == "answer":
        def answer_draft_fn(question: str, *, evidence: dict):
            return model_mod.draft_answer(
                question,
                evidence=evidence,
                provider=chosen_provider,
                model=chosen_model,
                api_key_file=api_key_file,
            )

        try:
            result = answer_question(
                root,
                args.question,
                draft_fn=answer_draft_fn,
                k=args.k,
                save=args.save,
                allow_stale=args.allow_stale,
                allow_open_contradictions=args.allow_open_contradictions,
            )
        except (AnswerError, RuntimeError) as e:
            print(f"scrip-harness: {e}", file=sys.stderr)
            return 1
        print(result["answer"].rstrip())
        if result["saved"]:
            print(f"\nsaved {result['saved']}")
        return 0

    if args.command == "reconcile":
        def reconcile_decide_fn(pair, span_a, span_b):
            return model_mod.decide_reconciliation(
                pair,
                span_a,
                span_b,
                provider=chosen_provider,
                model=chosen_model,
                api_key_file=api_key_file,
            )

        try:
            result = reconcile_contradictions(
                root, decide_fn=reconcile_decide_fn, dry_run=args.dry_run
            )
        except (ReconcileError, RuntimeError) as e:
            print(f"scrip-harness: {e}", file=sys.stderr)
            return 1
        if result["pairs"] == 0:
            print("no open contradictions")
        elif result.get("dry_run"):
            print(f"{result['pairs']} contradiction(s) — decisions (dry run):")
            for d in result["decisions"]:
                tail = f" → {d['winner']}" if d["decision"] == "supersede" else ""
                print(f"  {d['decision']}: {d['claim_a']} vs {d['claim_b']}{tail}")
        else:
            msg = f"reconciled {len(result['reconciled'])} of {result['pairs']} contradiction(s)"
            if result.get("qualified"):
                msg += f"; authored {len(result['qualified'])} qualifies claim(s)"
            print(msg)
        return 0

    if args.command == "promote":
        def decide_fn(candidate_text: str, candidates: list[dict]):
            return model_mod.decide_promotion(
                candidate_text,
                candidates,
                provider=chosen_provider,
                model=chosen_model,
                api_key_file=api_key_file,
            )

        # only --resynthesize needs a drafter (re-drafting the merged page); the
        # default append merge is deterministic and uses no model.
        promote_draft_fn = None
        if args.resynthesize:
            def _resynth_draft(text: str, *, source_id: str, failures=None):
                return model_mod.draft_page(
                    text,
                    source_id=source_id,
                    provider=chosen_provider,
                    model=chosen_model,
                    failures=failures,
                    api_key_file=api_key_file,
                )

            promote_draft_fn = _resynth_draft

        try:
            result = promote_page(
                root, args.slug, kind=args.kind, decide_fn=decide_fn,
                draft_fn=promote_draft_fn, resynthesize=args.resynthesize,
                merge_threshold=args.merge_threshold, keep_threshold=args.keep_threshold,
                dry_run=args.dry_run,
            )
        except (PromoteError, RuntimeError) as e:
            print(f"scrip-harness: {e}", file=sys.stderr)
            return 1
        if result["action"] == "merge":
            verb = "would merge" if result.get("dry_run") else (
                "resynthesized" if result.get("resynthesized") else "merged"
            )
            print(f"{verb} {args.kind}/{args.slug} into {result['target']}")
        else:
            print(f"kept {args.kind}/{args.slug} as its own page ({result.get('reason', '')})")
        return 0

    if args.command == "extract":
        def extract_draft_fn(text: str, *, source_id: str, failures=None):
            return model_mod.draft_extraction(
                text,
                source_id=source_id,
                provider=chosen_provider,
                model=chosen_model,
                failures=failures,
                api_key_file=api_key_file,
            )

        extract_sources = None
        if args.sources is not None:
            extract_sources = _normalize_sources(args.sources)
            if not extract_sources:
                print(
                    "scrip-harness: --from was given but lists no source ids",
                    file=sys.stderr,
                )
                return 1
        try:
            result = extract_facts(
                root, args.slug, sources=extract_sources, draft_fn=extract_draft_fn
            )
        except (ExtractError, RuntimeError) as e:
            print(f"scrip-harness: {e}", file=sys.stderr)
            return 1
        appended, skipped = result["appended"], result["skipped"]
        src_label = ",".join(extract_sources) if extract_sources else f"raw/{args.slug}"
        print(
            f"extracted {len(appended)} claim(s) from {src_label}  (verified"
            f"{f', {len(skipped)} duplicate(s) skipped' if skipped else ''})"
        )
        if result["contradictions"]:
            print(
                f"  {len(result['contradictions'])} contradiction candidate(s) — "
                f"run `scrip query contradictions` and RECONCILE per AGENT.md"
            )
        return 0

    if args.command == "graph":
        def graph_draft_fn(text: str, *, source_id: str):
            return model_mod.draft_graph(
                text,
                source_id=source_id,
                provider=chosen_provider,
                model=chosen_model,
                api_key_file=api_key_file,
            )

        try:
            result = draft_graph_facts(root, args.slug, draft_fn=graph_draft_fn)
        except (GraphError, RuntimeError) as e:
            print(f"scrip-harness: {e}", file=sys.stderr)
            return 1
        n_ent = len(result["entities"]["appended"])
        n_edge = len(result["edges"]["appended"])
        print(
            f"drafted {n_ent} entit{'y' if n_ent == 1 else 'ies'} and {n_edge} "
            f"edge(s) from raw/{args.slug}  (verified)"
        )
        extras = []
        if result["dropped_edges"]:
            extras.append(f"{len(result['dropped_edges'])} edge(s) dropped (unknown endpoint)")
        if result["skipped_entities"]:
            extras.append(f"{len(result['skipped_entities'])} entity name(s) skipped (no slug)")
        if extras:
            print("  " + "; ".join(extras))
        return 0

    def draft_fn(text: str, *, source_id: str, failures=None):
        return model_mod.draft_page(
            text,
            source_id=source_id,
            provider=chosen_provider,
            model=chosen_model,
            failures=failures,
            api_key_file=api_key_file,
        )

    compile_sources = None
    if args.sources is not None:
        compile_sources = _normalize_sources(args.sources)
        if not compile_sources:
            print(
                "scrip-harness: --from was given but lists no source ids",
                file=sys.stderr,
            )
            return 1
    try:
        page = compile_page(
            root, args.slug, kind=args.kind, sources=compile_sources, draft_fn=draft_fn
        )
    except (CompileError, RuntimeError) as e:
        print(f"scrip-harness: {e}", file=sys.stderr)
        return 1
    print(f"compiled {page.relative_to(root)}  (verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

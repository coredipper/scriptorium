"""``scrip-harness compile|extract <slug>`` — run the AGENT.md COMPILE or
EXTRACT step for one source.

This is the model-driven entry point. It resolves the scriptorium root, calls
Claude to draft the page or the claims, and hands every verifiable step to
``scrip``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _resolve_root(root_arg: str | None) -> Path:
    if root_arg:
        return Path(root_arg).expanduser()
    cur = Path.cwd().resolve()
    for cand in (cur, *cur.parents):
        if (cand / "vault").is_dir() and ((cand / "SPEC.md").exists() or (cand / ".kb").is_dir()):
            return cand
    raise SystemExit("scrip-harness: could not locate a scriptorium root; pass --root")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="scrip-harness",
        description="Runnable scriptorium compile loop (drives scrip + Claude).",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")
    pc = sub.add_parser(
        "compile",
        help="synthesize wiki/<kind>s/<slug> from raw/<slug> via Claude, then stamp + verify",
    )
    pc.add_argument("slug")
    pc.add_argument("--kind", choices=["concept", "entity"], default="concept")
    pc.add_argument("--root")
    pc.add_argument("--model", help="Claude model id (default: claude-opus-4-8)")
    pe = sub.add_parser(
        "extract",
        help="extract claims from raw/<slug> into facts/ via Claude (anchors minted "
        "and verified by `scrip fact add`), then stamp + verify",
    )
    pe.add_argument("slug")
    pe.add_argument("--root")
    pe.add_argument("--model", help="Claude model id (default: claude-opus-4-8)")
    pp = sub.add_parser(
        "promote",
        help="score a compiled page against existing pages (`scrip similar`) and "
        "merge it into the best match or keep it — model used only in the middle band",
    )
    pp.add_argument("slug")
    pp.add_argument("--kind", choices=["concept", "entity"], default="concept")
    pp.add_argument("--root")
    pp.add_argument("--model", help="Claude model id (default: claude-opus-4-8)")
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
    prc = sub.add_parser(
        "reconcile",
        help="adjudicate every open contradiction via Claude and record the "
        "decisions (`scrip fact add --table reconciliations`), then re-verify",
    )
    prc.add_argument("--root")
    prc.add_argument("--model", help="Claude model id (default: claude-opus-4-8)")
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
    pa.add_argument("--model", help="Claude model id (default: claude-opus-4-8)")
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
        PromoteError,
        ReconcileError,
        answer_question,
        compile_page,
        extract_facts,
        promote_page,
        reconcile_contradictions,
    )

    root = _resolve_root(args.root)
    chosen_model = args.model or model_mod.DEFAULT_MODEL

    if args.command == "answer":
        def answer_draft_fn(question: str, *, evidence: dict):
            return model_mod.draft_answer(question, evidence=evidence, model=chosen_model)

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
        except AnswerError as e:
            print(f"scrip-harness: {e}", file=sys.stderr)
            return 1
        print(result["answer"].rstrip())
        if result["saved"]:
            print(f"\nsaved {result['saved']}")
        return 0

    if args.command == "reconcile":
        def reconcile_decide_fn(pair, span_a, span_b):
            return model_mod.decide_reconciliation(pair, span_a, span_b, model=chosen_model)

        try:
            result = reconcile_contradictions(
                root, decide_fn=reconcile_decide_fn, dry_run=args.dry_run
            )
        except ReconcileError as e:
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
            print(f"reconciled {len(result['reconciled'])} of {result['pairs']} contradiction(s)")
        return 0

    if args.command == "promote":
        def decide_fn(candidate_text: str, candidates: list[dict]):
            return model_mod.decide_promotion(candidate_text, candidates, model=chosen_model)

        try:
            result = promote_page(
                root, args.slug, kind=args.kind, decide_fn=decide_fn,
                merge_threshold=args.merge_threshold, keep_threshold=args.keep_threshold,
                dry_run=args.dry_run,
            )
        except PromoteError as e:
            print(f"scrip-harness: {e}", file=sys.stderr)
            return 1
        if result["action"] == "merge":
            verb = "would merge" if result.get("dry_run") else "merged"
            print(f"{verb} {args.kind}/{args.slug} into {result['target']}")
        else:
            print(f"kept {args.kind}/{args.slug} as its own page ({result.get('reason', '')})")
        return 0

    if args.command == "extract":
        def extract_draft_fn(text: str, *, source_id: str, failures=None):
            return model_mod.draft_extraction(
                text, source_id=source_id, model=chosen_model, failures=failures
            )

        try:
            result = extract_facts(root, args.slug, draft_fn=extract_draft_fn)
        except ExtractError as e:
            print(f"scrip-harness: {e}", file=sys.stderr)
            return 1
        appended, skipped = result["appended"], result["skipped"]
        print(
            f"extracted {len(appended)} claim(s) from raw/{args.slug}  (verified"
            f"{f', {len(skipped)} duplicate(s) skipped' if skipped else ''})"
        )
        if result["contradictions"]:
            print(
                f"  {len(result['contradictions'])} contradiction candidate(s) — "
                f"run `scrip query contradictions` and RECONCILE per AGENT.md"
            )
        return 0

    def draft_fn(text: str, *, source_id: str, failures=None):
        return model_mod.draft_page(
            text, source_id=source_id, model=chosen_model, failures=failures
        )

    try:
        page = compile_page(root, args.slug, kind=args.kind, draft_fn=draft_fn)
    except CompileError as e:
        print(f"scrip-harness: {e}", file=sys.stderr)
        return 1
    print(f"compiled {page.relative_to(root)}  (verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

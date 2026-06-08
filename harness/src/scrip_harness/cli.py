"""``scrip-harness compile <slug>`` — run the AGENT.md COMPILE step for one source.

This is the model-driven entry point. It resolves the scriptorium root, calls
Claude to draft the page, and hands every verifiable step to ``scrip``.
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
    args = p.parse_args(argv)

    from . import model as model_mod
    from .runner import CompileError, compile_page

    root = _resolve_root(args.root)
    chosen_model = args.model or model_mod.DEFAULT_MODEL

    def draft_fn(text: str, *, source_id: str):
        return model_mod.draft_page(text, source_id=source_id, model=chosen_model)

    try:
        page = compile_page(root, args.slug, kind=args.kind, draft_fn=draft_fn)
    except CompileError as e:
        print(f"scrip-harness: {e}", file=sys.stderr)
        return 1
    print(f"compiled {page.relative_to(root)}  (verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

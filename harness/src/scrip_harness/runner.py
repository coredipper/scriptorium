"""Orchestrate one COMPILE: draft via a model, then mint verified anchors, scaffold,
stamp, and verify via ``scrip`` subprocesses. ``scrip`` stays the deterministic
source of truth — this never re-implements hashing, anchoring, or staleness."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from scrip import frontmatter  # reuse the deterministic frontmatter helper

from .compile import DraftPage, assemble_body

DraftFn = Callable[..., DraftPage]


class CompileError(RuntimeError):
    """A compile step failed (a quote didn't resolve, or a scrip command erred)."""


def _scrip(cmd: Sequence[str], args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([*cmd, *args], capture_output=True, text=True)


def compile_page(
    root,
    slug: str,
    *,
    kind: str = "concept",
    draft_fn: DraftFn,
    scrip_cmd: Sequence[str] = ("scrip",),
) -> Path:
    """Compile ``raw/<slug>`` into ``wiki/<kind>s/<slug>.md`` and leave it green.

    ``draft_fn(source_text, source_id=...)`` returns a :class:`DraftPage` — inject
    a stub in tests; production passes ``model.draft_page``. Raises
    :class:`CompileError` if any quote fails to resolve or any scrip step errors,
    so a bad draft never produces a stamped-but-broken page."""
    root = Path(root)
    source_id = f"raw/{slug}"
    source_text = (root / "vault" / "raw" / f"{slug}.md").read_text(encoding="utf-8")
    draft = draft_fn(source_text, source_id=source_id)

    # Mint a verified anchor per claim. scrip anchor exits non-zero on a quote that
    # is not present or not unique, so a hallucinated quote fails the compile here.
    footnotes: list[str] = []
    for i, claim in enumerate(draft.claims, 1):
        r = _scrip(
            scrip_cmd,
            ["anchor", claim.quote, "--source", source_id, "--label", f"a{i}",
             "--json", "--root", str(root)],
        )
        if r.returncode != 0:
            raise CompileError(
                f"claim {i} quote did not resolve uniquely (scrip anchor exit "
                f"{r.returncode}): {claim.quote!r}\n{r.stderr.strip()}"
            )
        footnotes.append(json.loads(r.stdout)["footnote"])

    r = _scrip(
        scrip_cmd,
        ["new", kind, slug, "--from", source_id, "--title", draft.title, "--root", str(root)],
    )
    if r.returncode != 0:
        raise CompileError(f"scrip new failed (exit {r.returncode}): {r.stderr.strip()}")

    # Fill the scaffold's body with the synthesized prose + minted footnotes.
    page = root / "vault" / "wiki" / f"{kind}s" / f"{slug}.md"
    meta, _ = frontmatter.load(page)
    page.write_text(frontmatter.dump(meta, assemble_body(draft, footnotes)), encoding="utf-8")

    r = _scrip(scrip_cmd, ["stamp", str(page), "--root", str(root)])
    if r.returncode != 0:
        raise CompileError(f"scrip stamp failed (exit {r.returncode}): {r.stderr.strip()}")
    r = _scrip(scrip_cmd, ["verify", "--root", str(root)])
    if r.returncode != 0:
        raise CompileError(f"scrip verify failed after compile:\n{r.stdout}{r.stderr}")
    return page

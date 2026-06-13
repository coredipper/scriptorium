"""Orchestrate the model-driven steps — COMPILE (draft a page) and EXTRACT
(draft claims) — handing every verifiable step to ``scrip`` subprocesses.
``scrip`` stays the deterministic source of truth — this never re-implements
hashing, anchoring, staleness, or fact writing."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from scrip import frontmatter  # reuse the deterministic frontmatter helper

from .compile import DraftPage, assemble_body, extract_markers
from .extract import DraftExtraction, to_ndjson

DraftFn = Callable[..., DraftPage]
ExtractDraftFn = Callable[..., DraftExtraction]

# Drive scriptoria through the *running interpreter*, not a bare `scrip` on PATH:
# `uv tool install scrip-harness` installs scriptoria into the harness's own
# environment but only exposes the harness's entry point, so a PATH `scrip` may be
# missing or a different version. `-m scrip.cli` always runs the bundled one.
DEFAULT_SCRIP_CMD = (sys.executable, "-m", "scrip.cli")

# Same conservative shape scrip enforces — no path separators, '..', or leading dot.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class CompileError(RuntimeError):
    """A compile step failed (bad slug, marker mismatch, an unresolved quote, or a
    scrip command erred)."""


class ExtractError(RuntimeError):
    """An extract step failed (bad slug, quotes still failing after the bounded
    retries, or a scrip command erred)."""


def _scrip(
    cmd: Sequence[str], args: list[str], input_text: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*cmd, *args], capture_output=True, text=True, input=input_text
    )


def compile_page(
    root,
    slug: str,
    *,
    kind: str = "concept",
    draft_fn: DraftFn,
    scrip_cmd: Sequence[str] = DEFAULT_SCRIP_CMD,
) -> Path:
    """Compile ``raw/<slug>`` into ``wiki/<kind>s/<slug>.md`` and leave it green.

    ``draft_fn(source_text, source_id=...)`` returns a :class:`DraftPage` — inject
    a stub in tests; production passes ``model.draft_page``. Raises
    :class:`CompileError` if any quote fails to resolve or any scrip step errors,
    so a bad draft never produces a stamped-but-broken page."""
    root = Path(root)
    if not _SLUG_RE.fullmatch(slug):  # fullmatch: reject a trailing newline (match + $ would not)
        raise CompileError(
            f"invalid slug {slug!r}: use letters/digits/'.'/'_'/'-', with no path "
            f"separators, '..', or leading dot"
        )
    source_id = f"raw/{slug}"
    try:
        source_text = (root / "vault" / "raw" / f"{slug}.md").read_text(encoding="utf-8")
    except OSError as e:
        raise CompileError(f"cannot read {source_id}: {e}") from e
    draft = draft_fn(source_text, source_id=source_id)

    # The model's inline markers must be exactly [^a1]..[^aN] in order for the N
    # claims. scrip verify only checks footnote *definitions* resolve, so without
    # this a misnumbered/missing/extra marker could be stamped with uncited prose.
    markers = extract_markers(draft.body)
    expected = [f"a{i}" for i in range(1, len(draft.claims) + 1)]
    if markers != expected:
        raise CompileError(
            f"draft footnote markers {markers} do not match claims {expected} in "
            f"first-appearance order (foreign or malformed labels are rejected)"
        )

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


def extract_facts(
    root,
    slug: str,
    *,
    draft_fn: ExtractDraftFn,
    scrip_cmd: Sequence[str] = DEFAULT_SCRIP_CMD,
    max_quote_retries: int = 2,
) -> dict:
    """Extract claims from ``raw/<slug>`` into ``facts/`` and leave the vault green.

    ``draft_fn(source_text, source_id=...)`` returns a :class:`DraftExtraction`;
    on a quote failure it is called again with ``failures=[...]`` (the per-record
    findings from ``scrip fact add``) and must return one replacement claim per
    failure, in order — an empty replacement quote drops that claim. The batch is
    all-or-nothing inside scrip, so each retry resubmits the full corrected set.
    Returns ``{"appended", "skipped", "contradictions"}``.
    """
    root = Path(root)
    if not _SLUG_RE.fullmatch(slug):  # fullmatch: reject a trailing newline (match + $ would not)
        raise ExtractError(
            f"invalid slug {slug!r}: use letters/digits/'.'/'_'/'-', with no path "
            f"separators, '..', or leading dot"
        )
    source_id = f"raw/{slug}"
    try:
        source_text = (root / "vault" / "raw" / f"{slug}.md").read_text(encoding="utf-8")
    except OSError as e:
        raise ExtractError(f"cannot read {source_id}: {e}") from e
    draft = draft_fn(source_text, source_id=source_id)
    claims = list(draft.claims)
    if not claims:
        raise ExtractError(f"the draft proposed no claims for {source_id}")

    # Submit; on per-record quote findings (exit 1, nothing written) ask the
    # model to fix exactly the failing quotes and resubmit the corrected batch.
    retries = 0
    while True:
        r = _scrip(
            scrip_cmd,
            ["fact", "add", "--table", "claims", "--stdin", "--json", "--root", str(root)],
            input_text=to_ndjson(claims, source_id),
        )
        if r.returncode == 0:
            try:
                added = json.loads(r.stdout)
            except json.JSONDecodeError as e:
                raise ExtractError(
                    f"could not parse scrip fact add output: {e}\n{r.stdout}"
                ) from e
            break
        if r.returncode != 1:
            raise ExtractError(
                f"scrip fact add failed (exit {r.returncode}): {r.stderr.strip()}"
            )
        try:
            failures = json.loads(r.stdout)["failures"]
        except (json.JSONDecodeError, KeyError) as e:
            raise ExtractError(
                f"could not parse scrip fact add failures: {e}\n{r.stdout}"
            ) from e
        if retries >= max_quote_retries:
            detail = "; ".join(
                f"{f['status']} {f.get('quote', '')!r}" for f in failures
            )
            raise ExtractError(
                f"{len(failures)} quote(s) still failed after {retries} retr"
                f"{'y' if retries == 1 else 'ies'}: {detail}"
            )
        retries += 1
        revised = draft_fn(source_text, source_id=source_id, failures=failures)
        replacements = list(revised.claims)
        if len(replacements) != len(failures):
            raise ExtractError(
                f"retry returned {len(replacements)} claim(s) for {len(failures)} "
                f"failure(s) — must be one per failure, in order (an empty quote "
                f"drops the claim)"
            )
        dropped: list[int] = []
        for failure, replacement in zip(failures, replacements, strict=True):
            i = failure["index"]
            if replacement.quote.strip():
                claims[i] = replacement
            else:
                dropped.append(i)
        for i in sorted(dropped, reverse=True):
            del claims[i]
        if not claims:
            raise ExtractError("every claim was dropped during quote retries")

    # Stamp the facts set scrip left honestly STALE, then prove the vault green.
    if added["appended"]:
        meta_path = root / "vault" / "facts" / "_meta.yaml"
        r = _scrip(scrip_cmd, ["stamp", str(meta_path), "--root", str(root)])
        if r.returncode != 0:
            raise ExtractError(f"scrip stamp failed (exit {r.returncode}): {r.stderr.strip()}")
    r = _scrip(scrip_cmd, ["verify", "--root", str(root)])
    if r.returncode != 0:
        raise ExtractError(f"scrip verify failed after extract:\n{r.stdout}{r.stderr}")

    # Surface contradiction candidates for RECONCILE — detection is scrip's,
    # adjudication stays the operator's.
    r = _scrip(scrip_cmd, ["query", "contradictions", "--json", "--root", str(root)])
    if r.returncode != 0:
        raise ExtractError(
            f"scrip query contradictions failed (exit {r.returncode}): {r.stderr.strip()}"
        )
    return {
        "appended": added["appended"],
        "skipped": added["skipped"],
        "contradictions": json.loads(r.stdout),
    }

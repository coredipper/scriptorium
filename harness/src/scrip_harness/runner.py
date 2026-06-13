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
from .promote import PromotionDecision, merge_bodies
from .reconcile import ReconciliationDecision

DraftFn = Callable[..., DraftPage]
ExtractDraftFn = Callable[..., DraftExtraction]
DecideFn = Callable[..., PromotionDecision]  # (candidate_text, candidates) -> decision
ReconcileDecideFn = Callable[..., ReconciliationDecision]  # (pair, span_a, span_b) -> decision

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


class PromoteError(RuntimeError):
    """A promote step failed (missing page, a scrip command erred, or the middle
    band was reached with no decider)."""


class ReconcileError(RuntimeError):
    """A reconcile step failed (a scrip command erred, or the model returned an
    invalid decision such as supersede without a winner)."""


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


def _append_log(root: Path, line: str) -> None:
    log = root / "vault" / "wiki" / "log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


def promote_page(
    root,
    slug: str,
    *,
    kind: str = "concept",
    decide_fn: DecideFn | None = None,
    merge_threshold: float = 0.5,
    keep_threshold: float = 0.25,
    scrip_cmd: Sequence[str] = DEFAULT_SCRIP_CMD,
    dry_run: bool = False,
) -> dict:
    """Promote a freshly compiled page: score it against existing pages with
    ``scrip similar``, then keep it or merge it into the best match.

    Banding on the top candidate's combined score: ``>= merge_threshold`` →
    merge (deterministic, no model); ``< keep_threshold`` → keep; in between →
    ``decide_fn(candidate_text, candidates)`` returns a ``PromotionDecision``
    (the only model use). On merge the absorbed page is appended into the target
    (footnotes renumbered), its sources/​id folded into the target's
    ``derived-from``/``supersedes``, then the target is re-stamped and the vault
    re-verified. Returns a dict describing the action.
    """
    root = Path(root)
    if not _SLUG_RE.fullmatch(slug):  # guard before building any path we might unlink
        raise PromoteError(
            f"invalid slug {slug!r}: use letters/digits/'.'/'_'/'-', with no path "
            f"separators, '..', or leading dot"
        )
    page = root / "vault" / "wiki" / f"{kind}s" / f"{slug}.md"
    if not page.exists():
        raise PromoteError(f"no such {kind} page: {page.relative_to(root)}")
    meta, body = frontmatter.load(page)
    cand_id = meta.get("id") or f"{kind}/{slug}"
    title = meta.get("title") or slug
    sources = list(meta.get("derived-from") or [])

    r = _scrip(
        scrip_cmd,
        ["similar", "--title", title, "--from", ",".join(sources), "--kind", kind,
         "--exclude", cand_id, "--top", "5", "--json", "--root", str(root)],
    )
    if r.returncode != 0:
        raise PromoteError(f"scrip similar failed (exit {r.returncode}): {r.stderr.strip()}")
    candidates = json.loads(r.stdout)["candidates"]
    if not candidates:
        return {"action": "keep", "target": None, "reason": "no candidates"}

    top = candidates[0]
    score = top["scores"]["combined"]
    if score >= merge_threshold:
        target_id = top["id"]
    elif score < keep_threshold:
        return {"action": "keep", "target": None, "reason": f"top score {score:.3f} below keep threshold"}
    else:
        if decide_fn is None:
            raise PromoteError(
                f"middle band (top score {score:.3f}) needs a decider; none given"
            )
        decision = decide_fn(page.read_text(encoding="utf-8"), candidates)
        if decision.decision != "merge":
            return {"action": "keep", "target": None, "reason": "decided keep"}
        target_id = decision.target_id

    target = next((c for c in candidates if c["id"] == target_id), None)
    if target is None:
        raise PromoteError(f"merge target {target_id!r} is not among the scored candidates")

    if dry_run:
        return {"action": "merge", "target": target_id, "dry_run": True,
                "score": score, "absorbed": cand_id}

    target_page = root / target["path"]
    original_target = target_page.read_bytes()  # bytes: rollback must be exact (CRLF, encoding)
    t_meta, t_body = frontmatter.load(target_page)
    new_body = merge_bodies(t_body, body)
    df = list(t_meta.get("derived-from") or [])
    for s in sources:
        if s not in df:
            df.append(s)
    t_meta["derived-from"] = df
    sup = list(t_meta.get("supersedes") or [])
    if cand_id not in sup:
        sup.append(cand_id)
    t_meta["supersedes"] = sup
    confs = [c for c in (t_meta.get("confidence"), meta.get("confidence"))
             if isinstance(c, (int, float))]
    if confs:
        t_meta["confidence"] = min(confs)
    target_page.write_text(frontmatter.dump(t_meta, new_body), encoding="utf-8")

    # The merge is atomic. The absorbed page is deleted only after stamp + verify
    # succeed (no data loss), and on failure the target is restored to its
    # original bytes — so a failed promote leaves the vault byte-for-byte
    # unchanged and a rerun after fixing the cause cannot duplicate content. Until
    # the unlink both pages exist and verify cleanly (footnotes resolve against
    # raw/, not each other).
    try:
        r = _scrip(scrip_cmd, ["stamp", str(target_page), "--root", str(root)])
        if r.returncode != 0:
            raise PromoteError(f"scrip stamp failed (exit {r.returncode}): {r.stderr.strip()}")
        r = _scrip(scrip_cmd, ["verify", "--root", str(root)])
        if r.returncode != 0:
            raise PromoteError(f"scrip verify failed after merge:\n{r.stdout}{r.stderr}")
    except PromoteError:
        target_page.write_bytes(original_target)  # roll back the merge, byte-for-byte
        raise
    page.unlink()  # absorbed page removed; its id lives on in the target's supersedes
    _append_log(root, f"- PROMOTE: merged {cand_id} into {target_id}")
    return {"action": "merge", "target": target_id, "absorbed": cand_id}


def _span(scrip_cmd: Sequence[str], root: Path, claim_id: str) -> dict:
    """Fetch a claim's resolved span via `scrip span` → ``{status, text}``."""
    r = _scrip(scrip_cmd, ["span", "--claim", claim_id, "--json", "--root", str(root)])
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise ReconcileError(
            f"scrip span --claim {claim_id} gave no parseable output: {e}\n{r.stderr}"
        ) from e


def reconcile_contradictions(
    root,
    *,
    decide_fn: ReconcileDecideFn,
    scrip_cmd: Sequence[str] = DEFAULT_SCRIP_CMD,
    dry_run: bool = False,
) -> dict:
    """Adjudicate every open contradiction. For each pair from `scrip query
    contradictions`, read both cited spans (`scrip span`), ask ``decide_fn`` for a
    :class:`ReconciliationDecision`, then record them append-only with `scrip fact
    add --table reconciliations`, log to wiki/log.md, and re-stamp + re-verify.
    ``dry_run`` reports the decisions without writing. Returns a summary.
    """
    root = Path(root)
    r = _scrip(scrip_cmd, ["query", "contradictions", "--json", "--root", str(root)])
    if r.returncode != 0:
        raise ReconcileError(f"scrip query contradictions failed (exit {r.returncode}): {r.stderr.strip()}")
    pairs = json.loads(r.stdout)
    if not pairs:
        return {"pairs": 0, "reconciled": []}

    records: list[dict] = []
    for pair in pairs:
        ca, cb = pair["claim_a"], pair["claim_b"]
        # Read both spans first and refuse unresolved evidence BEFORE asking the
        # model or recording anything — never adjudicate (and thereby suppress) a
        # contradiction on an anchor that doesn't resolve uniquely.
        sa, sb = _span(scrip_cmd, root, ca), _span(scrip_cmd, root, cb)
        if sa["status"] != "OK" or sb["status"] != "OK":
            raise ReconcileError(
                f"cannot reconcile {ca}/{cb}: anchor did not resolve uniquely "
                f"({ca}={sa['status']}, {cb}={sb['status']}) — fix it first (scrip verify)"
            )
        decision = decide_fn(pair, sa["text"], sb["text"])
        rec = {"decision": decision.decision, "claim_a": ca, "claim_b": cb}
        if decision.decision == "supersede":
            if decision.winner not in ("a", "b"):
                raise ReconcileError(
                    f"supersede for {ca}/{cb} needs winner 'a' or 'b', got {decision.winner!r}"
                )
            rec["winner"] = ca if decision.winner == "a" else cb
        if decision.rationale:
            rec["rationale"] = decision.rationale
        records.append(rec)

    if dry_run:
        return {"pairs": len(pairs), "dry_run": True, "decisions": records}

    ndjson = "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in records)
    r = _scrip(
        scrip_cmd,
        ["fact", "add", "--table", "reconciliations", "--stdin", "--json", "--root", str(root)],
        input_text=ndjson,
    )
    if r.returncode != 0:
        raise ReconcileError(f"scrip fact add failed (exit {r.returncode}): {r.stderr.strip()}")
    added = json.loads(r.stdout)
    for rec in records:
        tail = f" (winner {rec['winner']})" if rec["decision"] == "supersede" else ""
        _append_log(root, f"- RECONCILE: {rec['decision']} {rec['claim_a']} vs {rec['claim_b']}{tail}")

    if added["appended"]:
        r = _scrip(scrip_cmd, ["stamp", str(root / "vault" / "facts" / "_meta.yaml"), "--root", str(root)])
        if r.returncode != 0:
            raise ReconcileError(f"scrip stamp failed (exit {r.returncode}): {r.stderr.strip()}")
    r = _scrip(scrip_cmd, ["verify", "--root", str(root)])
    if r.returncode != 0:
        raise ReconcileError(f"scrip verify failed after reconcile:\n{r.stdout}{r.stderr}")
    return {"pairs": len(pairs), "reconciled": added["appended"], "skipped": added["skipped"]}

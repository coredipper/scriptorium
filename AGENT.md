# AGENT.md — the scriptorium protocol

You are the scribe. You own **judgment**: what to ingest, how to synthesize, when
two claims conflict, whether an answer deserves to become a page. The `scrip` CLI
owns **determinism**: hashing, staleness, provenance integrity, fact queries.
Never hand-compute a hash or guess whether something is stale — ask `scrip`.

Golden rules:
- **Never edit `vault/raw/`** after ingest. It is immutable. A changed source is a
  *re-ingest*, which is a tracked event.
- **Never silently overwrite** a claim that a new source contradicts. Reconcile.
- After any compile or extract, leave the vault **green**: `scrip status` exits 0
  and `scrip verify` exits 0.

The data contract these steps assume is normative in [SPEC.md](SPEC.md).

---

## INGEST — bring a source in

1. `scrip ingest <url|file> [--slug …] [--title …] [--author …]` — fetches or
   reads the source, extracts **canonical text** (HTML/PDF via the optional
   `[ingest]` extra; `.md`/`.txt` passthrough), and writes `vault/raw/<slug>.md` +
   `.meta.yaml`. The stored text is canonical; do not touch it again. Raw is
   immutable — re-ingesting a *changed* source needs `--reingest` (a tracked
   event). (You may still hand-author the two files instead.)
2. `scrip status --rebuild-manifest` — the new source registers and shows as
   `UNCOMPILED` (nothing depends on it yet).

## COMPILE — synthesize a wiki page

1. Read the relevant `raw/` source(s).
2. Scaffold the page with the correct frontmatter, then synthesize:
   - `scrip new concept <slug> --from raw/a,raw/b [--title "…"]` (or `entity`)
     writes `vault/wiki/{concepts,entities}/<slug>.md` with `id`, `type`, `title`,
     `derived-from`, `confidence` and an empty body. It refuses to overwrite.
   - Fill the prose. For each claim-bearing sentence, mint a footnote anchor with
     `scrip anchor "<exact quote>" --source raw/<slug>` — it prints a ready-to-paste
     `[^a1]: anchor=raw/<slug>#<anchor>  "…"` line and **exits 1 if the quote is
     not unique** (lengthen it until `OK`). Set `confidence` to your honest rating.
3. `scrip stamp vault/wiki/concepts/<slug>.md` — records the correct `input-hash`
   + `last-compiled` deterministically.
4. `scrip verify` — fix any `BROKEN`/`AMBIGUOUS` anchors (lengthen the quote until
   unique) until it exits 0.

## EXTRACT — pull structured facts

1. Propose records to `scrip fact add` (NDJSON on `--stdin` or from `--file`)
   instead of hand-appending — it validates, mints, and appends under the write
   lock, **all-or-nothing**:
   - claims (`--table claims`, the default): each proposal carries a **verbatim
     `quote`** plus a `subject`/`predicate`/`object` triple, a `polarity`
     (`asserts`/`denies`/`qualifies`), and a `confidence`. scrip mints the
     `anchor` (a non-unique or absent quote fails the batch, exit 1 listing each
     failing record — lengthen the quote and retry), assigns
     `claim_id`/`extracted_at`, skips exact duplicates (safe to re-run), and
     merges the new sources into `facts/_meta.yaml` `derived-from`.
   - entities / edges (`--table entities|edges`): schema + id checks, no anchors.
2. `scrip stamp vault/facts/_meta.yaml` — every append (any table) drops the
   set's `input-hash`, so it deliberately shows STALE until you stamp it.
3. `scrip verify` (anchors resolve) and `scrip query contradictions` (catch
   self-conflicts before they harden).

`scrip-harness extract <slug>` runs this loop end-to-end for one source's claims
(Claude proposes; failed quotes are re-asked with lengthened replacements).

## ANSWER — the policy ladder

Descend; stop at the first rung that applies (see [SPEC §9](SPEC.md#9-the-answer-policy-ladder)):

1. `scrip status` the relevant artifact(s); consult `wiki/` + `scrip query` over
   `facts/`.
2. **Hit & fresh** → answer, citing anchors. Done. *(cheap — no re-derivation)*
3. **Hit & stale** → recompile just that artifact (COMPILE/EXTRACT), `scrip stamp`,
   then answer.
4. **Miss** → `scrip search "<question>"` to retrieve candidate source blocks
   (semantic if `scrip index` has been built with the embeddings extra, else
   grep), synthesize an answer, cite it, then **PROMOTE** it.
5. **Conflict surfaced** → **RECONCILE**.

Append a one-line entry to `wiki/log.md` for compiles, promotions, and
reconciliations.

`scrip-harness answer "<question>"` runs the safe form of this ladder: it refuses
stale artifacts, broken anchors, and open contradictions by default; gathers
facts/wiki evidence first; falls back to `scrip search` when compiled evidence is
thin; and accepts the model answer only after every claim citation resolves via
`scrip span` or every raw quote mints via `scrip anchor`. `--save` writes the
verified answer to `wiki/explorations/`.

## PROMOTE — turn a good answer into a page

1. Before creating a page, score overlap with existing pages:
   `scrip similar --title "…" --from raw/a,raw/b [--kind concept|entity]` ranks
   them deterministically by normalized-title token overlap + shared
   `derived-from` + shared `tags` (tags derived from the claims on those
   sources, since pages carry no tags). Pass `--exclude <id>` when re-scoring an
   existing page so it does not match itself.
2. **High overlap** → MERGE into the existing page (append, extend `derived-from`,
   record the absorbed id in `supersedes`). **Low** → create a new page.
   **Middle** → you decide, but only over that small candidate set. (The
   threshold cutoffs are yours: `scrip similar` reports scores, not a verdict.)
3. Entity pages are strictly 1:1 with `entities.ndjson` rows. Re-`stamp` and
   `verify` after.

`scrip-harness promote <slug>` runs this end-to-end for a compiled page: it
scores via `scrip similar`, merges into the top match when overlap is high
(deterministically) or keeps the page when it is low, and asks the model only in
the middle band. A merge appends the absorbed page (footnotes renumbered),
folds its sources/​id into the target's `derived-from`/`supersedes`, deletes the
absorbed page, then re-stamps and re-verifies.

## RECONCILE — resolve a contradiction

1. Triggered by `scrip query contradictions` (opposing `polarity`, same
   subject+predicate, different source) **or** a `verify` `BROKEN` anchor from a
   re-ingested source.
2. Read both anchored spans with `scrip span --claim <id>` (or
   `scrip span "raw/<slug>#<anchor>"`). Decide: **supersede** (one wins),
   **qualify** (also add a `polarity: qualifies` claim and a caveat in the page),
   or **keep-both** (acknowledge the disagreement).
3. Record the decision append-only with
   `scrip fact add --table reconciliations` (`{decision, claim_a, claim_b,
   winner?, rationale?}` — scrip mints the id + timestamp). Existing claim rows
   are never rewritten; `scrip query contradictions` then stops surfacing the
   adjudicated pair. Log the decision in `wiki/log.md`. Never silent overwrite.

`scrip-harness reconcile` runs this loop: it reads each contradiction's spans,
asks the model to decide, records the reconciliation, logs it, and re-verifies.
On a **qualify** it also authors the nuancing `polarity: qualifies` claim (verbatim
quote → `scrip fact add --table claims`, anchor minted and verified); the page
caveat is left to the read-only view layer rather than mutating a stamped page.

---

## Quick reference

| You want to… | Command |
|---|---|
| bring a source into raw/ | `scrip ingest <url\|file> [--slug …]` |
| see what's stale / uncompiled | `scrip status` |
| scaffold a new wiki page | `scrip new concept\|entity <slug> --from raw/…` |
| mint a provenance anchor for a quote | `scrip anchor "<quote>" --source raw/<slug>` |
| append validated fact records | `scrip fact add [--table claims\|entities\|edges] --stdin` |
| score overlap before promoting a page | `scrip similar --title "…" --from raw/…` |
| read the text an anchor cites | `scrip span --claim <id>` \| `scrip span "raw/<slug>#<anchor>"` |
| record a contradiction decision | `scrip fact add --table reconciliations --stdin` |
| record provenance hashes after compiling | `scrip stamp [path…]` |
| check every citation still resolves | `scrip verify` |
| query the facts layer | `scrip query claims \| entities \| edges \| contradictions \| --sql "…"` |
| retrieve source blocks (rung 4) | `scrip search "<question>"` |
| build the semantic index (optional) | `scrip index` *(needs the `[embeddings]` extra)* |
| answer with verified citations | `scrip-harness answer "<question>" [--save]` |

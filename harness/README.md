# scrip-harness — the runnable compile loop

The deterministic `scrip` keeper does staleness, provenance, and queries. It never
calls a model. **scrip-harness** is the optional *judgment* layer that makes the
[AGENT.md](../AGENT.md) COMPILE step runnable: it asks Claude to synthesize a wiki
page from a source, then hands every verifiable step back to `scrip`.

The dependency points one way only: the harness depends on `scrip` (and the
Anthropic SDK); `scrip` depends on neither. Removing this directory leaves a fully
valid, fully deterministic vault and CLI behind.

## How a compile runs

`scrip-harness compile <slug>` (for `vault/raw/<slug>.md`):

1. **Draft** — Claude (`claude-opus-4-8`, adaptive thinking, structured output)
   returns a `DraftPage`: a title, markdown prose with footnote markers
   `[^a1], [^a2], …`, and one *verbatim quote* per marker.
2. **Mint + retry** — each quote goes through `scrip anchor`, which rejects a
   quote that isn't present in the source or isn't unique. Rejected quotes go back
   to Claude for one correction per failure (re-copied or lengthened until unique);
   bounded retries, then the compile fails cleanly. A hallucinated or paraphrased
   quote cannot get past this step. Unlike EXTRACT, every claim is kept — the
   body's `[^a1]..[^aN]` markers are positional — so a quote is corrected, never
   dropped.
3. **Scaffold + fill** — `scrip new` writes the frontmatter; the harness fills the
   body with the prose + the minted footnote definitions.
4. **Stamp + verify** — `scrip stamp` records provenance hashes; `scrip verify`
   proves every citation resolves. If verify fails, the compile errors out rather
   than leaving a stamped-but-broken page.

So the model owns *what to say*; `scrip` owns *what is true on disk*.

## How an extract runs

`scrip-harness extract <slug>` (for `vault/raw/<slug>.md`):

1. **Draft** — Claude returns a `DraftExtraction`: structured claims, each with a
   *verbatim quote*, a subject/predicate/object triple, and a polarity.
2. **Mint + append** — the claims go to `scrip fact add --stdin`, which verifies
   every quote (minting anchors), assigns ids and timestamps, skips exact
   duplicates, and appends **all-or-nothing** under the write lock.
3. **Retry** — if quotes come back BROKEN/AMBIGUOUS, the failures go back to
   Claude for one replacement per failure (lengthened until unique, or an empty
   quote to drop the claim); bounded retries, then the extract fails cleanly.
4. **Stamp + verify** — `scrip stamp vault/facts/_meta.yaml`, then `scrip verify`;
   contradiction candidates from `scrip query contradictions` are surfaced for
   the operator to RECONCILE per [AGENT.md](../AGENT.md).

## How a promote runs

`scrip-harness promote <slug>` (for a compiled `vault/wiki/<kind>s/<slug>.md`):

1. **Score** — `scrip similar` ranks existing pages by overlap (shared sources +
   title tokens + derived tags) with the candidate, excluding itself.
2. **Band** the top score: **≥ `--merge-threshold`** (0.5) → merge into it,
   **deterministically (no model)**; **< `--keep-threshold`** (0.25) → keep the
   page as its own; **in between** → Claude decides merge-vs-keep over the small
   candidate set (the *only* model call in PROMOTE).
3. **Merge** — append the candidate into the target (its `[^a1]..` footnotes
   renumbered to avoid collision), union the `derived-from`, record the absorbed
   id in `supersedes`, delete the absorbed page, then `scrip stamp` + `scrip
   verify`. `--dry-run` prints the decision and mutates nothing.

## How an answer runs

`scrip-harness answer "question"` makes the ANSWER rung executable:

1. **Preflight** — `scrip status`, `scrip verify`, and `scrip query
   contradictions` must be clean by default. Stale artifacts, broken anchors, or
   open contradiction pairs stop the answer before any model call.
2. **Gather** — the harness ranks claims from `facts/`, reads relevant compiled
   wiki pages as context, and falls back to `scrip search` when compiled evidence
   is thin.
3. **Draft** — Claude answers from that bounded evidence packet and returns
   structured citation records: either an existing `claim_id` or a verbatim raw
   quote.
4. **Verify citations** — claim citations are resolved with `scrip span`; raw
   quotes are minted with `scrip anchor`. Unsupported citations fail the answer.
   `--save` writes a verified note under `wiki/explorations/`.

## How a reconcile runs

`scrip-harness reconcile` (over every open contradiction):

1. **Find** — `scrip query contradictions` lists the candidate pairs (same
   subject+predicate, opposing polarity, different sources, not yet adjudicated).
2. **Read** — for each pair, `scrip span --claim <id>` fetches both verbatim
   cited spans, and Claude decides **supersede** (with a winner), **qualify**, or
   **keep-both**, with a rationale.
3. **Record** — the decisions are written append-only with `scrip fact add
   --table reconciliations` (existing claim rows are never rewritten), logged to
   `wiki/log.md`, then `scrip stamp` + `scrip verify`. Adjudicated pairs stop
   being surfaced by `scrip query contradictions`. `--dry-run` prints the
   decisions without recording.

## Install & run

Both packages are on PyPI. `scrip-harness` bundles `scriptoria` as a dependency
and drives it through its own interpreter, so it is self-sufficient — install
`scriptoria` as a tool too only if you want the `scrip` command on PATH for
direct use:

```sh
uv tool install scrip-harness            # this package → `scrip-harness` (pulls scriptoria)
uv tool install 'scriptoria[ingest]'     # optional: `scrip` on PATH + HTML/PDF ingest
export ANTHROPIC_API_KEY=...              # the harness calls Claude; scrip never does

scrip-harness compile article            # synthesize + verify a page from raw/article
scrip-harness extract article            # pull claims into facts/
scrip-harness answer "What does the corpus say about caching?"
scrip ingest <url> --slug article        # bring a source in (needs the install above)
```

(From a checkout, `uv tool install ./scrip` and `uv tool install ./harness`
install the local versions instead.)

## Develop / test

```sh
cd harness && uv run pytest        # hermetic: the model is stubbed; scrip runs for real
```

The tests inject a stub draft function (no network, no API key) and drive the real
`scrip` subcommands over a temp vault, asserting the result is stamped and verified.

## Scope & limits (v1)

- Covers **COMPILE** (one source → one wiki page, with the bounded quote-retry
  loop), **EXTRACT** (one source → claims in `facts/`, same retry loop), **ANSWER** (fresh
  compiled evidence first, raw search on miss, verified citations), **PROMOTE**
  (score → merge/keep, model only in the middle band), and **RECONCILE**
  (adjudicate every contradiction → record the decision). Entities/edges go
  through `scrip fact add --table entities|edges` by hand.
- Single source per page/extract; merge is **append** (not re-synthesis).
  `reconcile` records the decision (supersede/qualify/keep-both); for a
  **qualify**, authoring the nuancing `polarity: qualifies` claim + the page
  caveat is still operator follow-up. Multi-source synthesis is future work.

# scrip-harness — the runnable compile loop

The deterministic `scrip` keeper does staleness, provenance, and queries. It never
calls a model. **scrip-harness** is the optional *judgment* layer that makes the
[AGENT.md](../AGENT.md) COMPILE step runnable: it asks a configured model provider
to synthesize a wiki page from a source, then hands every verifiable step back to
`scrip`.

The dependency points one way only: the harness depends on `scrip` (and the
provider client in `model.py`); `scrip` depends on neither. Removing this
directory leaves a fully valid, fully deterministic vault and CLI behind.

## How a compile runs

`scrip-harness compile <slug>` (for `vault/raw/<slug>.md`; pass
`--from raw/a,raw/b` to synthesize one page from several sources):

1. **Draft** — the selected provider returns a `DraftPage`: a title, markdown
   prose with footnote markers
   `[^a1], [^a2], …`, and one *verbatim quote* per marker — each tagged with the
   `source_id` it was copied from when several sources are given.
2. **Mint + retry** — each quote goes through `scrip anchor`, which rejects a
   quote that isn't present in the source or isn't unique. Rejected quotes go back
   to the model for one correction per failure (re-copied or lengthened until unique);
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

1. **Draft** — the selected provider returns a `DraftExtraction`: structured
   claims, each with a *verbatim quote*, a subject/predicate/object triple, and a polarity.
2. **Mint + append** — the claims go to `scrip fact add --stdin`, which verifies
   every quote (minting anchors), assigns ids and timestamps, skips exact
   duplicates, and appends **all-or-nothing** under the write lock.
3. **Retry** — if quotes come back BROKEN/AMBIGUOUS, the failures go back to
   the model for one replacement per failure (lengthened until unique, or an empty
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
   page as its own; **in between** → the model decides merge-vs-keep over the small
   candidate set (the only model call in PROMOTE unless `--resynthesize` is set).
3. **Merge** — by default, append the candidate into the target (its `[^a1]..`
   footnotes renumbered to avoid collision); with `--resynthesize`, instead
   re-draft the target as one coherent page over the union of both pages' sources
   (re-minting every anchor via the COMPILE quote-retry loop). Either way: union the
   `derived-from`, record the absorbed id in `supersedes`, delete the absorbed page,
   then `scrip stamp` + `scrip verify` (the target is restored byte-for-byte if that
   fails). `--dry-run` prints the decision and mutates nothing.

## How an answer runs

`scrip-harness answer "question"` makes the ANSWER rung executable:

1. **Preflight** — `scrip status`, `scrip verify`, and `scrip query
   contradictions` must be clean by default. Stale artifacts, broken anchors, or
   open contradiction pairs stop the answer before any model call.
2. **Gather** — the harness ranks claims from `facts/`, reads relevant compiled
   wiki pages as context, and falls back to `scrip search` when compiled evidence
   is thin.
3. **Draft** — the selected provider answers from that bounded evidence packet and returns
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
   cited spans, and the model decides **supersede** (with a winner), **qualify**
   (with a verbatim qualifier quote + the condition under which it holds), or
   **keep-both**, with a rationale.
3. **Record** — the decisions are written append-only with `scrip fact add
   --table reconciliations` (existing claim rows are never rewritten); a
   **qualify** also authors a `polarity: qualifies` claim via `scrip fact add
   --table claims` (its anchor minted + verified). Logged to `wiki/log.md`, then
   `scrip stamp` + `scrip verify`. Adjudicated pairs stop being surfaced by `scrip
   query contradictions`. `--dry-run` prints the decisions without recording.

## How an ingest runs

`scrip-harness ingest <source>` takes a URL or file from cold to a verified,
compiled, graphed vault in one command:

1. **Ingest** — `scrip ingest <source>` fetches, extracts, and writes `raw/<slug>`
   (slug derived from the source name, or `--slug`). URLs/HTML/PDF need the
   extraction deps in the harness env — install `scrip-harness[ingest]`; plain
   `.md`/`.txt` work with the base install.
2. **Clean (opt-in)** — `--clean` first has the model normalize the extracted text
   into clean Markdown (dropping nav/boilerplate, preserving the prose *verbatim*)
   and re-ingests it. `raw/<slug>` then holds the cleaned rendering, so anchors
   resolve against it — a deliberate provenance trade-off.
3. **Chain** — COMPILE → EXTRACT → GRAPH run over `raw/<slug>` (each model-backed),
   leaving the vault green. `--through ingest|compile|extract|graph` (default
   `graph`) bounds how far the pipeline runs.

## Install & run

Both packages are on PyPI. `scrip-harness` bundles `scriptoria` as a dependency
and drives it through its own interpreter, so it is self-sufficient — install
`scriptoria` as a tool too only if you want the `scrip` command on PATH for
direct use:

```sh
uv tool install scrip-harness            # this package → `scrip-harness` (pulls scriptoria)
uv tool install 'scrip-harness[ingest]'  # to ingest URLs/HTML/PDF: adds the extraction deps
                                          # to the harness's own env (PATH is bypassed)
uv tool install 'scriptoria[ingest]'     # optional: `scrip` on PATH for direct, non-harness use
export OPENAI_API_KEY=...                 # or ANTHROPIC_API_KEY / GEMINI_API_KEY

scrip-harness ingest <url> --provider openai   # one command: ingest → compile → extract → graph
scrip-harness compile article --provider openai
scrip-harness extract article            # pull claims into facts/
scrip-harness answer "What does the corpus say about caching?" --provider openai
scrip ingest <url> --slug article        # or bring a source in deterministically (needs the install above)
```

(From a checkout, `uv tool install ./scrip` and `uv tool install ./harness`
install the local versions instead.)

### Provider selection

Every model-backed command accepts:

```sh
scrip-harness answer "..." --provider auto|anthropic|openai|gemini \
  [--model MODEL] [--api-key-file PATH]
```

`--provider auto` is the default. It picks the first available key in this order:
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (or `~/veed/var/openai`), then
`GEMINI_API_KEY`/`GOOGLE_API_KEY` (or files under `~/veed/var/gemini`). Provider
defaults can be overridden with `SCRIP_HARNESS_<PROVIDER>_MODEL`. Environment
keys take precedence over key files. When `--api-key-file` points at a directory,
the harness reads the first non-empty key from the sorted files in that directory.
An explicit key file also needs an explicit provider:

```sh
scrip-harness answer "How does the answer ladder work?" --provider openai \
  --api-key-file ~/veed/var/openai
scrip-harness answer "How does raw fallback work?" --provider gemini \
  --api-key-file ~/veed/var/gemini --model gemini-3.5-flash
```

### Demo fixture

From a checkout, `scripts/demo_answer.sh` runs the full answer command against a
small synthetic vault in `examples/answer-demo-vault/`:

```sh
scripts/demo_answer.sh --provider openai
scripts/demo_answer.sh --provider gemini --api-key-file ~/veed/var/gemini
scripts/demo_answer.sh --root . --provider auto "What does the vault say about caching?"
```

The script runs `scrip status` and `scrip verify` before invoking the model. Pass
`--save` to write the verified answer under `vault/wiki/explorations/`.

## Develop / test

```sh
cd harness && uv run pytest        # hermetic: the model is stubbed; scrip runs for real
```

The tests inject a stub draft function (no network, no API key) and drive the real
`scrip` subcommands over a temp vault, asserting the result is stamped and verified.

## Scope & limits (v1)

- Covers **COMPILE** (one or more sources → one wiki page, with the bounded
  quote-retry loop), **EXTRACT** (one or more sources → claims in `facts/`, same retry loop), **ANSWER** (fresh
  compiled evidence first, raw search on miss, verified citations), **PROMOTE**
  (score → merge/keep, model only in the middle band or on `--resynthesize`), **RECONCILE**
  (adjudicate every contradiction → record the decision), and **GRAPH** (one
  source → entities + typed edges in `facts/`). `scrip-harness graph <slug>`
  drafts both at once; the runner mints `entity/<slug>` ids and **drops any edge
  whose endpoints are not real entities** (drafted here or already on disk).
  Entities/edges carry no anchor — they are structural, not cited — so there is no
  quote-retry loop and a model can still assert a *wrong* relation between real
  entities; treat the graph as a navigational aid, not verified provenance. You
  can still author them by hand via `scrip fact add --table entities|edges`.
- COMPILE and EXTRACT both accept one or more sources (`--from raw/a,raw/b`); in a
  multi-source EXTRACT each claim names the source its quote came from and its anchor
  is minted against that source, so a mis-attributed quote fails quote-verify (the
  retry loop catches it). PROMOTE's merge is **append** by default (loss-free,
  deterministic); `--resynthesize` instead re-drafts the target as one coherent page
  over the union of both pages' sources (re-minting every anchor) — more coherent but
  it rewrites the body, so it is opt-in. (Re-synthesis re-reads whole files, so a
  block-scoped `derived-from` dep — `raw/x#<block_id>` — is widened to its whole file;
  safe, since the page can then only go *more* stale.) `reconcile` records the decision
  (supersede/qualify/keep-both) and, on a **qualify**, authors the nuancing
  `polarity: qualifies` claim; surfacing the page caveat is left to the read-only
  view layer, not a page mutation.

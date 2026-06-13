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
2. **Mint** — each quote goes through `scrip anchor`, which **fails the compile**
   if the quote isn't present in the source or isn't unique. A hallucinated or
   paraphrased quote cannot get past this step.
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

- Covers **COMPILE** (one source → one wiki page) and **EXTRACT** (one source →
  claims in `facts/`, with the bounded quote-retry loop). Entities/edges go
  through `scrip fact add --table entities|edges` by hand; PROMOTE (merge/dedup)
  and RECONCILE (contradictions) are not yet automated here — drive them with
  `scrip` directly per [AGENT.md](../AGENT.md).
- Single source per page/extract. Multi-source synthesis, and adopting the
  quote-retry loop in COMPILE too, are future work.

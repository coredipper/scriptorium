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

## Install & run

```sh
uv tool install ./scrip            # the deterministic keeper (must be on PATH)
uv tool install ./harness          # this package → `scrip-harness`
export ANTHROPIC_API_KEY=...        # the harness calls Claude; scrip never does

scrip ingest https://example.com/article --slug article   # bring a source in
scrip-harness compile article                             # synthesize + verify a page
```

## Develop / test

```sh
cd harness && uv run pytest        # hermetic: the model is stubbed; scrip runs for real
```

The tests inject a stub draft function (no network, no API key) and drive the real
`scrip` subcommands over a temp vault, asserting the result is stamped and verified.

## Scope & limits (v1)

- Covers **COMPILE** (one source → one wiki page). EXTRACT (claims into
  `facts/`), PROMOTE (merge/dedup), and RECONCILE (contradictions) are not yet
  automated here — drive them with `scrip` directly per [AGENT.md](../AGENT.md).
- Single source per page. Multi-source synthesis and a retry loop that re-asks the
  model to lengthen an ambiguous quote are future work.

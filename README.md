# scriptorium

An agent-maintained knowledge base where **staleness and provenance are
computable, not hoped for** — and where *compile, cache, and retrieve* are not
rival designs but rungs of one answer policy.

It synthesizes and transcends three prior approaches:

- **Karpathy's LLM wiki** — *compile* sources into a maintained markdown wiki.
- **MotherDuck's Obsidian + DuckDB plugin** — *cache* query results inline,
  "cached by default, live when it matters."
- **Local RAG (llm.c)** — *retrieve* raw chunks by embedding similarity.

Each is strong exactly where the others are weak. scriptorium keeps all three and
adds the two primitives they lack: a **content-hash dependency graph** (real
staleness) and **content-anchored provenance** (citations a machine can verify
still resolve). See **[RATIONALE.md](RATIONALE.md)** for the full argument and
**[SPEC.md](SPEC.md)** for the normative file contract.

## What's in here

```
SPEC.md         the technology-agnostic file contract (the durable artifact)
RATIONALE.md    why this beats compile-only / cache-only / retrieve-only
AGENT.md        the protocol the maintaining agent follows
vault/          a real, dogfooded instance (reading notes on the 3 designs above)
  raw/          immutable sources (+ .meta.yaml sidecars)
  facts/        structured extractions, queryable as data (NDJSON)
  wiki/         synthesized concept & entity pages, with provenance footnotes
scrip/          the reference CLI: the deterministic keeper (Python, uv)
scripts/        seed_vault.py — reproducibly regenerates the example vault
adapters/       deferred bindings (Obsidian, embeddings) — see adapters/README.md
```

The contract is the point; `scrip` and `vault/` are one conforming instance of it.

## Quickstart

```sh
# install the deterministic keeper
uv tool install ./scrip

# what's stale / what's uncompiled
scrip status

# do all citations still resolve to their sources?
scrip verify

# query the facts layer (DuckDB over NDJSON)
scrip query claims --where "list_contains(tags, 'caching')"
scrip query contradictions
scrip query --sql "SELECT source_id, count(*) AS n FROM claims GROUP BY 1 ORDER BY n DESC"

# rung 4 — retrieve source blocks for an uncompiled question (grep by default)
scrip search "what makes adding one document expensive?"
```

### Optional: semantic retrieval

The retrieval rung uses lexical grep out of the box. For real semantic search,
install the embeddings extra (small static embeddings, no GPU), build the index,
and `scrip search` upgrades automatically:

```sh
uv tool install './scrip[embeddings]'
scrip index    # embeds vault/raw/ blocks into .kb/embeddings/ (regenerable cache)
scrip search "keeping citations trustworthy when sources change"
```

The maintaining loop (for an agent or a human): **ingest** a source into `raw/`,
**compile** a page into `wiki/` and **extract** claims into `facts/`, then
`scrip stamp` to record provenance and `scrip verify` to prove citations resolve.
Full protocol in **[AGENT.md](AGENT.md)**.

## Regenerate the example vault

```sh
uv run --project scrip python scripts/seed_vault.py
scrip stamp && scrip verify && scrip status
```

## Develop `scrip`

```sh
cd scrip && uv run pytest        # hermetic; no network, no LLM
```

## Status

v0 — the thin end-to-end slice is complete and dogfooded. Deferred to adapters:
an embeddings retrieval rung, an Obsidian browsing layer, multi-writer locking.

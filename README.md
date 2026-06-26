# scriptorium

<p align="center">
  <img src="docs/jean-mielot-scriptorium.jpg" alt="Jean Miélot writing in his scriptorium" width="480"><br>
  <sub><em>Jean Miélot at work in his scriptorium (illumination by Jean Le Tavernier, c. 1456). Public domain, via <a href="https://commons.wikimedia.org/wiki/File:Tavernier_Jean_Mielot.jpg">Wikimedia Commons</a>.</em></sub>
</p>

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
HOWTO.md        practical day-to-day operator guide (start here to *use* it)
docs/           comparisons and adapter design notes
vault/          a real, dogfooded instance (reading notes on the 3 designs above)
  raw/          immutable sources (+ .meta.yaml sidecars)
  facts/        structured extractions, queryable as data (NDJSON)
  wiki/         synthesized concept & entity pages, with provenance footnotes
scrip/          the reference CLI: the deterministic keeper (Python, uv)
harness/        optional LLM loop (scrip-harness): runnable COMPILE / EXTRACT / PROMOTE
scripts/        seed_vault.py — reproducibly regenerates the example vault
examples/       small synthetic vaults and demos safe to share
adapters/       deferred bindings (Obsidian, embeddings, PageIndex) — see adapters/README.md
```

The contract is the point; `scrip` and `vault/` are one conforming instance of it.
For adjacent systems and tradeoffs, see **[docs/comparisons.md](docs/comparisons.md)**.
For the optional PageIndex cache adapter, see
**[docs/pageindex-adapter.md](docs/pageindex-adapter.md)**. The current
improvement plan lives in **[docs/roadmap.md](docs/roadmap.md)**.

**Want to actually use it day to day?** See **[HOWTO.md](HOWTO.md)**.

## Quickstart

The package is published to PyPI as **`scriptoria`**; the command it installs and
the import package are both `scrip` (`pip install scriptoria` → run `scrip`).

```sh
# install the deterministic keeper
uv tool install scriptoria        # or: pip install scriptoria   (from a checkout: ./scrip)

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

# before creating a page, score its overlap with existing ones (PROMOTE step 1)
scrip similar --title "Compilation over retrieval" --from raw/karpathy-llm-wiki
```

### Optional: answer demo

The optional harness can answer from a green vault with model output constrained
to verified claim ids or raw quotes. A sanitized fixture is included for demos:

```sh
scripts/demo_answer.sh --provider openai
scripts/demo_answer.sh --provider gemini --api-key-file ~/veed/var/gemini
scripts/demo_answer.sh --root . --provider auto "What does the vault say about caching?"
```

The first two commands use `examples/answer-demo-vault/`. The `--root .` form
targets the local dogfood vault instead.

### Optional: semantic retrieval

The retrieval rung uses lexical grep out of the box. For real semantic search,
install the embeddings extra (small static embeddings, no GPU), build the index,
and `scrip search` upgrades automatically:

```sh
uv tool install './scrip[embeddings]'
scrip index    # embeds vault/raw/ blocks into .kb/embeddings/ (regenerable cache)
scrip search "keeping citations trustworthy when sources change"
```

### Optional: long-document retrieval

When a compatible PageIndex backend is importable, build a per-source tree cache
and ask `scrip search` to try it before embeddings/grep:

```sh
scrip pageindex build raw/the-paper
scrip search "where does the paper discuss failure modes?" --long-docs pageindex
```

The cache is regenerable under `.kb/pageindex/`; returned snippets still have to
map back to canonical `vault/raw/` text before they can become citations.

The maintaining loop (for an agent or a human): **ingest** a source into `raw/`
(`scrip ingest <url|file>` — extracts canonical text; HTML/PDF need the optional
`[ingest]` extra, markdown/text need nothing), **compile** a page into `wiki/`
(`scrip new` + `scrip anchor` to mint verified citations), **extract** claims into
`facts/` (`scrip fact add` — validates each quote and mints its anchor), and
**promote** to dedup against existing pages (`scrip similar` scores overlap),
each followed by `scrip stamp` (record provenance) and `scrip verify` (prove
citations resolve). The optional [`scrip-harness`](harness/README.md) makes the
COMPILE, EXTRACT, and PROMOTE steps runnable with a model while `scrip` itself
stays deterministic and model-free. Full protocol in **[AGENT.md](AGENT.md)**.

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

**Latest releases: scriptoria v0.6.3 and scrip-harness v0.8.0** (see
[CHANGELOG.md](CHANGELOG.md)) — ANSWER now has a multi-provider harness
(`anthropic`, `openai`, `gemini`) and a sanitized demo fixture. The maintaining
loop has runnable support end to end: every [AGENT.md](AGENT.md) stage
(**INGEST · COMPILE · EXTRACT · ANSWER · PROMOTE · RECONCILE**) has deterministic
`scrip` primitives to branch on, and the model-bearing COMPILE / EXTRACT /
ANSWER / PROMOTE / RECONCILE steps have bounded `scrip-harness` commands. This
is still a reference implementation of a verifiable file contract, not a turnkey
document-chat product: rich chat UX and richer long-document workflows belong in
adapters or higher-level tools.

The contract is hardened (content-derived block ids, **SPEC v2**), with an
advisory write lock, `scrip watch`, and an optional `[embeddings]` retrieval rung;
an Obsidian browsing layer remains an adapter.

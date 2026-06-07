# HOWTO — using scriptorium day to day

A practical guide for the **human operator**. The agent (e.g. Claude Code) does
the synthesis; you curate and ask. For the agent's own protocol see
[AGENT.md](AGENT.md); for the data contract see [SPEC.md](SPEC.md).

## Mental model

- You **read** things → drop a note into `vault/raw/` (immutable once added).
- Your **agent compiles** that into `vault/wiki/` (prose) and `vault/facts/`
  (queryable claims), with citations back to the source.
- `scrip` keeps the bookkeeping honest: what's **stale**, whether citations still
  **resolve**, and answering structured **queries**.
- You **ask questions**; answers come from the compiled layer first, falling back
  to search only when nothing covers it.

## One-time setup

```sh
git clone https://github.com/coredipper/scriptorium
cd scriptorium
uv tool install ./scrip                 # the `scrip` command
uv tool install './scrip[embeddings]'   # optional: semantic `scrip search`
```

Check it's healthy:

```sh
scrip status     # → all artifacts fresh
scrip verify     # → all citations resolve
```

## The daily loop

### 1. Capture something you read

Save the source text (or your notes/excerpts) as a markdown file, plus a small
sidecar with where it came from:

```sh
$EDITOR vault/raw/some-article.md          # the text — keep verbatim quotes you may cite
$EDITOR vault/raw/some-article.meta.yaml   # title / author / url / retrieved
scrip status --rebuild-manifest            # registers it; shows as UNCOMPILED
```

### 2. Let the agent compile it

In Claude Code (or any agent that can read [AGENT.md](AGENT.md)), say:

> Ingest and compile `raw/some-article` per AGENT.md: write a concept page with
> provenance footnotes, extract claims into facts, then stamp and verify.

The agent writes the page + claims, runs `scrip stamp` to record provenance
hashes, and `scrip verify` until every citation resolves.

### 3. Keep it fresh

When a source changes (a deliberate re-ingest), only its dependents go stale:

```sh
scrip status            # lists STALE artifacts and which source changed
# ask the agent to recompile those, then:
scrip stamp <paths>     # re-records provenance; status returns to clean
```

### 4. Ask questions

Answers come from the compiled layer first (cheap), then search on a miss:

```sh
scrip query claims --where "list_contains(tags, 'caching')"
scrip query contradictions                     # opposing claims, by source
scrip query --sql "SELECT subject, count(*) FROM claims GROUP BY 1"
scrip search "what makes adding one document expensive?"   # rung 4 retrieval
```

Or just ask the agent in natural language — it will consult `wiki/` + `scrip
query`, recompile anything stale, and `scrip search` only if nothing covers it
(then **promote** the new answer into a page so it compounds).

## Recipes

| You want to… | Do this |
|---|---|
| Add an article you read | drop `raw/<slug>.md` + `.meta.yaml`, then `scrip status --rebuild-manifest` |
| Turn it into knowledge | ask the agent to *ingest + compile + extract* per AGENT.md |
| Re-index for semantic search | `scrip index` (needs the `[embeddings]` extra) |
| See what needs recompiling | `scrip status` |
| Prove citations still hold | `scrip verify` |
| Find conflicting sources | `scrip query contradictions` |
| Browse it visually | open `vault/` in Obsidian; run the dashboard (below) |

## Browse in Obsidian

`vault/` is already an Obsidian vault (open the folder). For an in-app health
note:

```sh
uv run --project scrip python adapters/obsidian/dashboard.py   # writes vault/wiki/_status.md
```

See [adapters/obsidian/README.md](adapters/obsidian/README.md).

## Regenerate the example vault

The shipped example is reproducible from one source of truth:

```sh
uv run --project scrip python scripts/seed_vault.py
scrip stamp && scrip verify && scrip status
```

## Develop / test `scrip`

```sh
cd scrip && uv run pytest -q
```

CI runs the same tests plus `scrip status`/`verify`/`query` on every push
(`.github/workflows/ci.yml`).

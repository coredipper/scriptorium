# scrip

The deterministic keeper of a [scriptorium](../README.md) knowledge base.

The agent owns judgment (synthesis, fact extraction, reconciliation, promotion).
`scrip` owns only what LLMs are unreliable or expensive at: **content hashing**,
**staleness** over a dependency graph, **provenance-anchor integrity**, and
**structured queries** over the facts layer. Files are the source of truth;
`.kb/manifest.json` is only a regenerable speed cache.

## Install

```sh
uv tool install ./scrip      # installs the `scrip` command
# or, without installing:
uv run --project scrip scrip --help
```

## Commands

| Command | What it does |
|---|---|
| `scrip status` | Report `STALE` / `OK` / `UNCOMPILED` artifacts from the dependency graph. `--no-cache` recomputes from files; `--rebuild-manifest` regenerates the cache. |
| `scrip verify` | Check every provenance anchor still resolves to text in its source; check referenced sources exist and `claim_id`s are unique. Fails on `BROKEN` and `AMBIGUOUS` by default; `--allow-ambiguous` downgrades `AMBIGUOUS` to a warning. |
| `scrip query [claims\|entities\|edges\|contradictions\|reconciliations]` | Structured query over `vault/facts/*.ndjson` via DuckDB. `--sql "<duckdb>"`, `--where`, `--limit`. |
| `scrip ingest <url\|file>` | Fetch/read a source and write canonical `vault/raw/<slug>.md` plus sidecar metadata. HTML/PDF need the optional `[ingest]` extra. |
| `scrip new concept\|entity <slug> --from raw/...` | Scaffold a derived wiki page for the agent to fill. |
| `scrip anchor "<quote>" --source raw/<slug>` | Mint a content-anchored footnote for a verbatim source quote. |
| `scrip fact add --table claims\|entities\|edges\|reconciliations` | Validate and append facts under the write lock; claims mint verified anchors, reconciliations mint ids/timestamps. |
| `scrip span --claim <id>` | Resolve a claim anchor and print the cited span. |
| `scrip similar --title ... --from ...` | Score overlap with existing wiki pages before PROMOTE. |
| `scrip search "<question>"` | Retrieve source blocks for a miss; uses embeddings if an index exists, otherwise lexical grep. |
| `scrip index` | Build the optional embeddings index over `vault/raw/` when `scriptoria[embeddings]` is installed; otherwise exits cleanly and `search` falls back to grep. |
| `scrip watch` / `scrip unlock` | Watch vault health in a poll loop; clear a stale advisory write lock. |

Every command accepts `--root DIR` and `--json`.

The optional `scrip-harness` package adds the model-bearing commands, including
`scrip-harness answer "<question>"`, which gathers evidence with these primitives
and verifies every citation before printing or saving an answer.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | clean / success |
| `1` | actionable finding (stale artifacts; broken citations) |
| `2` | usage error |
| `3` | data error (malformed frontmatter / NDJSON; missing source; duplicate id) |
| `4` | internal error |

Code `1` is an *expected* outcome the agent branches on, not a crash.

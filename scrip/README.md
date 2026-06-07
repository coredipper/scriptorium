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
| `scrip verify` | Check every provenance anchor still resolves to text in its source; check referenced sources exist and `claim_id`s are unique. `--strict` fails on `AMBIGUOUS` too. |
| `scrip query [claims\|entities\|edges\|contradictions]` | Structured query over `vault/facts/*.ndjson` via DuckDB. `--sql "<duckdb>"`, `--where`, `--limit`. |
| `scrip index` | v0 stub for the embeddings retrieval rung. |

Every command accepts `--root DIR` and `--json`.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | clean / success |
| `1` | actionable finding (stale artifacts; broken citations) |
| `2` | usage error |
| `3` | data error (malformed frontmatter / NDJSON; missing source; duplicate id) |
| `4` | internal error |

Code `1` is an *expected* outcome the agent branches on, not a crash.

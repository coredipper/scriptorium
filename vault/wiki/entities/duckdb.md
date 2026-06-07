---
id: entity/duckdb
type: wiki.entity
title: DuckDB
derived-from:
- raw/motherduck-duckdb-obsidian
confidence: 0.9
input-hash: sha256:73b4d45d229b6dfe18c2e0d16c6706e494ccfa250bcf36ee5186d6cebcab58ed
last-compiled: '2026-06-07T20:59:44Z'
---
DuckDB is an in-process analytical database. In the MotherDuck Obsidian plugin it runs locally via WASM, with no server, and can query Parquet, CSV, and JSON.[^a1] scriptorium uses it as the query lens over the `facts/` NDJSON layer.

[^a1]: anchor=raw/motherduck-duckdb-obsidian#qh:9a06e6f0178f35a0c4161f0b218c5349d317028c7df3206e0b97823163fcf847|loc:0.5087|len:83  "DuckDB runs locally via WASM, with no server, an"

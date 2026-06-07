---
id: concept/provenance-and-staleness
type: wiki.concept
title: Provenance and staleness
derived-from:
- raw/motherduck-duckdb-obsidian
- raw/karpathy-llm-wiki
confidence: 0.8
input-hash: sha256:83e035cbed4b4ee686c9f1a1522ab8cbfe717464e6bcaf038cc45bacbc5ae55f
last-compiled: '2026-06-07T20:59:44Z'
---
MotherDuck's sentinel is the seed of a general idea: a frozen result is wrapped in a marker that records what produced it, so a refresh knows what to replace.[^a1] Generalize that marker from a single SQL block to *any* derived artifact and you get a content-hash dependency graph — the concrete definition of the 'freshness' and 'lint' that compile-only designs leave undefined.

[^a1]: anchor=raw/motherduck-duckdb-obsidian#qh:6b325e891dd8df1dd49ab831fdb50c63701b3eba995cfefe5408f2803786f85a|loc:0.2743|len:113  "the result drops in as a markdown table, bracket"

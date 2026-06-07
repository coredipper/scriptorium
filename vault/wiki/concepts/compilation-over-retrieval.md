---
id: concept/compilation-over-retrieval
type: wiki.concept
title: Compilation over retrieval
derived-from:
- raw/karpathy-llm-wiki
- raw/motherduck-duckdb-obsidian
- raw/ganglani-local-rag
confidence: 0.82
input-hash: sha256:40196025b8b114a48e753cdbcbc6c4e6e6d67639d54ddfae480139faeacf9410
last-compiled: '2026-06-07T20:59:44Z'
---
Compilation over retrieval is the principle that a knowledge base should *accumulate* synthesized understanding rather than re-derive answers from raw sources on every query.[^a1] It is the opposite of naive RAG, whose incremental cost is punishing: adding a single note forces a full re-index.[^a2]

The pay-off is that good answers compound into the corpus instead of evaporating after each session.

[^a1]: anchor=raw/karpathy-llm-wiki#qh:91ac5a4417547421b0ab889e44773d5d3e6d6674e46c1c8ca221ab80068755e4|loc:0.2853|len:95  "Knowledge should be compiled into a maintained w"
[^a2]: anchor=raw/ganglani-local-rag#qh:cb53a05e50051862988d8ee33850d68b0711441520820bb3aa55fcc6a23b227d|loc:0.4689|len:57  "Adding a new note currently means re-indexing ev"

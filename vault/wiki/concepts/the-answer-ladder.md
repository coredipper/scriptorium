---
id: concept/the-answer-ladder
type: wiki.concept
title: The answer ladder
derived-from:
- raw/karpathy-llm-wiki
- raw/motherduck-duckdb-obsidian
- raw/ganglani-local-rag
confidence: 0.85
input-hash: sha256:40196025b8b114a48e753cdbcbc6c4e6e6d67639d54ddfae480139faeacf9410
last-compiled: '2026-06-07T21:20:14Z'
---
Compile, cache, and retrieve are not rival architectures but rungs of one policy. The default is cached: when the compiled layer covers a question, the agent reads the precomputed note with no re-fetch cost.[^a1] The system stays cached by default, live when it matters[^a2] — recompiling only the slice that has gone stale, and retrieving from raw sources only on a genuine miss.

[^a1]: anchor=raw/motherduck-duckdb-obsidian#qh:75bd527ad4c29051ce29232e9fe5cb2a058f8d1922edd59e27e3e1441ef0f0d1|loc:0.7157|len:114  "the agent reads the note. No query, no MCP round"
[^a2]: anchor=raw/motherduck-duckdb-obsidian#qh:89a35437ec2d8a1852ab65d527218d942a88f4c3332bfaa748a0b3b98abeaeeb|loc:0.6334|len:39  "cached by default, live when it matters"

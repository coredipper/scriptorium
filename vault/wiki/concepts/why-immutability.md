---
id: concept/why-immutability
type: wiki.concept
title: Why raw sources are immutable
derived-from:
- raw/karpathy-llm-wiki
confidence: 0.8
input-hash: sha256:ac266ef6c8a695ffd19c948d79cb5f6281dbf6915657b67b50f7f0280fd86b8f
last-compiled: '2026-06-07T21:20:14Z'
---
Immutability of `raw/` is load-bearing: because anchors hash the stored source text, citations only break on a deliberate re-ingest, never on a reformat.[^a1]

[^a1]: anchor=raw/karpathy-llm-wiki#qh:6fe1007c44f73a926f84d4a20a67148cb771a283b4fcf771cbff6cd8d5249d88|loc:0.5152|len:58  "Raw sources stay immutable; the wiki layer is re"

# Why scriptorium — compile, cache, retrieve as one ladder

Three well-known designs each capture one third of "talk to your own knowledge,"
and each hand-waves the parts the other two are good at. scriptorium's claim is
that those three moves are not competing architectures — they are **rungs of one
answer policy**, chosen per question by *freshness* and *coverage*.

## The three priors

- **Karpathy's LLM wiki** *compiles* sources into synthesized markdown an agent
  maintains. Knowledge compounds and is cheap to read. But "freshness,"
  "provenance," and "lint/contradiction" are named, not defined — and there is no
  structured, queryable fact layer.
- **MotherDuck's Obsidian + DuckDB plugin** *caches* query results inline as
  frozen markdown tables wrapped in a `hash + connection + timestamp + rows`
  sentinel; an agent reads the precomputed answer in seconds with zero re-fetch
  tokens. But it handles only tabular external data — no synthesis, no prose
  provenance — and "fresh" means *re-run the SQL*, not *the meaning drifted*.
- **A local RAG (llm.c)** *retrieves* raw chunks by embedding similarity, fully
  private. But naive chunking discards structure, **every new note re-indexes the
  whole corpus**, latency is poor, and nothing is ever synthesized.

## Why each fails alone

| | Freshness | Provenance | Structured query | Synthesis | Incremental |
|---|---|---|---|---|---|
| compile-only (wiki) | ✗ undefined | ✗ undefined | ✗ | ✓ | ~ |
| cache-only (DuckDB) | ~ SQL re-run | ✗ (tables only) | ✓ | ✗ | ✓ |
| retrieve-only (RAG) | ✗ | ~ (chunk → doc) | ✗ | ✗ | ✗ full re-index |
| **scriptorium** | ✓ dep-graph | ✓ content anchors | ✓ facts/ | ✓ wiki/ | ✓ per-artifact |

## What the fusion adds

Two primitives the priors lack do all the real work:

1. **A content-hash dependency graph.** Every derived artifact records a hash of
   its inputs at compile time. Staleness becomes *decidable from the files*: a
   source changes, exactly its dependents go stale, and only those recompile.
   This is the generalization of MotherDuck's sentinel from "one SQL block" to
   "any synthesized artifact," and it is the concrete definition Karpathy's "lint"
   was missing.
2. **Content-anchored provenance.** A citation is a hash of the quoted text, not a
   line number, checked by re-finding it in the source. Citations become a
   *reproducible boolean*, and — because the hash is over text we store, not the
   live PDF — re-extraction can never silently rot a reference.

On top of those, the **answer ladder** unifies the three verbs: prefer compiled
knowledge (cheap, like the cache), recompile only the stale slice (live when it
matters), and fall back to retrieval only on a true miss — then *promote* that
answer back into the compiled layer so the corpus compounds.

## The cost argument

A question answered from a fresh compiled page costs no retrieval and no
re-derivation — the MotherDuck "6-second" win, generalized to prose. When a
source changes, only the artifacts that *depend on the changed bytes* recompile —
not the corpus, fixing RAG's re-index tax. The expensive model calls happen once,
at compile time, and amortize over every future read.

## Honest limits

- **Synthesis quality** is still the model's job; the contract guarantees
  *traceability*, not *correctness* of prose.
- **Contradiction recall is bounded.** Detection only fires on claims sharing a
  `subject`+`predicate` with opposing polarity; differently-phrased conflicts slip
  through. This is a deliberate trade of recall for determinism — we would rather
  never flaky-flag and never silently overwrite than catch every semantic clash.
- **Block ids are positional** in v0, so inserting a paragraph renumbers them;
  whole-file dependencies are the safe default until content-derived block ids
  land (see [SPEC §11](SPEC.md#11-versioning)).
- **Single-writer** in v0. Concurrent agents need an advisory lock, deferred.

The point is not to be clever. It is to make *staleness* and *provenance* —
the two things every prior design left to faith — into things you can compute.

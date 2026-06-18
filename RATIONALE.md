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

## Related lineages — what this is *not*

The three priors above are scriptorium's *direct* ancestors. Its *spiritual* one
is older — the **commonplace book**, a personal compilation of quotations indexed
and cross-referenced over a lifetime (it sits in the vault as a seed source). What
scriptorium is **not** is a **Zettelkasten**, and the difference is load-bearing,
not cosmetic.

A Zettelkasten permanent note is deliberately *detached* from its source: you
read, internalize, and rewrite the idea in your own words, and the note then
stands on its own — trusted because a *human* internalized it. scriptorium does
the opposite. Every synthesized claim stays *attached* to immutable source bytes
through a verifiable anchor, because an *agent's* "internalization" cannot be
trusted the way a person's can. Detachment is the right call for a human thinking
tool; attachment is the only safe call for a machine-maintained reference. That
one split explains the rest: content-derived ids rather than Luhmann's branching
positional ones (two answers to the same "stable address under insertion"
problem — content-addressing vs. notation-with-gaps), typed `source → derived`
edges rather than emergent bidirectional wikilinks, and *decidable staleness*
where a Zettelkasten has no notion of a note going out of date at all.

The jobs differ too. A Zettelkasten optimizes a human's *serendipitous* idea
generation through dense, hand-authored links; scriptorium optimizes a
*verifiable, queryable, always-fresh* answer layer an agent maintains. That a
scriptorium vault also opens cleanly in Obsidian (see `adapters/obsidian/`) is a
browsing convenience, not a claim to be a slip-box. The overlap is the goal —
"talk to your own knowledge" — not the method.

## Honest limits

- **Synthesis quality** is still the model's job; the contract guarantees
  *traceability*, not *correctness* of prose.
- **Contradiction recall is bounded.** Detection only fires on claims sharing a
  `subject`+`predicate` with opposing polarity; differently-phrased conflicts slip
  through. This is a deliberate trade of recall for determinism — we would rather
  never flaky-flag and never silently overwrite than catch every semantic clash.
- **Block ids are content-derived** (SPEC v2), so inserting a paragraph no longer
  renumbers others and block-precise dependencies are insertion-stable; the one
  residual edge is *normalized-identical duplicate* blocks (byte-identical, or
  differing only in case/whitespace), disambiguated by occurrence order (see
  [SPEC §7.2](SPEC.md#72-sub-source-granularity-blocks)). Whole-file dependencies
  remain the safe default.
- **Single-writer** in v0. Concurrent agents need an advisory lock, deferred.

The point is not to be clever. It is to make *staleness* and *provenance* —
the two things every prior design left to faith — into things you can compute.

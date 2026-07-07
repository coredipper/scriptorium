# Improvement Plan

This roadmap turns the audit findings into implementation milestones.

## Phase 1 — Contract Credibility

Status: implemented in this repo.

- Add the missing reconciliation record for the dogfooded contradiction pair.
- Regenerate the seed script so the example vault remains reproducible.
- Make CI fail on open contradictions unless they are explicitly reconciled.
- Make open contradictions visible in the Obsidian dashboard.
- Correct stale documentation that described the embeddings index as a stub.
- Reword top-level positioning so the repo claims a verifiable contract, not a
  turnkey document-chat product.

## Phase 2 — Answer Surface

Status: implemented.

`scrip-harness answer "question"` makes the answer ladder concrete:

1. Run `scrip status` and refuse to answer from stale artifacts unless the caller
   passes an explicit override.
2. Query `facts/` and read relevant `wiki/` pages first.
3. Fall back to `scrip search` on a miss.
4. Ask the model to draft an answer using only returned evidence.
5. Emit citations as existing claim ids or verified raw anchors.
6. Optionally write `wiki/explorations/<slug>.md`.

It is tested with the same harness style as COMPILE/EXTRACT: model stubbed, real
`scrip` commands underneath.

## Phase 3 — PageIndex Adapter

Status: initial implementation complete.

Optional long-document retrieval is wired without making PageIndex part of the
contract:

- Store tree state under `.kb/pageindex/<slug>/`.
- Fingerprint it with the current `raw/<slug>` content hash.
- Return verbatim snippets from `vault/raw/`, not uncited summaries.
- Keep `scrip status` and `scrip verify` independent of PageIndex.
- Add `scrip pageindex build`, `scrip pageindex search`, and
  `scrip search --long-docs pageindex`.

## Phase 4 — Product Boundary

Status: ongoing.

Keep comparisons honest:

- OpenKB is the product-like document-to-wiki/query/chat surface.
- PageIndex is the long-document retrieval primitive.
- scriptorium is the verifiable file contract and deterministic keeper.

Future work should integrate with those layers where useful, rather than
rebuilding their entire product surface.

## Phase 5 — Semantic Layer

Status: initial implementation started.

The Knowledge Graph Guys' recurring lesson maps cleanly onto the next layer of
scriptorium: a graph becomes more useful when its identifiers and relationships
are constrained by explicit semantics, not just free-text labels.

Implemented:

- Optional `vault/ontology.yaml` vocabulary.
- `scrip ontology` validates and summarizes that vocabulary.
- `scrip fact add` validates claim predicates, entity kinds, and edge kinds when
  the ontology exists.
- Claim predicate aliases canonicalize before storage, improving deterministic
  contradiction grouping without adding model judgment.
- Entity rows may carry optional external identity metadata (`uri`, `same_as`,
  `external_ids`) while retaining local `entity/<slug>` ids as the contract
  identity.
- Harness EXTRACT and GRAPH prompts include the active ontology summary, so model
  drafts prefer local vocabulary before deterministic validation runs.
- `scrip-harness answer` includes a bounded, ranked `graph_context` packet from
  relevant entities and edges. This is context-only: final citations still have
  to be claim ids or verified raw quotes.

Next:

- Add focused views over the graph rather than whole-graph visualization, avoiding
  the usual unreadable graph hairball.

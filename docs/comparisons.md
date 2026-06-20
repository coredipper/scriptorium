# Comparisons

scriptorium is a reference implementation of a verifiable file contract:
Markdown raw sources, NDJSON facts, compiled wiki pages, content-hash
staleness, and content-anchored provenance. It is deliberately narrower than a
turnkey knowledge-base product.

| System | Primary job | Strength | What it does not solve for scriptorium |
|---|---|---|---|
| scriptorium | Verifiable local knowledge-base contract | Staleness and citation validity are computed from files; facts are queryable; reconciliations are append-only | Broad ingestion UX, rich chat, large-document tree retrieval, hosted UI |
| OpenKB | End-user document-to-wiki CLI | Add files/URLs, compile wiki pages, query/chat, generate skills, integrate PageIndex for long PDFs | Machine-checkable provenance anchors and dependency hashes are not its central contract |
| PageIndex | Long-document retrieval/indexing primitive | Hierarchical tree index over long PDFs/Markdown; reasoning-based retrieval without a vector DB | Maintained wiki, facts layer, contradiction ledger, file-level staleness contract |
| Traditional vector RAG | Retrieve chunks at query time | Simple to wire up; broad ecosystem | Knowledge does not compound; citations usually point to chunks, not verified source spans |

## Positioning

Use **OpenKB** when you want a product-like workflow: initialize a KB, add
documents, chat/query, and generate skills.

Use **PageIndex** when the hard problem is finding the right sections of a long
document before synthesis.

Use **scriptorium** when the hard problem is trust in the maintained artifact:
which compiled pages are stale, which citations still resolve, which facts are
queryable, and which contradictions have been adjudicated.

The strongest integration path is not replacement. Let PageIndex or OpenKB-style
ingestion find and summarize evidence, but commit the durable result into the
scriptorium contract: canonical raw text, verifiable anchors, stamped
dependencies, facts, and reconciliation records.

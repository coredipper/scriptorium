# adapters (deferred — post-v0)

The scriptorium contract is technology-agnostic. Concrete bindings to specific
tools live here as *adapters* so the core stays swappable. Some seams are now
partially implemented (embeddings, obsidian views); the rest document intended
seams.

## Planned adapters

- **obsidian/** — treat `vault/` as an Obsidian vault for browsing: `[[wiki-links]]`
  already match the contract's ids, and footnote anchors render as citations. No
  plugin required to read. **Partially implemented**: two optional view generators
  surface `scrip` state in-app — `dashboard.py` writes `wiki/_status.md` (staleness
  + broken citations) and `graph_view.py` writes `wiki/_graph.md` (the
  `facts/graph.ndjson` relationship map as clickable links). Both are
  frontmatter-less views — deleting them leaves a fully valid vault.

- **embeddings/** — the retrieval rung (rung 4 of the answer ladder). **Now
  implemented** as the optional `[embeddings]` extra (`scrip/src/scrip/embeddings.py`,
  using model2vec static embeddings). `scrip index` builds a block-level index
  over `vault/raw/` into `.kb/embeddings/`; `scrip search` uses it, falling back
  to grep when the extra is not installed. The contract is unchanged — embeddings
  are a cache for *finding* sources, never the source of truth.

- **lock/** — multi-writer coordination (`.kb/lock`, advisory). v0 is single-writer
  (one agent). Needed before concurrent agents maintain the same vault.

## The rule for any adapter

An adapter may make the vault nicer to use or faster to search. It must never
become the source of truth, and removing it must leave a fully valid vault behind
(`scrip status` and `scrip verify` still pass from the files alone).

# PageIndex Adapter

This is the implemented adapter shape for long-document retrieval. It keeps
PageIndex as a regenerable cache and keeps `vault/raw/` as the source of truth.

The repo ships the `scrip` cache plumbing and CLI surface, not a vendored
PageIndex dependency. If no importable backend is installed, the PageIndex
commands exit cleanly and normal `scrip search` still falls back to
embeddings/grep.

## Goals

- Use PageIndex to navigate long PDFs or Markdown sources.
- Return evidence that can still become a `scrip anchor` citation.
- Never make PageIndex state authoritative for staleness or provenance.
- Allow deleting `.kb/pageindex/` without changing `scrip status` or
  `scrip verify`.

## Storage

```text
.kb/pageindex/
  <slug>/
    tree.json
    meta.json
```

`meta.json` should include:

```json
{
  "source_id": "raw/paper",
  "raw_content_hash": "sha256:...",
  "backend": "pageindex",
  "backend_version": "...",
  "schema": 1,
  "created_at": "..."
}
```

The adapter is stale when `raw_content_hash` differs from the current
`vault/raw/<slug>.md` hash. This mirrors the embeddings adapter: stale retrieval
is a warning, not contract breakage.

## Commands

Implemented commands:

```sh
scrip pageindex build raw/paper
scrip pageindex search "question" --source raw/paper
scrip search "question" --long-docs pageindex
```

`scrip pageindex build` builds `.kb/pageindex/<slug>/tree.json` and
`.kb/pageindex/<slug>/meta.json` for one raw source. `scrip pageindex search`
searches cached PageIndex sections directly. `scrip search --long-docs pageindex`
tries that cache first and falls back to the current embeddings/grep path when
no usable cache exists.

The adapter looks for an importable backend named `pageindex` or `page_index`
that exposes `build` or `build_index`; `search` is optional because cached
records can still be ranked lexically.

## Evidence Contract

Search results must include enough information to mint normal anchors:

```json
{
  "source_id": "raw/paper",
  "section_id": "0007",
  "score": 0.82,
  "snippet": "verbatim text from vault/raw/paper.md",
  "span_hint": [12345, 12620],
  "method": "pageindex"
}
```

The important field is `snippet`: it must be copied from the canonical
`vault/raw/` text, not from a lossy OCR/tree summary. Any final wiki citation or
claim still goes through `scrip anchor` or `scrip fact add`, so a PageIndex
mistake cannot become trusted provenance without resolving against raw text.

Both build and search results are normalized back to cached raw-text snippets.
Backend summaries or search records that cannot be mapped to a cached raw
snippet are dropped.

## Non-Goals

- Do not store PageIndex summaries in `facts/` unless they are re-extracted as
  anchored claims.
- Do not treat PageIndex node ids as citation ids.
- Do not make `scrip status` depend on PageIndex being installed.
- Do not rewrite the raw source when rebuilding the PageIndex cache.

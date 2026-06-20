# PageIndex Adapter Design

This is the intended adapter shape for long-document retrieval. It keeps
PageIndex as a regenerable cache and keeps `vault/raw/` as the source of truth.

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
  "created_at": "..."
}
```

The adapter is stale when `raw_content_hash` differs from the current
`vault/raw/<slug>.md` hash. This mirrors the embeddings adapter: stale retrieval
is a warning, not contract breakage.

## Commands

Proposed commands:

```sh
scrip pageindex build raw/paper
scrip pageindex search "question" --source raw/paper
scrip search "question" --long-docs pageindex
```

The first two can live in an optional adapter module or separate package. The
third should only call PageIndex when the adapter is installed and a usable cache
exists; otherwise it should fall back to the current embeddings/grep path.

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

## Non-Goals

- Do not store PageIndex summaries in `facts/` unless they are re-extracted as
  anchored claims.
- Do not treat PageIndex node ids as citation ids.
- Do not make `scrip status` depend on PageIndex being installed.
- Do not rewrite the raw source when rebuilding the PageIndex cache.

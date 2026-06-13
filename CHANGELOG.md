# Changelog

All notable changes to scriptorium are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/); versions track the `scrip`
reference CLI. The file **contract** is versioned separately in
[SPEC.md](SPEC.md) (currently `version: 2`).

## [0.4.0] — 2026-06-13

PROMOTE joins the automated loop: a deterministic overlap scorer and a harness
command that merges duplicate pages or keeps them — leaving RECONCILE as the
only stage still driven by hand. (scriptoria and scrip-harness both move to
0.4.0; the harness pins `scriptoria>=0.4`, since `promote` shells out to the new
`scrip similar`.)

### Added
- **`scrip similar --title "…" --from raw/a,raw/b [--kind concept|entity] [--exclude ID] [--top N]`**
  — a deterministic topic-overlap scorer for PROMOTE step 1: ranks existing wiki
  pages by normalized-title token Jaccard + shared `derived-from` (block suffix
  stripped) + shared tags (derived from `claims.ndjson` via `source_id ∈
  derived-from`, since pages carry no `tags` frontmatter). Purely informational
  (always exit 0); the High/Middle/Low merge decision stays the caller's,
  mirroring `query contradictions`.

- **`scrip-harness promote <slug>`** — makes AGENT.md PROMOTE runnable: scores a
  compiled page against existing pages with `scrip similar`, then merges into the
  best match (high overlap, deterministic), keeps it (low), or asks the model
  (middle band — the only model use). A merge appends the absorbed page with its
  footnotes renumbered, folds its sources/​id into the target's
  `derived-from`/`supersedes`, deletes the absorbed page, and re-stamps +
  re-verifies. `--dry-run` reports the decision without mutating.

### Packaging
- **`scrip-harness` is published to PyPI** (`uv tool install scrip-harness`),
  with its own `harness-v*` release path (`release-harness.yml`); a CI assertion
  proves the published wheel declares `scriptoria` by version, never the dev path
  source. The harness versions independently of the `scrip` CLI.

## [0.3.0] — 2026-06-13

EXTRACT joins the automated loop — the facts layer gets its missing
deterministic writer — and the release pipeline is hardened so this cut ships
through a matrix-tested, lint-gated build.

### Added
- **`scrip fact add [--table claims|entities|edges] (--stdin | --file F)`** — a
  validated, locked writer for the facts/ layer, completing the
  model-proposes/scrip-verifies pattern for EXTRACT: a proposed claim carries a
  **verbatim `quote`** (never an anchor/id/timestamp — scrip mints those), the
  anchor is verified to resolve uniquely, the batch is **all-or-nothing** with
  per-record failures reported (exit 1), exact duplicates are skipped so
  re-extraction is idempotent, the claim sources are merged into
  `facts/_meta.yaml` `derived-from`, and every append (any table) drops the
  set's `input-hash` — the facts set honestly shows STALE until `scrip stamp`
  re-blesses it.
- **`scrip-harness extract <slug>`** — makes the AGENT.md EXTRACT step runnable
  for claims: Claude proposes structured claims; `scrip fact add` verifies and
  appends; BROKEN/AMBIGUOUS quotes are re-asked (bounded retries) with
  lengthened replacements or dropped; contradiction candidates are surfaced for
  RECONCILE.

### Hardening
- **CI now tests the support claim**: both suites run on Python 3.10–3.14
  (previously one unpinned version), with the `[ingest]` extra installed so the
  HTML/PDF extraction tests actually execute in CI (they had silently skipped).
- **Lint + typecheck in CI**: `ruff check` (pyflakes/pycodestyle errors, import
  order, pyupgrade, bugbear) and `pyright` (basic, pinned) over both packages.
- **The release workflow cuts a GitHub Release** (auto-generated notes) after a
  successful PyPI publish.
- **`.kb/manifest.json` is no longer intended for commit**: SPEC §8 already
  treats it as a regenerable cache that *may* be committed; the repo now
  gitignores it (its `(mtime, size)` records are wrong on every fresh clone).
- A missing/unreadable raw source is now a clean `CompileError` in
  `scrip-harness compile` (parity with `extract`).
- CLI test coverage for `status`, `index`, `unlock`, the `watch` loop, the
  embeddings search path (deterministic toy encoder), and `--json` output
  shapes across commands; packaging metadata (classifiers, URLs) for both
  packages.

## [0.2.0] — 2026-06-08

The first complete, releasable cut beyond the v0 end-to-end slice: the contract
is hardened, the maintaining loop is automated, and the agent loop is runnable.

### Contract (SPEC v1 → v2)
- **Content-derived block ids.** Block ids are now a digest of each block's
  normalized text instead of positional `b0,b1,…`, so inserting a paragraph no
  longer renumbers others — block-precise dependencies are insertion-stable. The
  one residual edge (normalized-identical duplicate blocks) is documented.
- **Manifest `version` 1 → 2;** a v1 manifest is discarded as a cache miss and
  regenerated (the manifest is never truth).

### Added
- **`scrip ingest <url|file>`** — fetch/read a source, extract canonical text, and
  write `raw/<slug>.md` + `.meta.yaml`. HTML/PDF via the optional `[ingest]` extra
  (`trafilatura`, `pypdf`); `.md`/`.txt` passthrough. Charset-correct decoding
  (HTTP header + WHATWG label normalization + in-document `<meta>`). Immutable raw;
  `--reingest` is the tracked overwrite.
- **`scrip anchor "<quote>" --source raw/<slug>`** — mint a verified provenance
  anchor and print a ready footnote; exits 1 on a non-unique/broken quote.
- **`scrip new concept|entity <slug> --from raw/…`** — scaffold a wiki page's
  frontmatter for the agent to fill.
- **`scrip unlock [--force]`** — clear the advisory write lock.
- **`scrip watch`** — re-run `status` + `verify` whenever the vault changes.
- **`scrip status --fast`** — opt-in acceleration that trusts `(mtime, size)` to
  skip re-hashing unchanged sources (see the tradeoff note below).
- **Advisory multi-writer lock** (`.kb/lock`): mutating commands serialize;
  reads never lock; a dead-process lock is reclaimed, a live one fails fast (2).
- **`scrip-harness`** — a separate, optional package that makes the AGENT.md
  COMPILE step runnable (Claude drafts → `scrip` mints/stamps/verifies). `scrip`
  never imports a model SDK.

### Changed
- The canonical text normalization is shared by anchors and block ids (one
  definition; they cannot drift).
- The embeddings index fingerprint includes a block-id schema version, so a v1
  positional-id index is detected as stale rather than silently returning ids
  that no longer resolve.

### Notes
- Published to PyPI as **`scriptoria`** (`scrip` and `scriptorium` were already
  taken); the CLI command and the import package both remain `scrip`.
- `scrip status --fast` deliberately trades the "always re-hash" guarantee
  (SPEC §8) for speed: an edit that preserves both mtime and size is missed.
  Plain `scrip status` always re-hashes and remains the safe default.

## [0.1.0] — 2026-06-07

- Initial v0: the technology-agnostic file contract (SPEC v1), the `scrip`
  reference CLI (`status`, `verify`, `stamp`, `query`, `search`, `index`), the
  optional embeddings retrieval rung, and a dogfooded example vault.

[0.4.0]: https://github.com/coredipper/scriptorium/releases/tag/v0.4.0
[0.3.0]: https://github.com/coredipper/scriptorium/releases/tag/v0.3.0
[0.2.0]: https://github.com/coredipper/scriptorium/releases/tag/v0.2.0
[0.1.0]: https://github.com/coredipper/scriptorium/releases/tag/v0.1.0

# Changelog

All notable changes to scriptorium are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/); versions track the `scrip`
reference CLI. The file **contract** is versioned separately in
[SPEC.md](SPEC.md) (currently `version: 2`).

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

[0.2.0]: https://github.com/coredipper/scriptorium/releases/tag/v0.2.0
[0.1.0]: https://github.com/coredipper/scriptorium/releases/tag/v0.1.0

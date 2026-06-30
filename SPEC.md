# The scriptorium contract (v2)

This is a **technology-agnostic file contract** for an agent-maintained knowledge
base. It says what the files on disk mean — nothing about which agent, editor, or
language you use. The `scrip` CLI in this repo is one *reference implementation*;
any tool that reproduces the behaviours in [Conformance](#conformance) is
compliant.

The contract exists to make two things true that prior designs left undefined:

1. **Staleness is decidable.** Given the files alone, you can compute exactly
   which derived artifacts are out of date with respect to their sources.
2. **Provenance is checkable.** Given the files alone, you can confirm that every
   synthesized claim still points at text that actually exists in its source.

Everything else (synthesis quality, what to write, when to ingest) is judgment,
and judgment belongs to the agent, not the contract.

---

## 1. Purpose & non-goals

**Purpose.** A portable substrate where an agent *compiles* raw reading into
durable, synthesized knowledge, *extracts* structured facts from it, and answers
questions by preferring compiled knowledge — falling back to retrieval only when
the compiled layer misses, and recompiling only what has gone stale.

**Non-goals.**
- Not a database. The files are the source of truth; any index is a cache.
- Not a tool lock-in. Markdown + NDJSON + YAML; no proprietary format.
- Not a retrieval engine. Embedding retrieval is an *optional adapter* for one
  rung of the answer policy, not the foundation.

---

## 2. Layers

Three layers live under `vault/`. They form a strict derivation order: `raw` is
authored/curated by a human or ingest step and never edited by the agent;
`facts` and `wiki` are **siblings compiled from `raw`**.

```
vault/
  raw/      immutable sources (+ .meta.yaml sidecars)   ← never edited after ingest
  facts/    structured extractions, queryable as data   ← derived from raw/
  wiki/     synthesized prose (concepts, entities)       ← derived from raw/
```

### 2.1 `raw/`
- Each source is a UTF-8 markdown file `raw/<slug>.md` whose text is **canonical**:
  if the source was a PDF/HTML page, the *extracted text we store here* is what
  everything else hashes and cites — not the original binary.
- A sidecar `raw/<slug>.meta.yaml` carries bibliographic metadata
  (`title`, `author`, `url`, `retrieved`, …). The sidecar is metadata, not a
  source: it is not hashed as content and not citable.
- A raw source's **content hash** is `sha256` of its exact bytes. Any byte change
  is, by definition, a new version that propagates staleness to dependents.

### 2.2 `facts/`
Newline-delimited JSON (one record per line), queryable directly as data:
- `facts/entities.ndjson` — entities (people, works, organizations, systems).
- `facts/claims.ndjson` — the claims table (§5).
- `facts/graph.ndjson` — edges between entities/sources (citation/idea graph). An
  edge is `{src, dst, kind}`; it may optionally be **cited** — carrying a verbatim
  `quote` + `source_id` whose `anchor` scrip mints and verifies exactly as for a
  claim (§6). A bare edge stays purely structural.
- `facts/reconciliations.ndjson` — RECONCILE decisions over contradiction pairs
  (§9.2). Optional: absent until the first reconciliation is recorded.
- `facts/_meta.yaml` — the **facts-set frontmatter**: this set's `derived-from`,
  `input-hash`, `last-compiled` (so the facts layer goes stale independently of
  the wiki).

NDJSON is required (not a single JSON array, not one file per record) so the set
appends without rewrites and diffs line-by-line in git.

### 2.3 `wiki/`
- `wiki/concepts/<slug>.md` and `wiki/entities/<slug>.md` — synthesized pages,
  each with frontmatter (§4) and inline provenance footnotes (§6).
- `wiki/index.md` — a human map of the wiki (not a tracked derived artifact).
- `wiki/log.md` — an append-only journal of compiles, answers, reconciliations
  (not a tracked derived artifact).

---

## 3. Identifiers

| Layer | id form | example |
|---|---|---|
| raw source | `raw/<slug>` | `raw/motherduck-duckdb-obsidian` |
| concept page | `concept/<slug>` | `concept/compilation-over-retrieval` |
| entity page | `entity/<slug>` | `entity/duckdb` |
| facts set | `facts/<name>` | `facts/core` |

A `raw/<slug>` id maps to the file `vault/raw/<slug>.md`. Block-scoped ids append
`#<block_id>` (§7.2), e.g. `raw/friston-2010#b3f9a1c2d4e5`.

---

## 4. Frontmatter schema (derived artifacts)

Every tracked derived artifact (a wiki page, or `facts/_meta.yaml`) carries:

| key | type | meaning |
|---|---|---|
| `id` | string | the artifact id (§3) |
| `type` | string | `wiki.concept` \| `wiki.entity` \| `facts.set` |
| `title` | string | human title (wiki pages) |
| `derived-from` | list | source ids this artifact was compiled from; each is `raw/<slug>` or `raw/<slug>#<block>` |
| `input-hash` | string | hash of the inputs at compile time (§7.1) |
| `last-compiled` | string | ISO-8601 UTC timestamp of the last compile/stamp |
| `confidence` | number | the agent's self-rated synthesis confidence in `[0,1]` |
| `supersedes` | list | ids merged into this artifact (promotion/dedup audit trail) — optional |

A wiki page is stored as `---\n<yaml>\n---\n<body>`. The facts set stores the same
keys as a plain YAML document in `facts/_meta.yaml`.

---

## 5. Claims schema (`facts/claims.ndjson`)

One JSON object per line:

```json
{"claim_id":"clm_000142","subject":"DuckDB Obsidian plugin","predicate":"caches","object":"SQL results as frozen markdown tables","claim_text":"The plugin freezes a query result as a plain-markdown table wrapped in a sentinel comment.","source_id":"raw/motherduck-duckdb-obsidian","anchor":"qh:7c1a…|loc:0.41|len:96","confidence":0.88,"polarity":"asserts","extracted_at":"2026-06-07T10:35:02Z","tags":["caching","provenance"]}
```

| field | required | meaning |
|---|---|---|
| `claim_id` | ✓ | stable, unique id |
| `source_id` | ✓ | the `raw/<slug>` the claim is drawn from (must exist) |
| `anchor` | ✓ | provenance anchor into `source_id` (§6) |
| `claim_text` | | the human-readable claim |
| `subject`, `predicate`, `object` | | a coarse triple used for grouping & contradiction detection |
| `polarity` | | `asserts` \| `denies` \| `qualifies` — **load-bearing** for contradiction detection (§9) |
| `confidence` | | `[0,1]` |
| `extracted_at` | | ISO-8601 UTC |
| `tags` | | list of strings |

---

## 6. Provenance anchors

An anchor cites a span of a source **by the content of the quote**, not by line
number, so it survives reformatting and can be machine-verified.

**Format:** `qh:<hex>|loc:<frac>|len:<n>`
- `qh` — `sha256` (hex) of the **normalized quote**.
- `loc` — fractional start offset of the quote in the normalized source `[0,1)`;
  a disambiguation hint, not required to be exact.
- `len` — length of the normalized quote in characters.

**Normalization** (identical at write- and verify-time): Unicode NFC → collapse
every run of whitespace to a single space → strip ends → lowercase.

**In wiki prose**, anchors appear as markdown footnotes whose target is
`<source_id>#<anchor>`:

```markdown
…good answers become wiki pages.[^a1]

[^a1]: anchor=raw/karpathy-llm-wiki#qh:3b9e…|loc:0.41|len:34  "good answers become wiki pages"
```

**Verification.** To check an anchor, normalize the source, then slide a window of
`len` characters and hash each window:
- exactly one matching window → **OK**
- zero matches → **BROKEN** (the citation no longer resolves)
- more than one match → **AMBIGUOUS** (the citation does not resolve *uniquely*)

`verify` **fails (exit 1) on BROKEN and on AMBIGUOUS by default** — a citation
must resolve to exactly one span. The remedy for AMBIGUOUS is to lengthen the
quote until unique; `--allow-ambiguous` downgrades it to a warning (resolving to
the span nearest `loc`).

Because `qh` is computed over the *stored* `raw/` text, re-extracting a PDF with a
different tool cannot silently break anchors; only a deliberate **re-ingest**
(new bytes under the same id) can — and that surfaces as ordinary staleness.

---

## 7. Dependency graph & staleness

### 7.1 input-hash
For a derived artifact `D` with `derived-from = [s1, s2, …]`, let
`h(s)` be the current content hash of dependency `s`. Then:

```
input-hash(D) = sha256( "\n".join( sorted( f"{s}:{h(s)}" for s in derived-from ) ) )
```

Sorting makes the result independent of declaration order. `D` is **STALE** iff
any of:
- a declared dependency no longer exists,
- `D` has no recorded `input-hash` (never compiled), or
- the recomputed `input-hash` ≠ the stored one.

Otherwise `D` is **OK**. A raw source that no dependency references is
**UNCOMPILED** (informational, not an error).

### 7.2 Sub-source granularity (blocks)
A source may be split into deterministic blocks (heading lines and
blank-line-separated paragraphs), each with a `block_id` and a hash of its sliced
text. A derived artifact may then declare block-scoped dependencies
(`raw/x#<block_id>`), so a one-paragraph edit only invalidates artifacts that
depend on that block.

The `block_id` is **content-derived**: a short digest of the block's *normalized*
text (the §6 normalization), so it is a function of content, not position.
Consequences:
- **Insertion-stable.** Inserting a block elsewhere leaves every other block's id
  unchanged, so dependents of unaffected blocks stay fresh. (In v1 ids were
  positional and an insertion renumbered them, falsely staling dependents.)
- **Reflow-stable identity.** Whitespace/case reformatting does not change a
  block's id; the separate exact-slice `hash` still changes, so a dependent of a
  reflowed block goes STALE via an input-hash mismatch (§7.1), not a vanished id.
- **Duplicate disambiguation.** Blocks with identical *normalized* text
  (byte-identical, or differing only in case/whitespace) share a base id; the
  first keeps the bare id and later repeats take an occurrence suffix (`…:1`,
  `…:2`). A dependency on such a *duplicated* block is inherently positional and
  may shift if an earlier normalized-identical copy is inserted — the one residual
  edge (§11 Versioning).

Whole-file dependencies remain the safe default; block-precise dependencies are
**opt-in**.

---

## 8. Manifest (the cache)

`.kb/manifest.json` (`version: 2`) records, per raw source, its
`content_hash`/`blocks` plus `(mtime, size)`; and per derived artifact, its
`derived-from`/`input-hash`/`last-compiled`. It is a **cache, not truth**:

- Any computation must be reproducible **without** the manifest. Deleting `.kb/`
  and recomputing from files must yield an identical stale/OK/uncompiled set.
- **Staleness re-hashes raw content by default.** `(mtime, size)` are recorded
  for information only and are *not* trusted to skip a re-hash — otherwise an edit
  preserving both could hide a byte change and falsely report dependents fresh.
  The manifest's stored hashes are used only to annotate *which* source changed.
  The opt-in `scrip status --fast` deliberately reverses this: it trusts
  `(mtime, size)` to reuse the cached hash for unchanged sources (faster on large
  vaults), accepting that an edit preserving both is missed. It is an explicit
  acceleration, never the default.
- It is written **atomically** (temp file + rename). A corrupt or stale manifest
  is treated as a cache miss, never an error.
- It may be committed to git for fast first reads; on a merge conflict, discard
  and regenerate (`scrip status --rebuild-manifest`).

`.kb/` holds only regenerable state: the manifest, the optional embeddings index
(`.kb/embeddings/`), and the advisory write lock (`.kb/lock`, §11). None are the
source of truth; deleting `.kb/` and recomputing from `vault/` must be a no-op.

---

## 9. The answer policy ladder

Answering a question is a descent through rungs; stop at the first that applies:

1. **Consult compiled** — look in `wiki/` and query `facts/` first
   (index-before-search).
2. **Hit & fresh** (`scrip status` clean) → answer from the compiled layer and
   cite anchors. *Cheapest path; no re-derivation.*
3. **Hit & stale** → recompile only the stale artifact from its sources
   (`scrip stamp` to re-record), then answer. *Live when it matters.*
4. **Miss** → retrieve from `raw/` via `scrip search` (grep by default; a
   semantic index when the optional embeddings adapter is built with
   `scrip index`), synthesize an answer, cite it, then **promote** it into a new
   or merged compiled page.
5. **Conflict** → if a source contradicts a compiled claim
   (`scrip query contradictions`, or a `verify` BROKEN from a replaced source),
   **reconcile** explicitly; never silently overwrite.

This ladder is the thesis: *compile, cache, and retrieve are not competitors —
they are rungs chosen by freshness and coverage.*

### 9.1 Contradiction detection
Detection is **deterministic**: contradiction *candidates* are pairs of claims
with the same `subject`+`predicate`, opposing `polarity`, from different sources.
Only *adjudication* (decide supersede / qualify / keep-both) is the agent's
judgment, applied to that bounded candidate set. This trades recall (claims
phrased with different subjects are missed) for precision and reproducibility.

### 9.2 Reconciliation
Adjudicating a contradiction is recorded **append-only** in
`facts/reconciliations.ndjson`, one record per pair:

```json
{"reconciliation_id":"rec_0001","decision":"supersede","claim_a":"clm_0009","claim_b":"clm_0003","winner":"clm_0009","rationale":"newer source measured it directly","at":"2026-06-13T10:00:00Z"}
```

| field | required | meaning |
|---|---|---|
| `reconciliation_id` | ✓ | stable, unique id (minted, not authored) |
| `decision` | ✓ | `supersede` \| `qualify` \| `keep-both` |
| `claim_a`, `claim_b` | ✓ | the adjudicated pair (existing claim ids) |
| `winner` | for `supersede` | the surviving claim (`claim_a` or `claim_b`); absent otherwise |
| `rationale` | | why this decision |
| `at` | ✓ | ISO-8601 UTC (minted) |

Existing claim rows are **never rewritten** (the loser of a `supersede` stays in
`claims.ndjson`; the record marks it superseded). Contradiction detection (§9.1)
**excludes any pair that has a reconciliation record** (either order), so the
candidate set converges as decisions are recorded.

---

## 10. Conformance

An implementation conforms if, from the files alone, it:

1. computes the same **STALE / OK / UNCOMPILED** set as §7 (verifiable: same
   result with and without the manifest);
2. returns the same anchor verdicts **OK / AMBIGUOUS / BROKEN** as §6;
3. treats the manifest as a regenerable cache (§8);
4. never edits `raw/` and never silently overwrites a contradicted claim (§9).

`scrip status`, `scrip verify`, `scrip stamp`, and `scrip query` are the reference
behaviours; their exit codes are part of the contract surface
(`0` clean · `1` finding · `2` usage · `3` data error · `4` internal).

---

## 11. Versioning

- This document is `version: 2`; the manifest carries the same.
- **Reconciliations (additive).** `facts/reconciliations.ndjson` (§9.2) was added
  as an optional facts file. It is backward-compatible: instances without it are
  unaffected, and it does not change block ids, so the manifest `version` stays
  `2` (no cache invalidation).
- **Cited edges (additive).** An edge in `facts/graph.ndjson` may optionally carry
  a verbatim `quote` + `source_id`; scrip then mints and verifies an `anchor` for
  it (§6), so `scrip verify` covers it. Backward-compatible: bare `{src,dst,kind}`
  edges are unaffected, and the optional fields do not change block ids, so the
  manifest `version` stays `2`.
- **v1 → v2 (block ids).** Block ids became content-derived (a digest of the
  normalized block text) instead of positional `b0,b1,…`, making block-precise
  dependencies insertion-stable (§7.2). The id *form* is the only change: a
  `version: 1` manifest holds positional ids and is simply discarded as a cache
  miss and regenerated (the manifest is never truth, §8). Whole-file dependencies
  are byte-for-byte unaffected. The one residual limitation is duplicate blocks:
  normalized-identical blocks (byte-identical, or differing only in
  case/whitespace) are disambiguated by occurrence order, so a dependency on one
  of several such blocks can still shift if an earlier copy is inserted.
- **Concurrency (advisory lock).** Mutating commands take an advisory lock at
  `.kb/lock` — a small JSON record `{pid, host, acquired_at}` *published
  atomically* (written to a temp file, then hard-linked into place, so the lock
  is never observed empty or half-written); reads
  (`status`/`verify`/`query`/`search`) never lock. A lock whose holder is a
  *provably-dead* process on this host is reclaimed automatically on the next
  acquire. A live, other-host, or not-yet-readable lock is **waited on**: the
  acquirer polls (with backoff) up to `SCRIP_LOCK_TIMEOUT` seconds (default `10`),
  so two agents serialize cooperatively rather than one failing immediately; if
  still held when that elapses the write fails (exit 2), with
  `scrip unlock [--force]` to clear a stuck lock. `SCRIP_LOCK_TIMEOUT=0` restores
  fail-fast. A holder that dies *during* the wait is reclaimed on the next poll; an
  other-host lock is only waited on, never reclaimed. It is advisory, not a kernel
  mutex (best-effort polling, not a fair queue), and not part of the
  files-are-truth contract — deleting it never affects `status`/`verify`.
- **Optional adapters** (outside the core contract): an embeddings retrieval rung
  (`scrip index` / `scrip search`, via the `[embeddings]` extra) and an Obsidian
  browsing layer (`adapters/obsidian/`).

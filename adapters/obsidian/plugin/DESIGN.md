# Obsidian plugin — design

Status: design approved 2026-06-17 (brainstorm). Implementation in progress.

## Goal

An actual Obsidian plugin for a scriptorium vault, complementing the existing
Python view-generators (`dashboard.py` → `_status.md`, `graph_view.py` →
`_graph.md`) with live, in-app surfaces. "File over app" still holds: the plugin
only reads/displays; it is never the source of truth, and deleting it leaves a
fully valid vault.

## Architecture — hybrid, two layers

- **Pure-TS core (desktop + mobile, no external deps).** Reads
  `vault/facts/graph.ndjson` and note frontmatter through Obsidian's vault API.
  Powers the relationship panel. Never computes hashes/staleness — it only
  *displays* what the agent wrote, honoring "scrip owns determinism."
- **Desktop shell-out layer (guarded by `Platform.isDesktopApp` + scrip
  presence).** Spawns `scrip <cmd> --root <root> --json` and parses the JSON.
  Powers the health status bar + panel. Self-disables (one-time notice) when
  `scrip` is not found; the core keeps working.

`scrip` needs **no changes**: every subcommand already accepts `--root DIR` and
`--json`. Shapes used: `status` → `{stale, ok, uncompiled}` (stale items carry
`id` / `reason` / `changed_sources`); `verify` → `{checked, ok, ambiguous,
broken}` (broken items carry `where` / `source_id`).

## v1 scope

1. **Relationship panel** (pure-TS): sidebar showing the active note's typed edges
   from `graph.ndjson` — outbound + inbound grouped by kind
   (`builds-on`/`cites`/`about`/`made-by`), click-to-open.
2. **Health status bar + panel** (desktop): badge `✓ fresh` / `⚠ N stale · M
   broken`, refreshed on load + on save (debounced); panel lists STALE artifacts
   (with the changed source) and BROKEN citations, click-to-open.
3. **Settings tab**: scrip binary path, root override (auto-detected by default),
   auto-check-on-save toggle.

**Dropped from v1 — on-disk "Regenerate _status.md/_graph.md" command.** For
plugin users the live panels already show this data, so the on-disk views are
redundant; shelling out to the Python generators adds a fragile uv/Python/project
requirement, and re-implementing their formatting in TS risks drift from the
single source of truth the project deliberately maintains. The existing CLI / cron
/ hook keep the on-disk views fresh for non-plugin viewers. If on-demand on-disk
regeneration is wanted later, the most self-contained path is pure-TS regeneration
of `_graph.md` only (the plugin already holds the graph index; works even on
mobile), accepting the format-sync cost.

## Repo layout & toolchain

```
adapters/obsidian/plugin/
  manifest.json      # id: scriptorium, isDesktopOnly: false
  package.json       # devDeps only: esbuild, typescript, obsidian, tslib
  tsconfig.json
  esbuild.config.mjs
  styles.css
  README.md          # build + sideload
  src/
    main.ts          # ScriptoriumPlugin (onload wiring)
    root.ts          # resolveRoot()
    graphIndex.ts    # parse graph.ndjson → adjacency; note <-> node mapping
    scripRunner.ts   # spawn `scrip … --json` (desktop)
    health.ts        # HealthController (status+verify → bar/panel)
    view.ts          # RelationshipView extends ItemView
    settings.ts      # ScriptoriumSettingTab + defaults
    types.ts         # shared types for scrip JSON shapes
```

The Node/npm toolchain stays entirely under this dir — it never touches the
`scrip`/`harness` builds or the Python CI. Optional separate CI job:
`tsc --noEmit` + esbuild build.

## Root resolution

From `vault.adapter.basePath`: if it contains `vault/` + (`SPEC.md` | `.kb/`) →
root = basePath; if it *is* a `vault/` dir (has `raw/ wiki/ facts/`) → root =
parent. A settings override wins. Mirrors scrip's `resolve_root` so plugin and CLI
agree on the root.

## Data flow

1. **Load** → resolve root → parse `graph.ndjson` (core ready). Desktop + scrip →
   `status` + `verify` → status bar.
2. **Active note change** → panel re-renders edges from the in-memory index
   (instant, no scrip).
3. **File modify** (debounced ~800ms) → if auto-check + desktop → re-run
   `status`/`verify`; a `graph.ndjson` change rebuilds the index.

## Error handling

- scrip missing → desktop layer self-disables + one-time notice; core unaffected.
- scrip non-zero / bad JSON → notice with stderr tail; bar shows `⚠ check failed`;
  last good result retained.
- `graph.ndjson` missing/malformed → "no relationships yet"; a malformed line is
  skipped with a console warning, never a crash.
- mobile → shell-out layer never instantiated; panel + reading an existing
  `_status.md` only.
- root unresolvable → panel prompts to set the root override.

## Testing

- **Pure modules unit-tested** (node:test, no Obsidian import): `graphIndex`
  parsing → adjacency, `root` detection (both vault layouts), the `status`/`verify`
  JSON mappers.
- **Glue** (views, bar, runner): manual verification in the dogfood vault — panel
  shows `the-answer-ladder → builds-on → compilation-over-retrieval`; bar reads
  `✓ fresh`; breaking a citation flips it to `⚠ 1 broken`.
- Build gate: `tsc --noEmit` + esbuild (optional CI job, separate from Python CI).

## Distribution

v1 = **sideload**: `npm run build` → copy `manifest.json` + `main.js` +
`styles.css` into `<vault>/.obsidian/plugins/scriptorium/`, documented in the
plugin README. `isDesktopOnly: false` keeps the core mobile-compatible.
Community-store submission is a deliberate later step.

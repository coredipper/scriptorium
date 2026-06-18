# Scriptorium — Obsidian plugin

A live, in-app companion to a scriptorium vault: **vault health** (from `scrip`)
and **relationship navigation** (from `facts/graph.ndjson`). It complements the
Python view-generators (`../dashboard.py`, `../graph_view.py`) — and, like them,
it only reads. Delete it and the vault is still fully valid.

## What it does

- **Relationship panel** (works everywhere, no dependencies): a sidebar showing
  the active note's typed edges from `facts/graph.ndjson` — outbound (`→`) and
  inbound (`←`), grouped by kind (`builds-on`, `cites`, `about`, `made-by`),
  click to open. Surfaces the relationship layer Obsidian's native graph view
  can't see (it lives in NDJSON, not in `[[wiki-links]]`).
- **Vault health** (desktop, needs `scrip`): a status-bar badge — `Scriptorium ✓`
  when fresh, `⚠ N stale · M broken` otherwise — refreshed on load and on save.
  The panel lists stale artifacts (with the changed source) and broken citations,
  click to open.
- **Command**: *Scriptorium: Check vault health (status + verify)*.
- **Settings**: `scrip` path, root override, auto-check-on-save.

## Architecture

Two layers (see [DESIGN.md](DESIGN.md)):

- **Pure-TS core** (relationship panel) reads vault files via Obsidian's API and
  never computes hashes/staleness — it only displays what the agent wrote, so it
  runs on **desktop and mobile** with no external dependency.
- **Desktop shell-out layer** (health) spawns `scrip <cmd> --root <root> --json`
  and parses the JSON. If `scrip` isn't found it disables itself with a notice and
  the core keeps working. Determinism stays in `scrip`; the plugin never
  re-implements it.

## Requirements

- Relationship panel: none.
- Vault health: Obsidian **desktop** + the `scrip` CLI installed (e.g.
  `uv tool install ./scrip` or `pipx install scriptoria`).

**macOS:** Obsidian launched from Finder/Dock often has a minimal `PATH` that
excludes `~/.local/bin`, so the plugin may report "scrip not found" even when
`scrip` works in your terminal. Fix: run `which scrip` and paste the **absolute
path** (e.g. `/Users/<you>/.local/bin/scrip`) into **Settings → Scriptorium →
scrip path**. An absolute path is invoked directly, bypassing the GUI-`PATH`
problem.

## Build

```sh
cd adapters/obsidian/plugin
npm install
npm run build      # tsc --noEmit + esbuild -> main.js
npm test           # pure-module unit tests (node --test)
npm run dev        # watch build
```

## Install (sideload)

Copy `manifest.json`, `main.js`, and `styles.css` into your vault's
`.obsidian/plugins/scriptorium/`, then enable **Scriptorium** under
Settings → Community plugins. Obsidian may be pointed either at the scriptorium
root (the directory containing `vault/`) or at `vault/` itself — the plugin
detects both. Open the panel from the ribbon (git-fork icon) or the command
palette.

## Verifying it works

Open `wiki/concepts/the-answer-ladder.md`; the panel should show
`builds-on → concept/compilation-over-retrieval`. On desktop with `scrip`
installed, the status bar should read `Scriptorium ✓`.

## Not in v1

On-disk regeneration of `_status.md` / `_graph.md` (the live panels already show
this data; the Python generators keep the files fresh for git / non-plugin
viewers) and community-store submission. See [DESIGN.md](DESIGN.md) for the
rationale.

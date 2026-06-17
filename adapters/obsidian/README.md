# Obsidian adapter

scriptorium's `vault/` *is* an Obsidian vault — no plugin required. The contract
was designed to render natively:

- **ids map to filenames** (`concept/compilation-over-retrieval` →
  `wiki/concepts/compilation-over-retrieval.md`),
- **`wiki/index.md` uses `[[wiki-links]]`** that Obsidian resolves,
- **provenance footnotes** (`[^a1]: anchor=raw/…`) render as Obsidian footnotes,
- everything is plain markdown + NDJSON on disk, so "file over app" holds: close
  Obsidian and the vault is still fully valid.

## Open it

Point Obsidian at the `vault/` directory ("Open folder as vault"). `raw/`,
`facts/`, and `wiki/` show up as folders. The graph view links pages via their
wiki-links and footnote targets.

## Recommended community plugins

- **Dataview** — query the wiki's frontmatter (`derived-from`, `confidence`,
  `last-compiled`) — e.g. *list every page derived from `raw/karpathy-llm-wiki`*.
  This complements `scrip query` (which queries the `facts/` data layer);
  Dataview queries the *notes*, `scrip` queries the *facts*.
- **Obsidian Git** — the vault is git-native; commit/sync from inside the app.

## Health dashboard

`scrip status`/`verify` live in the terminal; this brings them *into* Obsidian.
Run:

```sh
uv run --project scrip python adapters/obsidian/dashboard.py
```

It writes `vault/wiki/_status.md` — a note listing fresh pages (as clickable
`[[links]]`), anything stale (with the source that changed), and any broken
citations. Because `_status.md` has no frontmatter, it is a pure *view*: it never
becomes a tracked artifact and never affects the dependency graph.

Keep it fresh by wiring the one-liner into:

- a **cron job** (e.g. every 15 min while you work), or
- a **Claude Code hook** / skill that runs it after each compile, or
- a manual run before you sit down to read.

## Relationship graph

The typed edges in `facts/graph.ndjson` (`builds-on`, `cites`, `about`,
`made-by` …) are the vault's most connected structure, but they live in NDJSON
and Obsidian's graph view never sees them — it only follows `[[wiki-links]]` and
footnote targets. Run:

```sh
uv run --project scrip python adapters/obsidian/graph_view.py
```

It writes `vault/wiki/_graph.md` — a clickable map of every edge, grouped by
node, with outbound (`→`) and inbound (`←`) typed links. Like the dashboard it
has no frontmatter, so it is a pure *view*: never a tracked artifact, never
affects the dependency graph.

One honest caveat: because every link lives in this single note, Obsidian's
*graph view* renders `_graph` as one hub, not true page-to-page edges — making
the pages link to each other directly would mean editing them, which would make
their `input-hash` lie. For an interactive relationship graph, query the edges
with `scrip query edges` (backlinks are just `scrip query edges --where "dst =
'<id>'"`) or render them with Dataview. `_graph.md` is the zero-plugin,
always-valid map.

## The adapter rule

This adapter only makes the vault nicer to browse. It is not the source of truth,
and deleting `vault/wiki/_status.md` (or this whole directory) leaves a fully
valid vault behind — `scrip status` and `scrip verify` still pass from the files
alone.

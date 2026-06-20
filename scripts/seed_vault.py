#!/usr/bin/env python
"""Seed the example scriptorium vault — reading notes on the designs that
motivated this project, plus two background notes.

Run with the `scrip` project's env so `import scrip` resolves:

    uv run --project scrip python scripts/seed_vault.py

It writes vault/raw, vault/wiki, and vault/facts. Provenance anchors are computed
from the stored note text via `scrip`'s own `anchors.make_anchor`, so every
citation is guaranteed to resolve under `scrip verify`. It does NOT stamp
input-hashes — run `scrip stamp` afterwards to exercise the real compile loop.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from scrip import anchors, frontmatter

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "vault" / "raw"
WIKI = ROOT / "vault" / "wiki"
FACTS = ROOT / "vault" / "facts"


# --------------------------------------------------------------------------- #
# 1. Raw reading notes  (slug -> (meta sidecar, note text))
# --------------------------------------------------------------------------- #
SOURCES: dict[str, tuple[dict, str]] = {
    "karpathy-llm-wiki": (
        {
            "title": "The LLM Wiki (knowledge base) setup",
            "author": "Andrej Karpathy",
            "url": "https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f",
            "retrieved": "2026-06-07",
        },
        "# Reading note — Karpathy's LLM wiki\n\n"
        "Karpathy points an agent at a local folder of markdown and has it build "
        "and maintain a wiki, browsed through Obsidian. The core stance is that "
        "Knowledge should be compiled into a maintained wiki, not retrieved from "
        "scratch on every query.\n\n"
        "The division of labour: the agent maintains the wiki, while the human "
        "curates and asks questions. Raw sources stay immutable; the wiki layer "
        "is regenerable. Good answers should be filed back as wiki pages so the "
        "knowledge compounds.\n\n"
        "What is left undefined: how freshness is tracked, how a claim is tied "
        "back to its source, and what 'lint' actually checks.\n\n"
        "A later clarification: the wiki is a cache over the raw sources, never a "
        "replacement for them.\n",
    ),
    "motherduck-duckdb-obsidian": (
        {
            "title": "Your Obsidian Vault Can Now Run SQL (and Your Agent Can Read It)",
            "author": "MotherDuck",
            "url": "https://motherduck.com/blog/obsidian-vault-duckdb-ai-agents/",
            "retrieved": "2026-06-07",
        },
        "# Reading note — MotherDuck DuckDB + Obsidian plugin\n\n"
        "Your notes are markdown files sitting on disk, and Obsidian is just a "
        "viewer on top of them. The plugin lets you write a DuckDB query in a "
        "note and freeze the result: the result drops in as a markdown table, "
        "bracketed by sentinel comments so the next refresh knows what to "
        "replace. The sentinel carries a query hash, connection, timestamp, and "
        "row count.\n\n"
        "DuckDB runs locally via WASM, with no server, and can query Parquet, "
        "CSV, and JSON.\n\n"
        "The strategy is cached by default, live when it matters. When you ask a "
        "question, the agent reads the note. No query, no MCP round-trip, no "
        "tokens spent re-fetching data that was already computed. The limitation: "
        "this caches tabular external data, not synthesized prose, and freshness "
        "means re-running the SQL.\n",
    ),
    "ganglani-local-rag": (
        {
            "title": "Building a local LLM knowledge base (Karpathy-style)",
            "author": "Kunal Ganglani",
            "url": "https://www.kunalganglani.com/blog/llm-wiki-karpathy-local-knowledge-base",
            "retrieved": "2026-06-07",
        },
        "# Reading note — Ganglani's local RAG attempt\n\n"
        "A hands-on local knowledge base built on llm.c: chunk, embed, retrieve "
        "top-k, generate, fully private. In practice it hits walls. Naive "
        "fixed-size chunking throws away document structure. Adding a new note "
        "currently means re-indexing everything. Answer quality lags GPT-4 class "
        "models, and CPU inference is slow.\n\n"
        "The honest takeaway: the architecture is sound but the ergonomics are "
        "early, and nothing is ever synthesized — you still get fragments back.\n",
    ),
    "commonplace-books": (
        {
            "title": "The commonplace book tradition",
            "author": "(background reading)",
            "url": "https://en.wikipedia.org/wiki/Commonplace_book",
            "retrieved": "2026-06-07",
        },
        "# Reading note — commonplace books\n\n"
        "A commonplace book is a personal compilation of quotations and notes, "
        "curated over a lifetime. Scholars from antiquity through the "
        "Enlightenment kept them to gather, index, and cross-reference what they "
        "read. The value is in the curation and cross-referencing, not the raw "
        "collection.\n\n"
        "It is the centuries-old ancestor of the agent-maintained knowledge "
        "base: a compiled, indexed, personal artifact rather than a pile of "
        "sources.\n",
    ),
    "rag-chunking-limits": (
        {
            "title": "On the limits of fixed-size chunking in RAG",
            "author": "(background reading)",
            "url": "https://example.org/notes/rag-chunking",
            "retrieved": "2026-06-07",
        },
        "# Reading note — RAG chunking limits\n\n"
        "Fixed-size chunking severs sentences from their context and discards "
        "structure. The retriever then matches fragments by surface similarity, "
        "with no notion of which document or section they came from.\n\n"
        "More fundamentally: retrieval surfaces fragments; it does not synthesize "
        "understanding. That is the gap a compiled wiki layer is meant to fill.\n",
    ),
    "contrarian-rag": (
        {
            "title": "A contrarian take on chunking",
            "author": "(background reading)",
            "url": "https://example.org/notes/contrarian",
            "retrieved": "2026-06-07",
        },
        "# Reading note — a contrarian take on chunking\n\n"
        "Fixed-size chunking does not meaningfully harm retrieval quality in "
        "practice. In practice, the impact depends on chunk size and a good "
        "reranker.\n",
    ),
}


# --------------------------------------------------------------------------- #
# 2. Claims  (each anchored to a verbatim quote in its source note)
# --------------------------------------------------------------------------- #
CLAIMS = [
    ("karpathy-llm-wiki",
     "Knowledge should be compiled into a maintained wiki, not retrieved from scratch on every query.",
     "knowledge base", "prefers", "compilation over retrieval", "asserts", ["compile"]),
    ("karpathy-llm-wiki",
     "Good answers should be filed back as wiki pages so the knowledge compounds.",
     "good answers", "become", "wiki pages", "asserts", ["compile", "promotion"]),
    ("motherduck-duckdb-obsidian",
     "cached by default, live when it matters",
     "answer policy", "is", "cached by default", "asserts", ["caching"]),
    ("motherduck-duckdb-obsidian",
     "the agent reads the note. No query, no MCP round-trip, no tokens spent re-fetching data that was already computed.",
     "agent", "reads", "precomputed note", "asserts", ["caching", "cost"]),
    ("motherduck-duckdb-obsidian",
     "the result drops in as a markdown table, bracketed by sentinel comments so the next refresh knows what to replace",
     "frozen result", "wrapped in", "sentinel comment", "asserts", ["provenance", "staleness"]),
    ("ganglani-local-rag",
     "Adding a new note currently means re-indexing everything.",
     "naive RAG", "requires", "full re-index per note", "asserts", ["retrieval", "incremental"]),
    ("ganglani-local-rag",
     "Naive fixed-size chunking throws away document structure.",
     "fixed-size chunking", "discards", "document structure", "asserts", ["retrieval", "chunking"]),
    ("commonplace-books",
     "The value is in the curation and cross-referencing, not the raw collection.",
     "commonplace book", "values", "curation over collection", "asserts", ["history"]),
    # A deliberate contradiction with clm_0007 (same subject+predicate, opposing
    # polarity, different source) so `scrip query contradictions` has a live pair,
    # plus a qualifying claim recording the reconciliation.
    ("contrarian-rag",
     "Fixed-size chunking does not meaningfully harm retrieval quality in practice.",
     "fixed-size chunking", "discards", "document structure", "denies", ["retrieval", "chunking"]),
    ("contrarian-rag",
     "In practice, the impact depends on chunk size and a good reranker.",
     "fixed-size chunking", "discards", "document structure", "qualifies", ["retrieval", "chunking"]),
]


# --------------------------------------------------------------------------- #
# 3. Wiki pages  (frontmatter + body + footnote anchors)
# --------------------------------------------------------------------------- #
WIKI_PAGES = [
    {
        "path": WIKI / "concepts" / "compilation-over-retrieval.md",
        "fm": {
            "id": "concept/compilation-over-retrieval",
            "type": "wiki.concept",
            "title": "Compilation over retrieval",
            "derived-from": [
                "raw/karpathy-llm-wiki",
                "raw/motherduck-duckdb-obsidian",
                "raw/ganglani-local-rag",
            ],
            "confidence": 0.82,
        },
        "body": (
            "Compilation over retrieval is the principle that a knowledge base "
            "should *accumulate* synthesized understanding rather than re-derive "
            "answers from raw sources on every query.[^a1] It is the opposite of "
            "naive RAG, whose incremental cost is punishing: adding a single note "
            "forces a full re-index.[^a2]\n\n"
            "The pay-off is that good answers compound into the corpus instead of "
            "evaporating after each session."
        ),
        "notes": [
            ("a1", "karpathy-llm-wiki",
             "Knowledge should be compiled into a maintained wiki, not retrieved from scratch on every query."),
            ("a2", "ganglani-local-rag",
             "Adding a new note currently means re-indexing everything."),
        ],
    },
    {
        "path": WIKI / "concepts" / "provenance-and-staleness.md",
        "fm": {
            "id": "concept/provenance-and-staleness",
            "type": "wiki.concept",
            "title": "Provenance and staleness",
            "derived-from": [
                "raw/motherduck-duckdb-obsidian",
                "raw/karpathy-llm-wiki",
            ],
            "confidence": 0.8,
        },
        "body": (
            "MotherDuck's sentinel is the seed of a general idea: a frozen result "
            "is wrapped in a marker that records what produced it, so a refresh "
            "knows what to replace.[^a1] Generalize that marker from a single SQL "
            "block to *any* derived artifact and you get a content-hash "
            "dependency graph — the concrete definition of the 'freshness' and "
            "'lint' that compile-only designs leave undefined."
        ),
        "notes": [
            ("a1", "motherduck-duckdb-obsidian",
             "the result drops in as a markdown table, bracketed by sentinel comments so the next refresh knows what to replace"),
        ],
    },
    {
        "path": WIKI / "concepts" / "the-answer-ladder.md",
        "fm": {
            "id": "concept/the-answer-ladder",
            "type": "wiki.concept",
            "title": "The answer ladder",
            "derived-from": [
                "raw/karpathy-llm-wiki",
                "raw/motherduck-duckdb-obsidian",
                "raw/ganglani-local-rag",
            ],
            "confidence": 0.85,
        },
        "body": (
            "Compile, cache, and retrieve are not rival architectures but rungs of "
            "one policy. The default is cached: when the compiled layer covers a "
            "question, the agent reads the precomputed note with no re-fetch "
            "cost.[^a1] The system stays cached by default, live when it "
            "matters[^a2] — recompiling only the slice that has gone stale, and "
            "retrieving from raw sources only on a genuine miss."
        ),
        "notes": [
            ("a1", "motherduck-duckdb-obsidian",
             "the agent reads the note. No query, no MCP round-trip, no tokens spent re-fetching data that was already computed."),
            ("a2", "motherduck-duckdb-obsidian",
             "cached by default, live when it matters"),
        ],
    },
    {
        "path": WIKI / "entities" / "duckdb.md",
        "fm": {
            "id": "entity/duckdb",
            "type": "wiki.entity",
            "title": "DuckDB",
            "derived-from": ["raw/motherduck-duckdb-obsidian"],
            "confidence": 0.9,
        },
        "body": (
            "DuckDB is an in-process analytical database. In the MotherDuck "
            "Obsidian plugin it runs locally via WASM, with no server, and can "
            "query Parquet, CSV, and JSON.[^a1] scriptorium uses it as the query "
            "lens over the `facts/` NDJSON layer."
        ),
        "notes": [
            ("a1", "motherduck-duckdb-obsidian",
             "DuckDB runs locally via WASM, with no server, and can query Parquet, CSV, and JSON."),
        ],
    },
    {
        "path": WIKI / "concepts" / "why-immutability.md",
        "fm": {
            "id": "concept/why-immutability",
            "type": "wiki.concept",
            "title": "Why raw sources are immutable",
            "derived-from": ["raw/karpathy-llm-wiki"],
            "confidence": 0.8,
        },
        "body": (
            "Immutability of `raw/` is load-bearing: because anchors hash the "
            "stored source text, citations only break on a deliberate re-ingest, "
            "never on a reformat.[^a1]"
        ),
        "notes": [
            ("a1", "karpathy-llm-wiki",
             "Raw sources stay immutable; the wiki layer is regenerable."),
        ],
    },
]


# --------------------------------------------------------------------------- #
# 4. Entities & graph edges
# --------------------------------------------------------------------------- #
ENTITIES = [
    {"entity_id": "entity/karpathy", "name": "Andrej Karpathy", "kind": "person", "tags": ["author"]},
    {"entity_id": "entity/motherduck", "name": "MotherDuck", "kind": "org", "tags": ["vendor"]},
    {"entity_id": "entity/duckdb", "name": "DuckDB", "kind": "system", "tags": ["database"]},
    {"entity_id": "entity/obsidian", "name": "Obsidian", "kind": "system", "tags": ["editor"]},
    {"entity_id": "entity/llm-c", "name": "llm.c", "kind": "system", "tags": ["inference"]},
    {"entity_id": "entity/rag", "name": "Retrieval-Augmented Generation", "kind": "concept", "tags": ["retrieval"]},
    {"entity_id": "entity/commonplace-book", "name": "Commonplace book", "kind": "concept", "tags": ["history"]},
]

EDGES = [
    {"src": "raw/motherduck-duckdb-obsidian", "dst": "raw/karpathy-llm-wiki", "kind": "cites"},
    {"src": "entity/duckdb", "dst": "entity/motherduck", "kind": "made-by"},
    {"src": "entity/llm-c", "dst": "entity/karpathy", "kind": "made-by"},
    {"src": "raw/ganglani-local-rag", "dst": "entity/rag", "kind": "about"},
    {"src": "concept/the-answer-ladder", "dst": "concept/compilation-over-retrieval", "kind": "builds-on"},
]

RECONCILIATIONS = [
    {
        "reconciliation_id": "rec_0001",
        "decision": "qualify",
        "claim_a": "clm_0007",
        "claim_b": "clm_0009",
        "rationale": (
            "Preserve both claims with the qualifying caveat in clm_0010: naive "
            "fixed-size chunking can discard document structure, while the "
            "practical retrieval impact depends on chunk size and reranking."
        ),
        "at": "2026-06-07T10:00:00Z",
    }
]


def write_ndjson(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def main() -> None:
    # 0. rebuild from this single source of truth: clear previously generated
    #    content so records removed from this script never linger in the vault.
    for d in (RAW, FACTS, WIKI / "concepts", WIKI / "entities"):
        d.mkdir(parents=True, exist_ok=True)
    for p in list(RAW.glob("*.md")) + list(RAW.glob("*.meta.yaml")):
        p.unlink()
    for p in FACTS.glob("*.ndjson"):
        p.unlink()
    (FACTS / "_meta.yaml").unlink(missing_ok=True)
    for sub in ("concepts", "entities"):
        for p in (WIKI / sub).glob("*.md"):
            p.unlink()

    # 1. raw notes + sidecars
    for slug, (meta, text) in SOURCES.items():
        (RAW / f"{slug}.md").write_text(text, encoding="utf-8")
        (RAW / f"{slug}.meta.yaml").write_text(
            yaml.safe_dump(meta, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    # 2. claims
    claim_rows = []
    for i, (slug, quote, subj, pred, obj, pol, tags) in enumerate(CLAIMS, start=1):
        src_text = SOURCES[slug][1]
        claim_rows.append({
            "claim_id": f"clm_{i:04d}",
            "subject": subj,
            "predicate": pred,
            "object": obj,
            "claim_text": quote,
            "source_id": f"raw/{slug}",
            "anchor": anchors.make_anchor(src_text, quote),
            "confidence": 0.85,
            "polarity": pol,
            "extracted_at": "2026-06-07T10:00:00Z",
            "tags": tags,
        })
    write_ndjson(FACTS / "claims.ndjson", claim_rows)
    write_ndjson(FACTS / "entities.ndjson", ENTITIES)
    write_ndjson(FACTS / "graph.ndjson", EDGES)
    write_ndjson(FACTS / "reconciliations.ndjson", RECONCILIATIONS)

    # facts-set frontmatter (unstamped; scrip stamp fills input-hash)
    (FACTS / "_meta.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "facts/core",
                "type": "facts.set",
                "derived-from": [f"raw/{slug}" for slug in SOURCES],
                "members": [
                    "facts/entities.ndjson",
                    "facts/claims.ndjson",
                    "facts/graph.ndjson",
                    "facts/reconciliations.ndjson",
                ],
                "confidence": 0.85,
            },
            sort_keys=False, allow_unicode=True,
        ),
        encoding="utf-8",
    )

    # 3. wiki pages
    for page in WIKI_PAGES:
        body = page["body"] + "\n\n"
        for label, slug, quote in page["notes"]:
            anchor = anchors.make_anchor(SOURCES[slug][1], quote)
            body += f'[^{label}]: anchor=raw/{slug}#{anchor}  "{quote[:48]}"\n'
        page["path"].write_text(frontmatter.dump(page["fm"], body), encoding="utf-8")

    # index + log (untracked)
    concept_links = "".join(
        f"- [[{p['fm']['id'].split('/')[-1]}]]\n"
        for p in WIKI_PAGES
        if p["fm"]["type"] == "wiki.concept"
    )
    entity_links = "".join(
        f"- [[{p['fm']['id'].split('/')[-1]}]]\n"
        for p in WIKI_PAGES
        if p["fm"]["type"] == "wiki.entity"
    )
    (WIKI / "index.md").write_text(
        f"# Index\n\n## Concepts\n{concept_links}\n## Entities\n{entity_links}",
        encoding="utf-8",
    )
    (WIKI / "log.md").write_text(
        f"# Log\n\n- 2026-06-07 — seeded vault from {len(SOURCES)} reading notes; "
        f"compiled {len(WIKI_PAGES)} wiki pages and {len(claim_rows)} claims; "
        "reconciled the fixed-size chunking contradiction as `qualify` in "
        "`facts/reconciliations.ndjson`, with `clm_0010` carrying the caveat.\n",
        encoding="utf-8",
    )
    print(f"seeded {len(SOURCES)} sources, {len(WIKI_PAGES)} wiki pages, "
          f"{len(claim_rows)} claims, {len(ENTITIES)} entities, {len(EDGES)} edges")


if __name__ == "__main__":
    main()

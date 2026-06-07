# Reading note — MotherDuck DuckDB + Obsidian plugin

Your notes are markdown files sitting on disk, and Obsidian is just a viewer on top of them. The plugin lets you write a DuckDB query in a note and freeze the result: the result drops in as a markdown table, bracketed by sentinel comments so the next refresh knows what to replace. The sentinel carries a query hash, connection, timestamp, and row count.

DuckDB runs locally via WASM, with no server, and can query Parquet, CSV, and JSON.

The strategy is cached by default, live when it matters. When you ask a question, the agent reads the note. No query, no MCP round-trip, no tokens spent re-fetching data that was already computed. The limitation: this caches tabular external data, not synthesized prose, and freshness means re-running the SQL.

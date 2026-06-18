import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildGraphIndex,
  outgoingEdges,
  incomingEdges,
  nodeIdToPath,
  pathToNodeId,
} from "./graphIndex.ts";

const SAMPLE = [
  '{"src":"concept/the-answer-ladder","dst":"concept/compilation-over-retrieval","kind":"builds-on"}',
  '{"src":"raw/motherduck-duckdb-obsidian","dst":"raw/karpathy-llm-wiki","kind":"cites"}',
  "",
  "not json at all",
  '{"src":"entity/duckdb","kind":"made-by"}',
].join("\n");

test("buildGraphIndex parses valid edges and skips blank/malformed/incomplete", () => {
  const idx = buildGraphIndex(SAMPLE);
  assert.equal(idx.edges.length, 2);
  assert.ok(idx.nodes.has("concept/the-answer-ladder"));
  assert.ok(idx.nodes.has("raw/karpathy-llm-wiki"));
});

test("outgoing/incoming adjacency", () => {
  const idx = buildGraphIndex(SAMPLE);
  assert.equal(outgoingEdges(idx, "concept/the-answer-ladder").length, 1);
  const inc = incomingEdges(idx, "concept/compilation-over-retrieval");
  assert.equal(inc.length, 1);
  assert.equal(inc[0].kind, "builds-on");
  assert.equal(outgoingEdges(idx, "no-such-node").length, 0);
});

test("node<->path mapping, vault-dir layout (prefix '')", () => {
  assert.equal(nodeIdToPath("concept/foo", ""), "wiki/concepts/foo.md");
  assert.equal(nodeIdToPath("raw/bar", ""), "raw/bar.md");
  assert.equal(nodeIdToPath("entity/baz", ""), "wiki/entities/baz.md");
  assert.equal(pathToNodeId("wiki/concepts/foo.md", ""), "concept/foo");
  assert.equal(pathToNodeId("raw/bar.md", ""), "raw/bar");
});

test("node<->path mapping, root layout (prefix 'vault')", () => {
  assert.equal(nodeIdToPath("concept/foo", "vault"), "vault/wiki/concepts/foo.md");
  assert.equal(pathToNodeId("vault/raw/bar.md", "vault"), "raw/bar");
  assert.equal(pathToNodeId("raw/bar.md", "vault"), null); // missing required prefix
});

test("facts/* and unknown kinds map to null", () => {
  assert.equal(nodeIdToPath("facts/core", ""), null);
  assert.equal(pathToNodeId("vault/facts/_meta.yaml", "vault"), null);
});

test("round-trips for the three page kinds", () => {
  for (const id of ["concept/a", "raw/b", "entity/c"]) {
    const p = nodeIdToPath(id, "");
    assert.ok(p);
    assert.equal(pathToNodeId(p, ""), id);
  }
});

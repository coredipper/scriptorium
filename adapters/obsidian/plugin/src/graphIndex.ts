import type { Edge } from "./types.ts";

// In-memory view of facts/graph.ndjson: the edge list plus src/dst adjacency.
// Pure: built from the file's text, so it is unit-testable without Obsidian.
export interface GraphIndex {
  edges: Edge[];
  outgoing: Map<string, Edge[]>;
  incoming: Map<string, Edge[]>;
  nodes: Set<string>;
}

function push(m: Map<string, Edge[]>, key: string, e: Edge): void {
  const arr = m.get(key);
  if (arr) arr.push(e);
  else m.set(key, [e]);
}

export function buildGraphIndex(ndjson: string): GraphIndex {
  const edges: Edge[] = [];
  const outgoing = new Map<string, Edge[]>();
  const incoming = new Map<string, Edge[]>();
  const nodes = new Set<string>();

  for (const raw of ndjson.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    let obj: unknown;
    try {
      obj = JSON.parse(line);
    } catch {
      console.warn("scriptorium: skipping malformed graph.ndjson line");
      continue;
    }
    const e = obj as Partial<Edge>;
    if (
      typeof e.src !== "string" ||
      typeof e.dst !== "string" ||
      typeof e.kind !== "string"
    ) {
      console.warn("scriptorium: graph.ndjson line missing src/dst/kind");
      continue;
    }
    const edge: Edge = { src: e.src, dst: e.dst, kind: e.kind };
    edges.push(edge);
    nodes.add(edge.src);
    nodes.add(edge.dst);
    push(outgoing, edge.src, edge);
    push(incoming, edge.dst, edge);
  }

  return { edges, outgoing, incoming, nodes };
}

export function outgoingEdges(index: GraphIndex, nodeId: string): Edge[] {
  return index.outgoing.get(nodeId) ?? [];
}

export function incomingEdges(index: GraphIndex, nodeId: string): Edge[] {
  return index.incoming.get(nodeId) ?? [];
}

// node id <-> path within the Obsidian vault.
// `vaultPrefix` is "" when Obsidian opened the scriptorium vault/ dir directly,
// or "vault" when it opened the scriptorium root (which contains vault/).
function withPrefix(vaultPrefix: string): string {
  return vaultPrefix ? vaultPrefix.replace(/\/+$/, "") + "/" : "";
}

export function nodeIdToPath(nodeId: string, vaultPrefix: string): string | null {
  const pre = withPrefix(vaultPrefix);
  const slash = nodeId.indexOf("/");
  if (slash < 0) return null;
  const kind = nodeId.slice(0, slash);
  const slug = nodeId.slice(slash + 1);
  if (kind === "raw") return `${pre}raw/${slug}.md`;
  if (kind === "concept") return `${pre}wiki/concepts/${slug}.md`;
  if (kind === "entity") return `${pre}wiki/entities/${slug}.md`;
  return null; // facts/* sets have no single page
}

export function pathToNodeId(path: string, vaultPrefix: string): string | null {
  const pre = withPrefix(vaultPrefix);
  let p = path;
  if (pre) {
    if (!p.startsWith(pre)) return null;
    p = p.slice(pre.length);
  }
  const raw = p.match(/^raw\/(.+)\.md$/);
  if (raw) return `raw/${raw[1]}`;
  const concept = p.match(/^wiki\/concepts\/(.+)\.md$/);
  if (concept) return `concept/${concept[1]}`;
  const entity = p.match(/^wiki\/entities\/(.+)\.md$/);
  if (entity) return `entity/${entity[1]}`;
  return null;
}

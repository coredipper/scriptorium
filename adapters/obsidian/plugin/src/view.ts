import { ItemView, WorkspaceLeaf, TFile } from "obsidian";
import type ScriptoriumPlugin from "./main.ts";
import {
  outgoingEdges,
  incomingEdges,
  nodeIdToPath,
  pathToNodeId,
} from "./graphIndex.ts";

export const VIEW_TYPE = "scriptorium-relationships";

// Sidebar panel: vault health (desktop) + the active note's typed relationships
// from facts/graph.ndjson (pure-TS, works everywhere).
export class RelationshipView extends ItemView {
  plugin: ScriptoriumPlugin;

  constructor(leaf: WorkspaceLeaf, plugin: ScriptoriumPlugin) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType(): string {
    return VIEW_TYPE;
  }
  getDisplayText(): string {
    return "Scriptorium";
  }
  getIcon(): string {
    return "git-fork";
  }

  async onOpen(): Promise<void> {
    // active-leaf-change covers switching tabs/panes; file-open covers opening a
    // different note in the same leaf — both must refresh the panel.
    this.registerEvent(
      this.app.workspace.on("active-leaf-change", () => this.render()),
    );
    this.registerEvent(this.app.workspace.on("file-open", () => this.render()));
    this.render();
  }

  async onClose(): Promise<void> {}

  render(): void {
    const root = this.containerEl.children[1] as HTMLElement;
    root.empty();
    root.addClass("scriptorium-view");
    this.renderHealth(root);
    this.renderRelationships(root);
  }

  private openNode(nodeId: string): void {
    const prefix = this.plugin.resolved?.vaultPrefix ?? "";
    const path = nodeIdToPath(nodeId, prefix);
    if (!path) return;
    const file = this.app.vault.getAbstractFileByPath(path);
    if (file instanceof TFile) {
      void this.app.workspace.getLeaf(false).openFile(file);
    }
  }

  private renderHealth(root: HTMLElement): void {
    const h = this.plugin.health.getState();
    // On mobile / when nothing has run, show nothing (no shell-out layer).
    if (!h.available && !h.error && !h.summary) return;

    root.createEl("div", { text: "Health", cls: "scriptorium-section-title" });
    if (h.error) {
      root.createEl("div", { text: h.error, cls: "scriptorium-empty" });
    }
    const sum = h.summary;
    if (sum) {
      const line = root.createEl("div", { cls: "scriptorium-health" });
      if (sum.clean) {
        line.addClass("is-clean");
        line.setText(`✓ fresh — ${sum.ok} artifact(s), citations resolve`);
      } else {
        line.addClass("has-findings");
        const amb = sum.ambiguous ? ` · ${sum.ambiguous} ambiguous` : "";
        line.setText(`⚠ ${sum.stale} stale · ${sum.broken} broken${amb}`);
      }
    }
    for (const s of h.status?.stale ?? []) {
      const el = root.createEl("div", { cls: "scriptorium-finding" });
      el.createSpan({ text: `stale: ${s.id}` });
      if (s.changed_sources?.length) {
        el.createEl("div", {
          text: `changed: ${s.changed_sources.join(", ")}`,
          cls: "scriptorium-reason",
        });
      }
      el.addEventListener("click", () => this.openNode(s.id));
    }
    for (const b of h.verify?.broken ?? []) {
      const el = root.createEl("div", {
        cls: "scriptorium-finding",
        text: `broken: ${b.where} → ${b.source_id}`,
      });
      el.addEventListener("click", () => this.openNode(b.source_id));
    }
  }

  private renderRelationships(root: HTMLElement): void {
    root.createEl("div", {
      text: "Relationships",
      cls: "scriptorium-section-title",
    });
    const idx = this.plugin.graphIndex;
    const prefix = this.plugin.resolved?.vaultPrefix ?? "";
    const active = this.app.workspace.getActiveFile();

    if (!idx) {
      root.createEl("div", {
        text: "No facts/graph.ndjson found.",
        cls: "scriptorium-empty",
      });
      return;
    }
    if (!active) {
      root.createEl("div", {
        text: "Open a note to see its relationships.",
        cls: "scriptorium-empty",
      });
      return;
    }
    const nodeId = pathToNodeId(active.path, prefix);
    if (!nodeId) {
      root.createEl("div", {
        text: "This note is not a graph node.",
        cls: "scriptorium-empty",
      });
      return;
    }
    const out = outgoingEdges(idx, nodeId);
    const inc = incomingEdges(idx, nodeId);
    if (!out.length && !inc.length) {
      root.createEl("div", {
        text: "No relationships for this note.",
        cls: "scriptorium-empty",
      });
      return;
    }
    for (const e of out) this.renderEdge(root, e.kind, "→", e.dst);
    for (const e of inc) this.renderEdge(root, e.kind, "←", e.src);
  }

  private renderEdge(
    root: HTMLElement,
    kind: string,
    arrow: string,
    otherId: string,
  ): void {
    const el = root.createEl("div", { cls: "scriptorium-edge" });
    el.createSpan({ text: `${kind} ${arrow}`, cls: "scriptorium-edge-kind" });
    el.createSpan({ text: otherId });
    el.addEventListener("click", () => this.openNode(otherId));
  }
}

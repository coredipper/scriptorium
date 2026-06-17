import {
  Plugin,
  Platform,
  FileSystemAdapter,
  Notice,
  debounce,
  TFile,
} from "obsidian";
import { RelationshipView, VIEW_TYPE } from "./view.ts";
import { HealthController } from "./health.ts";
import {
  ScriptoriumSettingTab,
  DEFAULT_SETTINGS,
  type ScriptoriumSettings,
} from "./settings.ts";
import { buildGraphIndex, type GraphIndex } from "./graphIndex.ts";
import { resolveRoot, type Resolved } from "./root.ts";

export default class ScriptoriumPlugin extends Plugin {
  settings: ScriptoriumSettings = DEFAULT_SETTINGS;
  graphIndex: GraphIndex | null = null;
  resolved: Resolved | null = null;
  health!: HealthController;
  private statusBar: HTMLElement | null = null;

  async onload(): Promise<void> {
    await this.loadSettings();

    this.health = new HealthController(() => ({
      scripPath: this.settings.scripPath,
      root: this.resolved?.root || null,
    }));
    this.health.onChange(() => {
      this.updateStatusBar();
      this.refreshView();
    });

    this.registerView(VIEW_TYPE, (leaf) => new RelationshipView(leaf, this));
    this.addRibbonIcon("git-fork", "Scriptorium relationships", () =>
      this.activateView(),
    );

    if (Platform.isDesktopApp) {
      this.statusBar = this.addStatusBarItem();
    }

    this.addCommand({
      id: "open-panel",
      name: "Open relationships panel",
      callback: () => this.activateView(),
    });
    this.addCommand({
      id: "check-health",
      name: "Check vault health (status + verify)",
      callback: async () => {
        await this.health.refresh();
        const s = this.health.getState();
        if (s.error) new Notice(`Scriptorium: ${s.error}`);
        else if (s.summary?.clean) new Notice("Scriptorium: all fresh ✓");
        else
          new Notice(
            `Scriptorium: ${s.summary?.stale ?? 0} stale · ${s.summary?.broken ?? 0} broken`,
          );
      },
    });

    this.addSettingTab(new ScriptoriumSettingTab(this.app, this));

    // Resolve root, load the graph, run an initial health check.
    await this.reload();

    const debounced = debounce(
      (file: TFile) => void this.onVaultChange(file),
      800,
      true,
    );
    this.registerEvent(
      this.app.vault.on("modify", (f) => {
        if (f instanceof TFile) debounced(f);
      }),
    );
  }

  async loadSettings(): Promise<void> {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
    await this.reload();
  }

  // Re-resolve root, reload the graph index, refresh health + the view.
  async reload(): Promise<void> {
    await this.resolveRootAndPrefix();
    await this.loadGraph();
    if (Platform.isDesktopApp) await this.health.refresh();
    this.refreshView();
    this.updateStatusBar();
  }

  private async resolveRootAndPrefix(): Promise<void> {
    const adapter = this.app.vault.adapter;
    const override = this.settings.rootOverride || null;
    if (Platform.isDesktopApp && adapter instanceof FileSystemAdapter) {
      const fs = await import("node:fs");
      const base = adapter.getBasePath();
      this.resolved = resolveRoot(base, (p) => fs.existsSync(p), override);
    } else {
      // mobile / no filesystem: derive only the vault prefix via relative checks.
      const hasFacts = await adapter.exists("facts");
      const hasVault = await adapter.exists("vault");
      const prefix = hasFacts ? "" : hasVault ? "vault" : null;
      this.resolved = prefix === null ? null : { root: "", vaultPrefix: prefix };
    }
  }

  private graphPath(): string {
    const prefix = this.resolved?.vaultPrefix ?? "";
    return (prefix ? prefix + "/" : "") + "facts/graph.ndjson";
  }

  private async loadGraph(): Promise<void> {
    const path = this.graphPath();
    try {
      if (await this.app.vault.adapter.exists(path)) {
        const text = await this.app.vault.adapter.read(path);
        this.graphIndex = buildGraphIndex(text);
      } else {
        this.graphIndex = buildGraphIndex("");
      }
    } catch {
      this.graphIndex = buildGraphIndex("");
    }
  }

  private async onVaultChange(file: TFile): Promise<void> {
    if (file.path === this.graphPath()) {
      await this.loadGraph();
      this.refreshView();
      return;
    }
    if (Platform.isDesktopApp && this.settings.autoCheckOnSave) {
      await this.health.refresh();
    }
  }

  private updateStatusBar(): void {
    if (!this.statusBar) return;
    const s = this.health.getState();
    if (!s.available && s.error) {
      this.statusBar.setText("Scriptorium ⚠");
      this.statusBar.title = s.error;
      return;
    }
    const sum = s.summary;
    if (!sum) {
      this.statusBar.setText("");
      return;
    }
    if (sum.clean) {
      this.statusBar.setText("Scriptorium ✓");
      this.statusBar.title = `${sum.ok} artifact(s) fresh, citations resolve`;
    } else {
      this.statusBar.setText(
        `Scriptorium ⚠ ${sum.stale} stale · ${sum.broken} broken`,
      );
      this.statusBar.title = "Open the Scriptorium panel for details";
    }
  }

  private refreshView(): void {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE)) {
      const v = leaf.view;
      if (v instanceof RelationshipView) v.render();
    }
  }

  async activateView(): Promise<void> {
    const { workspace } = this.app;
    let leaf = workspace.getLeavesOfType(VIEW_TYPE)[0];
    if (!leaf) {
      const right = workspace.getRightLeaf(false);
      if (!right) return;
      leaf = right;
      await leaf.setViewState({ type: VIEW_TYPE, active: true });
    }
    void workspace.revealLeaf(leaf);
  }
}

import { App, PluginSettingTab, Setting } from "obsidian";
import type ScriptoriumPlugin from "./main.ts";

export interface ScriptoriumSettings {
  scripPath: string;
  rootOverride: string;
  autoCheckOnSave: boolean;
}

export const DEFAULT_SETTINGS: ScriptoriumSettings = {
  scripPath: "scrip",
  rootOverride: "",
  autoCheckOnSave: true,
};

export class ScriptoriumSettingTab extends PluginSettingTab {
  plugin: ScriptoriumPlugin;

  constructor(app: App, plugin: ScriptoriumPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl)
      .setName("scrip path")
      .setDesc("Path to the scrip CLI (desktop only). Default: scrip on PATH.")
      .addText((t) =>
        t
          .setPlaceholder("scrip")
          .setValue(this.plugin.settings.scripPath)
          .onChange(async (v) => {
            this.plugin.settings.scripPath = v.trim() || "scrip";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Root override")
      .setDesc(
        "Scriptorium root (the directory containing vault/). Leave blank to auto-detect.",
      )
      .addText((t) =>
        t
          .setPlaceholder("(auto-detect)")
          .setValue(this.plugin.settings.rootOverride)
          .onChange(async (v) => {
            this.plugin.settings.rootOverride = v.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Auto-check on save")
      .setDesc("Re-run scrip status/verify when a note changes (desktop only).")
      .addToggle((t) =>
        t
          .setValue(this.plugin.settings.autoCheckOnSave)
          .onChange(async (v) => {
            this.plugin.settings.autoCheckOnSave = v;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl).addButton((b) =>
      b
        .setButtonText("Re-detect root + reload graph")
        .onClick(() => this.plugin.reload()),
    );
  }
}

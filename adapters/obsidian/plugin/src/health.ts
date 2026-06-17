import { Platform } from "obsidian";
import { createScripRunner, ScripNotFound } from "./scripRunner.ts";
import {
  summarizeHealth,
  type StatusResult,
  type VerifyResult,
  type HealthSummary,
} from "./types.ts";

export interface HealthState {
  available: boolean; // true once a scrip run succeeded
  summary: HealthSummary | null;
  status: StatusResult | null;
  verify: VerifyResult | null;
  error: string | null;
}

// Runs `scrip status` + `scrip verify` (desktop only) and notifies listeners.
// UI-free: main.ts subscribes and updates the status bar + view.
export class HealthController {
  private state: HealthState = {
    available: false,
    summary: null,
    status: null,
    verify: null,
    error: null,
  };
  private listeners: Array<(s: HealthState) => void> = [];
  private getConfig: () => { scripPath: string; root: string | null };

  constructor(getConfig: () => { scripPath: string; root: string | null }) {
    this.getConfig = getConfig;
  }

  getState(): HealthState {
    return this.state;
  }

  onChange(cb: (s: HealthState) => void): void {
    this.listeners.push(cb);
  }

  private emit(): void {
    for (const cb of this.listeners) cb(this.state);
  }

  async refresh(): Promise<void> {
    const { scripPath, root } = this.getConfig();
    if (!Platform.isDesktopApp || !root) {
      // mobile or unresolved root: shell-out layer simply isn't available.
      this.state = { ...this.state, available: false, error: null };
      this.emit();
      return;
    }
    const runner = createScripRunner(scripPath, root);
    try {
      const status = await runner.run<StatusResult>(["status"]);
      const verify = await runner.run<VerifyResult>(["verify"]);
      this.state = {
        available: true,
        summary: summarizeHealth(status, verify),
        status,
        verify,
        error: null,
      };
    } catch (e) {
      const msg =
        e instanceof ScripNotFound
          ? "scrip not found — set its path in Scriptorium settings"
          : (e as Error).message;
      // keep the last good result for the panel; surface the error.
      this.state = { ...this.state, available: false, error: msg };
    }
    this.emit();
  }
}

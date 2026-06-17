// Shared types + pure mappers. Obsidian-free on purpose, so node --test can run
// the logic without the Obsidian runtime.

export interface Edge {
  src: string;
  dst: string;
  kind: string;
}

// `scrip status --json` -> graph.compute_status()
export interface StaleItem {
  id: string;
  reason?: string;
  changed_sources?: string[];
}

export interface StatusResult {
  stale: StaleItem[];
  ok: { id: string }[];
  uncompiled: { id: string }[];
}

// `scrip verify --json` -> anchors.verify_vault()
export interface AnchorRef {
  where: string;
  source_id: string;
}

export interface VerifyResult {
  checked: number;
  ok: number;
  broken: AnchorRef[];
  ambiguous: AnchorRef[];
}

export interface HealthSummary {
  stale: number;
  broken: number;
  ambiguous: number;
  ok: number;
  clean: boolean;
}

export function summarizeHealth(
  status: StatusResult,
  verify: VerifyResult,
): HealthSummary {
  const stale = status.stale?.length ?? 0;
  const broken = verify.broken?.length ?? 0;
  const ambiguous = verify.ambiguous?.length ?? 0;
  const ok = status.ok?.length ?? 0;
  return {
    stale,
    broken,
    ambiguous,
    ok,
    clean: stale === 0 && broken === 0 && ambiguous === 0,
  };
}

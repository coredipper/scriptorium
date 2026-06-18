import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createScripRunner, ScripNotFound } from "./scripRunner.ts";

function fakeScrip(body: string): string {
  const dir = mkdtempSync(join(tmpdir(), "scrip-fake-"));
  const p = join(dir, "scrip");
  writeFileSync(p, body, { mode: 0o755 });
  return p;
}

test("parses JSON printed on a non-zero exit (status with findings)", async () => {
  // scrip exits 1 when stale but still prints the result JSON on stdout.
  const path = fakeScrip(
    '#!/bin/sh\necho \'{"stale":[{"id":"concept/x"}],"ok":[],"uncompiled":[]}\'\nexit 1\n',
  );
  const runner = createScripRunner(path, "/root");
  const res = await runner.run<{ stale: { id: string }[] }>(["status"]);
  assert.equal(res.stale.length, 1);
});

test("parses JSON on a clean (zero) exit", async () => {
  const path = fakeScrip(
    '#!/bin/sh\necho \'{"checked":3,"ok":3,"broken":[],"ambiguous":[]}\'\nexit 0\n',
  );
  const runner = createScripRunner(path, "/root");
  const res = await runner.run<{ ok: number }>(["verify"]);
  assert.equal(res.ok, 3);
});

test("rejects ScripNotFound for a missing binary", async () => {
  const runner = createScripRunner("/no/such/scrip-binary-xyz", "/root");
  await assert.rejects(() => runner.run(["status"]), ScripNotFound);
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { summarizeHealth } from "./types.ts";

test("summarizeHealth: clean when nothing stale/broken/ambiguous", () => {
  const s = summarizeHealth(
    { stale: [], ok: [{ id: "a" }, { id: "b" }], uncompiled: [] },
    { checked: 5, ok: 5, broken: [], ambiguous: [] },
  );
  assert.equal(s.clean, true);
  assert.equal(s.ok, 2);
  assert.equal(s.stale, 0);
});

test("summarizeHealth: findings flip clean to false and are counted", () => {
  const s = summarizeHealth(
    { stale: [{ id: "concept/x", reason: "changed" }], ok: [], uncompiled: [] },
    {
      checked: 3,
      ok: 2,
      broken: [{ where: "concept/x", source_id: "raw/y" }],
      ambiguous: [],
    },
  );
  assert.equal(s.clean, false);
  assert.equal(s.stale, 1);
  assert.equal(s.broken, 1);
});

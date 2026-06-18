import { test } from "node:test";
import assert from "node:assert/strict";
import { summarizeHealth, formatFindings } from "./types.ts";

test("summarizeHealth: clean when nothing stale/broken/ambiguous", () => {
  const s = summarizeHealth(
    { stale: [], ok: [{ id: "a" }, { id: "b" }], uncompiled: [] },
    { checked: 5, ok: 5, broken: [], ambiguous: [] },
  );
  assert.equal(s.clean, true);
  assert.equal(s.ok, 2);
  assert.equal(s.stale, 0);
});

test("formatFindings: omits ambiguous when zero, includes it otherwise", () => {
  assert.equal(
    formatFindings({ stale: 1, broken: 2, ambiguous: 0, ok: 5, clean: false }),
    "1 stale · 2 broken",
  );
  assert.equal(
    formatFindings({ stale: 0, broken: 0, ambiguous: 3, ok: 5, clean: false }),
    "0 stale · 0 broken · 3 ambiguous",
  );
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

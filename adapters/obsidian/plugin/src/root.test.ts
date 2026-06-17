import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveRoot } from "./root.ts";

const setExists = (paths: string[]) => {
  const s = new Set(paths);
  return (p: string) => s.has(p);
};

test("root layout: Obsidian opened the scriptorium root", () => {
  const r = resolveRoot("/repo", setExists(["/repo/vault", "/repo/SPEC.md"]));
  assert.deepEqual(r, { root: "/repo", vaultPrefix: "vault" });
});

test("vault-dir layout: Obsidian opened vault/ directly", () => {
  const r = resolveRoot(
    "/repo/vault",
    setExists(["/repo/vault/raw", "/repo/vault/wiki", "/repo/vault/facts", "/repo/SPEC.md"]),
  );
  assert.deepEqual(r, { root: "/repo", vaultPrefix: "" });
});

test("override wins for root; prefix still detected from layout", () => {
  const r = resolveRoot(
    "/x/vault",
    setExists(["/x/vault/raw", "/x/vault/wiki", "/x/vault/facts"]),
    "/custom/root",
  );
  assert.deepEqual(r, { root: "/custom/root", vaultPrefix: "" });
});

test("trailing slashes are tolerated", () => {
  const r = resolveRoot("/repo/", setExists(["/repo/vault", "/repo/.kb"]));
  assert.deepEqual(r, { root: "/repo", vaultPrefix: "vault" });
});

test("unrecognized folder -> null", () => {
  assert.equal(resolveRoot("/random", () => false), null);
});

// Resolve the scriptorium root + the vault prefix from the Obsidian vault path.
// Pure: filesystem access is injected as `exists`, so it is unit-testable.
//
// scrip's own resolve_root treats the "root" as the directory containing vault/
// (plus SPEC.md or .kb/). Obsidian may be pointed either at that root or at the
// vault/ dir itself, so we detect both and report where vault/ sits relative to
// the Obsidian vault (the `vaultPrefix`).

export interface Resolved {
  root: string; // value to pass as `scrip --root`
  vaultPrefix: string; // "" if Obsidian opened vault/, "vault" if it opened the root
}

function trimSlash(p: string): string {
  return p.replace(/\/+$/, "");
}
function join(a: string, b: string): string {
  return trimSlash(a) + "/" + b;
}
function parent(p: string): string {
  const q = trimSlash(p);
  const i = q.lastIndexOf("/");
  return i <= 0 ? q : q.slice(0, i);
}

export function resolveRoot(
  basePath: string,
  exists: (p: string) => boolean,
  override?: string | null,
): Resolved | null {
  const looksRootDir = (p: string): boolean =>
    exists(join(p, "vault")) &&
    (exists(join(p, "SPEC.md")) || exists(join(p, ".kb")));
  const looksVaultDir = (p: string): boolean =>
    exists(join(p, "raw")) && exists(join(p, "wiki")) && exists(join(p, "facts"));

  // Where the scriptorium vault/ dir sits relative to the Obsidian vault root.
  let vaultPrefix: string | null = null;
  if (looksVaultDir(basePath)) vaultPrefix = "";
  else if (exists(join(basePath, "vault"))) vaultPrefix = "vault";

  // The dir scrip should treat as --root.
  let root: string | null = override ? trimSlash(override) : null;
  if (!root) {
    if (looksRootDir(basePath)) {
      root = trimSlash(basePath);
    } else if (looksVaultDir(basePath)) {
      const p = parent(basePath);
      if (exists(join(p, "SPEC.md")) || exists(join(p, ".kb"))) root = p;
    }
  }

  if (root === null || vaultPrefix === null) return null;
  return { root, vaultPrefix };
}

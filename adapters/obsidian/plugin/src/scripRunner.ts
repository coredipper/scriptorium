// Spawns the `scrip` CLI and returns parsed `--json` output. Desktop-only: the
// caller guards on Platform.isDesktopApp. `node:child_process` is loaded lazily
// (dynamic import) so merely importing this module never touches Node — keeping
// the plugin loadable on Obsidian mobile. Obsidian-free, so the parse logic is
// unit-testable with a fake executable.

export class ScripNotFound extends Error {}

export class ScripFailed extends Error {
  code: number | null;
  stderr: string;
  constructor(message: string, code: number | null, stderr: string) {
    super(message);
    this.name = "ScripFailed";
    this.code = code;
    this.stderr = stderr;
  }
}

export class ScripParseError extends Error {}

export interface ScripRunner {
  run<T>(args: string[]): Promise<T>;
}

export function createScripRunner(scripPath: string, root: string): ScripRunner {
  return {
    async run<T>(args: string[]): Promise<T> {
      const { execFile } = await import("node:child_process");
      const full = [...args, "--root", root, "--json"];
      return new Promise<T>((resolve, reject) => {
        execFile(
          scripPath,
          full,
          { maxBuffer: 32 * 1024 * 1024, timeout: 30_000 },
          (err, stdout, stderr) => {
            // status/verify exit non-zero when there ARE findings, yet still
            // print valid JSON on stdout — so always try stdout first.
            const text = (stdout ?? "").trim();
            if (err) {
              const e = err as NodeJS.ErrnoException;
              if (e.code === "ENOENT") {
                reject(new ScripNotFound(`scrip not found at '${scripPath}'`));
                return;
              }
              if (text.startsWith("{") || text.startsWith("[")) {
                try {
                  resolve(JSON.parse(text) as T);
                  return;
                } catch {
                  /* fall through to failure */
                }
              }
              const code = typeof e.code === "number" ? e.code : null;
              reject(
                new ScripFailed(
                  `scrip ${args.join(" ")} failed`,
                  code,
                  stderr || String(err),
                ),
              );
              return;
            }
            try {
              resolve(JSON.parse(text) as T);
            } catch {
              reject(
                new ScripParseError(
                  `could not parse scrip JSON: ${text.slice(0, 200)}`,
                ),
              );
            }
          },
        );
      });
    },
  };
}

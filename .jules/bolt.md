## 2024-05-24 - Python String Split over Regex
**Learning:** Using `" ".join(text.split())` is approximately 4-5x faster than using `re.sub(r"\s+", " ", text).strip()` for collapsing whitespace and trimming ends, as Python's native `split()` without arguments automatically splits on all whitespace and discards empty strings.
**Action:** When normalizing whitespace in Python, prefer `split()` and `join()` over regular expressions unless complex pattern matching is required.

## 2024-06-17 - O(1) Cache for Block Hashes Lookup
**Learning:** Checking for block dependencies inside large lists (`r["blocks"]`) scaled terribly O(n) for operations running heavily in loops (e.g. `_dep_hash` dependency resolution). Using a lazy-initialized `_blocks_map` hash dictionary for caching significantly improved hash checking (`O(n)` to `O(1)`).
**Action:** Always prefer maps/dictionaries (e.g. `_blocks_map`) instead of `O(n)` list iterations if a property lookup logic executes frequently in the codebase.

## 2024-06-21 - Memory Overhead of String Operations on Large Files
**Learning:** Using `Path.read_text().splitlines()` on large `.md` files incurs heavy memory and O(N) allocation overhead. In operations that only need metadata (frontmatter) from a file, eagerly loading the entire file body scales poorly.
**Action:** When extracting subset metadata (like YAML frontmatter) from large string files, use python iterators `open(p, "r")` line-by-line reading and `break` loops early instead of using `read_text().splitlines()` or `read()`. Always abstract early reads to a dedicated `load_meta()` operation.

## 2024-07-23 - PyYAML C-extension Acceleration
**Learning:** Pure Python `yaml.safe_load` is extremely slow. Using the C-extension (`CSafeLoader`) provides a ~7x speedup for parsing YAML frontmatter in large files. However, `CSafeDumper` does not support `sort_keys=False`, meaning insertion order cannot be preserved.
**Action:** When working with PyYAML, use `yaml.load(..., Loader=SafeLoader)` (where `SafeLoader` falls back from `CSafeLoader` to pure Python) for fast reads, but continue using `yaml.safe_dump` if you need to preserve insertion order (e.g., to keep frontmatter file diffs clean).

## 2024-07-28 - Single Pass Block Segmentation
**Learning:** In operations that process text files line-by-line (like markdown block segmentation), accumulating intermediate lists (e.g., span tuples containing start/end and full lines) introduces significant memory overhead and repeated O(N) iteration loops. Merging the tracking logic directly inside the main `splitlines()` loop saves allocations and iteration cycles.
**Action:** Always prefer a single pass strategy when generating indices or ranges over raw text files; avoid constructing intermediary sequence arrays (`spans: list[...]`) that are merely used to inform the final range boundaries.

## 2024-08-05 - Avoid premature optimization on rarely hit defensive fallback paths
**Learning:** Sometimes optimizations change edge-case behavior. For instance, swapping `splitlines()` for `\n`-only `find/rfind` loses Python's broad line separator support (like U+2028). When the path being optimized is a defensive fallback rarely hit on large strings, the behavioral risk outweighs the micro-optimization reward.
**Action:** Before optimizing a block of code, verify if it is an actual hot path. Do not optimize fallback blocks if the optimization changes subtle edge-case behavior (like Unicode line-breaking sensitivity) without sufficient test coverage.

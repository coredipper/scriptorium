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

## 2024-08-01 - Avoid splitlines() for text trimming
**Learning:** Using `splitlines()` to remove boundary lines (such as markdown code block backticks ` ``` ` around JSON strings) from large text payloads creates a massive, temporary array of all lines in memory. This introduces `O(N)` memory overhead and compute simply to discard the first and last items.
**Action:** To prevent memory overhead and O(N) allocations when extracting string data by trimming prefix/suffix boundaries, prefer string searching (`find()` and `rfind()`) and slicing rather than full segmentation via `splitlines()`.
## 2024-11-20 - io.StringIO over string split
**Learning:** Using `text.split("\n")` to parse huge NDJSON files into lines copies the entire text into memory as a list of strings, peaking at around ~150MB of RAM for a ~100MB string. By using `io.StringIO(text, newline="\n")` instead, we can process lines lazily, saving significant memory.
**Action:** When extracting data line-by-line from a large string payload, prefer `io.StringIO(text)` over `text.split()`.

## 2024-11-20 - io.StringIO memory peak [Superseded]
**Learning:** `io.StringIO(text)` over `text.split("\n")` was previously thought to reduce peak memory for in-memory NDJSON strings, however this is incorrect. A different approach (LF-only iterator and direct file streaming) is required to properly reduce memory for parsing large text strings in memory.
**Action:** Do not rely on `io.StringIO` to reduce memory peaks for large string variables; explore file streams or true lazy iterators instead.

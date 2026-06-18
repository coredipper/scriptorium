## 2024-05-24 - Python String Split over Regex
**Learning:** Using `" ".join(text.split())` is approximately 4-5x faster than using `re.sub(r"\s+", " ", text).strip()` for collapsing whitespace and trimming ends, as Python's native `split()` without arguments automatically splits on all whitespace and discards empty strings.
**Action:** When normalizing whitespace in Python, prefer `split()` and `join()` over regular expressions unless complex pattern matching is required.

## 2024-06-17 - O(1) Cache for Block Hashes Lookup
**Learning:** Checking for block dependencies inside large lists (`r["blocks"]`) scaled terribly O(n) for operations running heavily in loops (e.g. `_dep_hash` dependency resolution). Using a lazy-initialized `_blocks_map` hash dictionary for caching significantly improved hash checking (`O(n)` to `O(1)`).
**Action:** Always prefer maps/dictionaries (e.g. `_blocks_map`) instead of `O(n)` list iterations if a property lookup logic executes frequently in the codebase.

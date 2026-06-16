## 2024-05-24 - Faster NDJSON reading
**Learning:** `path.read_text(encoding="utf-8").splitlines()` on large `.ndjson` files reads the entire file into memory as a giant string and then creates a list of strings, which is slow and memory-intensive. `with path.open() as f: for line in f:` is much faster and uses stream-reading.
**Action:** Replace `p.read_text().splitlines()` with `with p.open() as f: for line in f:` when reading `.ndjson` files line-by-line, such as in `_source_tags` in `similar.py`.

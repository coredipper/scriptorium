import re

text = open(".jules/bolt.md", "r").read()
# Replace the last entry which is the flawed learning
lines = text.splitlines()

# find the index of "## 2024-07-29"
idx = -1
for i, line in enumerate(lines):
    if line.startswith("## 2024-07-29"):
        idx = i
        break

if idx != -1:
    lines = lines[:idx]

# Add the correct learning
new_learning = """## 2024-07-29 - String Slicing vs splitlines() Risk
**Learning:** Replacing `splitlines()` with `find('\\n')` for trimming markdown blocks introduces a subtle correctness risk because `splitlines()` handles other line separators (e.g., `U+2028`, `\\r\\n`) which `find('\\n')` misses. Additionally, optimizing cold paths (e.g., `_json_from_text` which runs once per LLM completion, where fallback code paths rarely fire) offers negligible reward but introduces unverified test risks.
**Action:** Do not micro-optimize cold paths or error fallback branches. When rewriting `splitlines()` to string searching, ensure equivalent behavior for non-`\\n` line separators (like `\\r\\n` and `U+2028`)."""

lines.append(new_learning)
open(".jules/bolt.md", "w").write("\n".join(lines) + "\n")

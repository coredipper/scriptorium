with open("scrip/tests/test_facts.py", "r") as f:
    content = f.read()

import re

search_block_iter = """def test_iter_lf_lines_matches_split_newline_semantics():
    samples = [
        "",
        "one",
        "one\\n",
        "one\\n\\n",
        "one\\r\\ntwo\\r\\n",
        "one\\rtwo",
        "one\\u2028two\\ntwo\\u2029three",
    ]
    for text in samples:
        assert list(facts._iter_lf_lines(text)) == text.split("\\n")


def test_parse_ndjson_basic():"""

replace_block_iter = """def test_parse_ndjson_basic():"""

if search_block_iter in content:
    content = content.replace(search_block_iter, replace_block_iter)
    print("Removed test_iter_lf_lines_matches_split_newline_semantics")
else:
    print("Could not find test_iter_lf_lines_matches_split_newline_semantics")

search_imports = """import pytest
from scrip.errors import DataError, UsageError

from scrip import facts"""
replace_imports = """import io
import pytest
from scrip.errors import DataError, UsageError

from scrip import facts"""
if search_imports in content:
    content = content.replace(search_imports, replace_imports)

# Replace all facts.parse_ndjson(text) with facts.parse_ndjson(io.StringIO(text, newline="\n"))
# Note: we can just do string replacements for facts.parse_ndjson(
content = re.sub(
    r'facts\.parse_ndjson\((.*?)\)',
    r'facts.parse_ndjson(io.StringIO(\1, newline="\\n"))',
    content
)

with open("scrip/tests/test_facts.py", "w") as f:
    f.write(content)
print("Patched test_facts.py successfully")

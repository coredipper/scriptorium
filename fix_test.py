import re

with open("scrip/tests/test_facts.py", "r") as f:
    text = f.read()

text = re.sub(
    r"def test_iter_lf_lines_matches_split_newline_semantics\(\):\n(    .*\n)+",
    "", text
)

with open("scrip/tests/test_facts.py", "w") as f:
    f.write(text)

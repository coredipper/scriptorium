with open("scrip/src/scrip/facts.py", "r") as f:
    content = f.read()

# Replace _iter_lf_lines and parse_ndjson
import re

search_block = """def _iter_lf_lines(text: str) -> Iterator[str]:
    \"\"\"Yield ``text.split("\\n")``-equivalent lines without allocating the list.\"\"\"
    start = 0
    while True:
        end = text.find("\\n", start)
        if end == -1:
            yield text[start:]
            return
        yield text[start:end]
        start = end + 1


def parse_ndjson(text: str) -> list[dict]:
    \"\"\"Parse proposed records (one JSON object per line). Malformed input is a
    :class:`DataError` with its line number; an empty input is a usage error.\"\"\"
    records: list[dict] = []
    # Split on "\\n" only, not str.splitlines(): NDJSON records are newline-
    # delimited and may legally contain U+2028/U+2029/NEL inside a JSON string,
    # which splitlines() would wrongly treat as record breaks. trailing \\r (from
    # \\r\\n) and the trailing empty element from a final newline are dropped below.
    for lineno, raw_line in enumerate(_iter_lf_lines(text), start=1):
        line = raw_line.strip()"""

replace_block = """def parse_ndjson(lines: Iterable[str]) -> list[dict]:
    \"\"\"Parse proposed records (one JSON object per line). Malformed input is a
    :class:`DataError` with its line number; an empty input is a usage error.\"\"\"
    records: list[dict] = []
    # Bolt optimization: Accept Iterable[str] to stream NDJSON line-by-line
    # instead of allocating the entire payload in memory.
    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()"""

if search_block in content:
    content = content.replace(search_block, replace_block)
    with open("scrip/src/scrip/facts.py", "w") as f:
        f.write(content)
    print("Patched scrip/src/scrip/facts.py successfully")
else:
    print("Could not find block in scrip/src/scrip/facts.py")

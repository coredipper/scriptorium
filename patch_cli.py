with open("scrip/src/scrip/cli.py", "r") as f:
    content = f.read()

import re

search_block = """    if args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            raise errors.UsageError(f"cannot read --file: {e}") from e
    else:
        text = sys.stdin.read()
    result = facts.add(root, args.table, facts.parse_ndjson(text))"""

replace_block = """    if args.file:
        try:
            # Bolt optimization: stream NDJSON file line-by-line to avoid O(N) memory allocation
            with open(Path(args.file), "r", encoding="utf-8", newline="\\n") as f:
                result = facts.add(root, args.table, facts.parse_ndjson(f))
        except OSError as e:
            raise errors.UsageError(f"cannot read --file: {e}") from e
    else:
        # Stream from stdin. Use buffer + TextIOWrapper if available to control newline
        if hasattr(sys.stdin, "buffer"):
            import io
            stream = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", newline="\\n")
        else:
            stream = sys.stdin
        result = facts.add(root, args.table, facts.parse_ndjson(stream))"""

if search_block in content:
    content = content.replace(search_block, replace_block)
    with open("scrip/src/scrip/cli.py", "w") as f:
        f.write(content)
    print("Patched scrip/src/scrip/cli.py successfully")
else:
    print("Could not find block in scrip/src/scrip/cli.py")

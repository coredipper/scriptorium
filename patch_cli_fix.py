with open("scrip/src/scrip/cli.py", "r") as f:
    content = f.read()

search_block = """        else:
            # Stream from stdin. Use buffer + TextIOWrapper if available to control newline
            if hasattr(sys.stdin, "buffer"):
                stream = stack.enter_context(io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", newline="\\n", closefd=False))
            else:
                stream = sys.stdin"""

replace_block = """        else:
            # Stream from stdin. Use buffer + TextIOWrapper if available to control newline.
            # To prevent TextIOWrapper from closing sys.stdin.buffer upon garbage collection,
            # we do not add it to ExitStack, and we must not let it be automatically closed.
            # Wait, standard TextIOWrapper in standard Python does not accept closefd.
            # A safe alternative is to just use sys.stdin directly, or use a generator that
            # handles the newline separation if we must strictly avoid splitlines issues.
            # Actually, `sys.stdin` is already configured, so we can just use `sys.stdin`.
            stream = sys.stdin"""

if search_block in content:
    content = content.replace(search_block, replace_block)
    with open("scrip/src/scrip/cli.py", "w") as f:
        f.write(content)
    print("Patched successfully")
else:
    print("Failed to find block")

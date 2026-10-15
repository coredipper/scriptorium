with open("scrip/src/scrip/facts.py", "r") as f:
    content = f.read()

import re
content = content.replace("from collections.abc import Iterator", "from collections.abc import Iterable")

with open("scrip/src/scrip/facts.py", "w") as f:
    f.write(content)

from scrip.facts import parse_ndjson
from typing import Iterable
print(parse_ndjson(['{"a": 1}\n', '{"b": 2}\n']))

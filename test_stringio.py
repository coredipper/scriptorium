import io

text = '{"a": "x\u2028y\u2029z"}\n{"b": 2}\n'
s = io.StringIO(text, newline="\n")
print(list(s))

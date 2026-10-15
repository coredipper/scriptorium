import io
text = '{"a": "x\u2028y\u2029z"}\n{"b": 2}\n'
f = io.StringIO(text)
print(list(f))

f2 = io.StringIO(text, newline="\n")
print(list(f2))

import io
text = '{"a": "x\ry\rz"}\r\n{"b": 2}\n'
f = io.StringIO(text)
print(list(f))

f2 = io.StringIO(text, newline="\n")
print(list(f2))

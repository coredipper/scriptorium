import sys
import io

def test():
    has_buffer = hasattr(sys.stdin, 'buffer')
    print("has_buffer", has_buffer)

test()

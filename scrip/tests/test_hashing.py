from scrip import hashing


def test_identical_bytes_same_hash():
    assert hashing.sha256_bytes(b"abc") == hashing.sha256_bytes(b"abc")


def test_one_char_changes_hash():
    assert hashing.sha256_text("hello") != hashing.sha256_text("hellp")


def test_hash_is_namespaced_and_fixed_length():
    h = hashing.sha256_text("x")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_content_hash_file(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"data")
    assert hashing.content_hash_file(p) == hashing.sha256_bytes(b"data")


def test_input_hash_order_independent():
    a = hashing.input_hash({"raw/a": "sha256:1", "raw/b": "sha256:2"})
    b = hashing.input_hash({"raw/b": "sha256:2", "raw/a": "sha256:1"})
    assert a == b


def test_input_hash_changes_with_dep_content():
    a = hashing.input_hash({"raw/a": "sha256:1"})
    b = hashing.input_hash({"raw/a": "sha256:2"})
    assert a != b


def test_input_hash_changes_when_dep_added():
    a = hashing.input_hash({"raw/a": "sha256:1"})
    b = hashing.input_hash({"raw/a": "sha256:1", "raw/b": "sha256:2"})
    assert a != b

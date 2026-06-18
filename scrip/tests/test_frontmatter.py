import pytest
from scrip.errors import DataError

from scrip import frontmatter


# --- parse ----------------------------------------------------------------
def test_parse_no_frontmatter_returns_whole_text():
    meta, body = frontmatter.parse("just a body\n")
    assert meta == {}
    assert body == "just a body\n"


def test_parse_valid_mapping():
    meta, body = frontmatter.parse("---\nid: concept/x\nn: 3\n---\nBody.\n")
    assert meta == {"id": "concept/x", "n": 3}
    assert body == "Body.\n"


def test_parse_empty_frontmatter_is_empty_dict():
    meta, body = frontmatter.parse("---\n---\nbody\n")
    assert meta == {}
    assert body == "body\n"


def test_parse_invalid_yaml_raises():
    with pytest.raises(DataError):
        frontmatter.parse("---\nfoo: [unclosed\n---\nbody\n")


def test_parse_non_mapping_raises():
    with pytest.raises(DataError):
        frontmatter.parse("---\n- a\n- b\n---\nbody\n")  # a list, not a mapping


def test_parse_unterminated_raises():
    with pytest.raises(DataError):
        frontmatter.parse("---\nid: x\nno closing fence here\n")


# --- load / dump ----------------------------------------------------------
def test_load_missing_file_raises(tmp_path):
    with pytest.raises(DataError):
        frontmatter.load(tmp_path / "nope.md")


def test_dump_roundtrips_and_preserves_insertion_order():
    meta = {"id": "concept/x", "type": "wiki.concept", "derived-from": ["raw/a"]}
    text = frontmatter.dump(meta, "Body.\n")
    meta2, body2 = frontmatter.parse(text)
    assert meta2 == meta
    assert body2 == "Body.\n"
    assert text.index("id:") < text.index("type:") < text.index("derived-from:")


# --- require --------------------------------------------------------------
def test_require_raises_on_missing():
    with pytest.raises(DataError):
        frontmatter.require({"a": 1}, ["a", "b"], where="page")


def test_require_passes_when_present():
    frontmatter.require({"a": 1, "b": 2}, ["a", "b"])  # no raise


# --- typed accessors (new) ------------------------------------------------
def test_as_str_returns_value_or_none():
    assert frontmatter.as_str({"k": "v"}, "k") == "v"
    assert frontmatter.as_str({}, "k") is None
    assert frontmatter.as_str({"k": None}, "k") is None


def test_as_str_rejects_non_string():
    with pytest.raises(DataError):
        frontmatter.as_str({"k": 3}, "k")
    with pytest.raises(DataError):
        frontmatter.as_str({"k": ["a"]}, "k")


def test_as_str_list_returns_list_or_empty():
    assert frontmatter.as_str_list({"k": ["a", "b"]}, "k") == ["a", "b"]
    assert frontmatter.as_str_list({}, "k") == []
    assert frontmatter.as_str_list({"k": None}, "k") == []


def test_as_str_list_rejects_bare_string_and_non_string_items():
    with pytest.raises(DataError):
        frontmatter.as_str_list({"k": "raw/a"}, "k")  # bare string would char-split
    with pytest.raises(DataError):
        frontmatter.as_str_list({"k": [1, 2]}, "k")


def test_accessor_error_names_the_location():
    with pytest.raises(DataError) as ei:
        frontmatter.as_str_list({"derived-from": "raw/a"}, "derived-from", where="wiki/x.md")
    assert "wiki/x.md" in str(ei.value)
    assert "derived-from" in str(ei.value)

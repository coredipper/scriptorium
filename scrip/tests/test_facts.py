import pytest

from scrip import facts
from scrip.errors import DataError, UsageError


def test_parse_ndjson_basic():
    text = '{"a": 1}\n{"b": 2}\n'
    assert facts.parse_ndjson(text) == [{"a": 1}, {"b": 2}]


def test_parse_ndjson_skips_blank_lines_and_strips_crlf():
    text = '{"a": 1}\r\n\r\n{"b": 2}\r\n'
    assert facts.parse_ndjson(text) == [{"a": 1}, {"b": 2}]


def test_parse_ndjson_keeps_u2028_inside_json_string():
    # U+2028 / U+2029 are legal *inside* a JSON string value. str.splitlines()
    # treats them as line breaks and would split this record into invalid
    # fragments; splitting on "\n" only keeps the record intact.
    text = '{"a": "x y z"}\n{"b": 2}\n'
    assert facts.parse_ndjson(text) == [{"a": "x y z"}, {"b": 2}]


def test_parse_ndjson_reports_line_number_on_bad_json():
    text = '{"a": 1}\nnot json\n'
    with pytest.raises(DataError) as exc:
        facts.parse_ndjson(text)
    assert "line 2" in str(exc.value)


def test_parse_ndjson_empty_is_usage_error():
    with pytest.raises(UsageError):
        facts.parse_ndjson("  \n  \n")

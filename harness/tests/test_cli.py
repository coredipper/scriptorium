"""Pure unit tests for cli.py argument helpers — no argparse, no model, no scrip."""

from scrip_harness.cli import _normalize_sources


def test_normalize_sources_strips_each_part_before_prefixing():
    # whitespace around a comma-separated part must be stripped BEFORE the raw/
    # prefix check, or " raw/b" wrongly becomes "raw/ raw/b"
    assert _normalize_sources("raw/a, raw/b") == ["raw/a", "raw/b"]


def test_normalize_sources_prefixes_bare_slugs():
    assert _normalize_sources("a, b") == ["raw/a", "raw/b"]
    assert _normalize_sources("raw/a,b") == ["raw/a", "raw/b"]


def test_normalize_sources_drops_empty_parts():
    # an all-empty value yields nothing — the CLI treats that as a usage error
    assert _normalize_sources(",") == []
    assert _normalize_sources("") == []
    assert _normalize_sources(" , raw/a , ") == ["raw/a"]

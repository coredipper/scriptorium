"""Minimal YAML frontmatter parsing — no third-party 'frontmatter' package.

A document is ``---\\n<yaml>\\n---\\n<body>``. We split on the fence lines and let
PyYAML parse the middle. Keeping this in-house (≈40 lines) is what lets the
whole CLI stay "a few hundred LOC" with only duckdb + pyyaml as real deps.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader

from .errors import DataError

FENCE = "---"


def parse(text: str) -> tuple[dict, str]:
    """Return ``(meta, body)``. If there is no frontmatter, ``meta`` is ``{}``
    and ``body`` is the whole text."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != FENCE:
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == FENCE:
            fm_text = "".join(lines[1:i])
            body = "".join(lines[i + 1 :])
            try:
                meta = yaml.load(fm_text, Loader=SafeLoader)
            except yaml.YAMLError as e:
                raise DataError(f"invalid YAML frontmatter: {e}") from e
            if meta is None:
                meta = {}
            if not isinstance(meta, dict):
                raise DataError("frontmatter must be a YAML mapping")
            return meta, body
    raise DataError("unterminated frontmatter (missing closing '---')")


def _read_frontmatter(f) -> tuple[bool, dict]:
    first_line = f.readline()
    if not first_line or first_line.strip() != FENCE:
        return False, {}

    fm_lines = []
    for line in f:
        if line.strip() == FENCE:
            break
        fm_lines.append(line)
    else:
        raise DataError("unterminated frontmatter (missing closing '---')")

    try:
        meta = yaml.load("".join(fm_lines), Loader=SafeLoader)
    except yaml.YAMLError as e:
        raise DataError(f"invalid YAML frontmatter: {e}") from e
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise DataError("frontmatter must be a YAML mapping")
    return True, meta


def load(path: str | Path) -> tuple[dict, str]:
    p = Path(path)
    try:
        with open(p, encoding="utf-8") as f:
            found, meta = _read_frontmatter(f)
            if not found:
                f.seek(0)
                return {}, f.read()
            body = f.read()
            return meta, body
    except OSError as e:
        raise DataError(f"cannot read {p}: {e}") from e


def load_meta(path: str | Path) -> dict:
    """Read just the frontmatter from a file without loading the body.
    Significantly faster for metadata-only operations like scanning the vault."""
    p = Path(path)
    try:
        with open(p, encoding="utf-8") as f:
            _, meta = _read_frontmatter(f)
            return meta
    except OSError as e:
        raise DataError(f"cannot read {p}: {e}") from e


def dump(meta: dict, body: str) -> str:
    """Serialize back to a frontmatter document. Insertion order is preserved
    (``sort_keys=False``) so files diff cleanly."""
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"{FENCE}\n{fm}\n{FENCE}\n{body}"


def require(meta: dict, keys: Iterable[str], where: str = "frontmatter") -> None:
    """Raise :class:`DataError` if any required key is absent."""
    missing = [k for k in keys if k not in meta]
    if missing:
        raise DataError(f"{where}: missing required key(s): {', '.join(missing)}")


def as_str(meta: dict, key: str, where: str = "frontmatter") -> str | None:
    """Return ``meta[key]`` as a string, or ``None`` if absent/null. Raise
    :class:`DataError` (naming ``where``) if present but not a string."""
    value = meta.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DataError(f"{where}: '{key}' must be a string, got {type(value).__name__}")
    return value


def as_str_list(meta: dict, key: str, where: str = "frontmatter") -> list[str]:
    """Return ``meta[key]`` as a list of strings, or ``[]`` if absent/null. Raise
    :class:`DataError` (naming ``where``) if present but not a list of strings.

    This is what stops a hand-edited bare string (``derived-from: raw/x``) from
    silently char-splitting into per-character dependency ids downstream."""
    value = meta.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise DataError(f"{where}: '{key}' must be a list of strings")
    return value

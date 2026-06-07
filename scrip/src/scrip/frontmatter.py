"""Minimal YAML frontmatter parsing — no third-party 'frontmatter' package.

A document is ``---\\n<yaml>\\n---\\n<body>``. We split on the fence lines and let
PyYAML parse the middle. Keeping this in-house (≈40 lines) is what lets the
whole CLI stay "a few hundred LOC" with only duckdb + pyyaml as real deps.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

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
                meta = yaml.safe_load(fm_text)
            except yaml.YAMLError as e:
                raise DataError(f"invalid YAML frontmatter: {e}") from e
            if meta is None:
                meta = {}
            if not isinstance(meta, dict):
                raise DataError("frontmatter must be a YAML mapping")
            return meta, body
    raise DataError("unterminated frontmatter (missing closing '---')")


def load(path: str | Path) -> tuple[dict, str]:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise DataError(f"cannot read {p}: {e}") from e
    return parse(text)


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

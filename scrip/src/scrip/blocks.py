"""Deterministic markdown block segmentation for sub-source staleness.

A *block* is a heading line or a run of non-blank, non-heading lines (a
paragraph). Blank lines are boundaries, never blocks. The split is a pure
function of the input, so the same source always yields the same blocks.

Each block records its char ``span`` into the original text and a ``hash`` of
the exact sliced substring. Editing one paragraph shifts the spans of later
blocks but leaves their sliced content — and therefore their hashes —
unchanged, which is what makes block-precise dependency tracking cheap and
correct (see SPEC §6.2).

``block_id`` is positional (``b0``, ``b1``, …). Positional ids are stable under
in-place edits; *inserting* a block renumbers later ids — a known limitation,
which is why whole-file dependencies are the v0 default and block-precise deps
are opt-in.
"""

from __future__ import annotations

from . import hashing


def _is_heading(line: str) -> bool:
    return line.lstrip().startswith("#")


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def split_blocks(text: str) -> list[dict]:
    """Return a list of ``{"block_id", "span": [start, end], "hash"}``."""
    # Index every line with its [start, end) char offsets.
    spans: list[tuple[int, int, str]] = []
    start = 0
    for line in text.splitlines(keepends=True):
        end = start + len(line)
        spans.append((start, end, line))
        start = end

    ranges: list[list[int]] = []  # [start, end] per block
    cur: list[int] | None = None
    for s, e, line in spans:
        if _is_blank(line):
            if cur is not None:
                ranges.append(cur)
                cur = None
        elif _is_heading(line):
            if cur is not None:
                ranges.append(cur)
                cur = None
            ranges.append([s, e])  # a heading is its own block
        else:
            if cur is None:
                cur = [s, e]
            else:
                cur[1] = e
    if cur is not None:
        ranges.append(cur)

    return [
        {
            "block_id": f"b{idx}",
            "span": [s, e],
            "hash": hashing.sha256_text(text[s:e]),
        }
        for idx, (s, e) in enumerate(ranges)
    ]

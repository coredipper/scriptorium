"""Deterministic markdown block segmentation for sub-source staleness.

A *block* is a heading line or a run of non-blank, non-heading lines (a
paragraph). Blank lines are boundaries, never blocks. The split is a pure
function of the input, so the same source always yields the same blocks.

Each block records its char ``span`` into the original text and a ``hash`` of
the exact sliced substring. Editing one paragraph shifts the spans of later
blocks but leaves their sliced content — and therefore their hashes —
unchanged, which is what makes block-precise dependency tracking cheap and
correct (see SPEC §7.2).

``block_id`` is **content-derived**: a short digest of the block's *normalized*
text (the same normalization provenance anchors use), so it is independent of
position. Inserting a block elsewhere leaves every other block's id untouched —
the insertion-stability that positional ids lacked. Blocks whose *normalized*
text is identical (byte-identical, or differing only in case/whitespace) share a
base id and are disambiguated by an occurrence suffix (``…:1``, ``…:2``); the
first occurrence keeps the bare id so it stays stable when a duplicate is
appended later.
"""

from __future__ import annotations

from . import hashing


def _is_heading(line: str) -> bool:
    return line.lstrip().startswith("#")


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def split_blocks(text: str) -> list[dict]:
    """Return a list of ``{"block_id", "span": [start, end], "hash"}``."""
    # Use splitlines(keepends=True): its boundary set (form feed, NEL, U+2028/9,
    # …) is part of the deterministic segmentation contract — io.StringIO only
    # splits on \r/\n and would re-hash existing blocks that contain those chars.
    # ⚡ Bolt Optimization: Calculate blocks in a single pass to avoid O(N) memory
    # allocation overhead from intermediate `ranges` list.
    out: list[dict] = []
    seen: dict[str, int] = {}

    cur_start: int | None = None
    cur_end = 0
    start = 0

    for line in text.splitlines(keepends=True):
        end = start + len(line)
        if _is_blank(line):
            if cur_start is not None:
                slice_text = text[cur_start:cur_end]
                out.append(
                    {
                        "block_id": _block_id(slice_text, seen),
                        "span": [cur_start, cur_end],
                        "hash": hashing.sha256_text(slice_text),
                    }
                )
                cur_start = None
        elif _is_heading(line):
            if cur_start is not None:
                slice_text = text[cur_start:cur_end]
                out.append(
                    {
                        "block_id": _block_id(slice_text, seen),
                        "span": [cur_start, cur_end],
                        "hash": hashing.sha256_text(slice_text),
                    }
                )
                cur_start = None

            slice_text = text[start:end]
            out.append(
                {
                    "block_id": _block_id(slice_text, seen),
                    "span": [start, end],
                    "hash": hashing.sha256_text(slice_text),
                }
            )
        else:
            if cur_start is None:
                cur_start = start
            cur_end = end
        start = end

    if cur_start is not None:
        slice_text = text[cur_start:cur_end]
        out.append(
            {
                "block_id": _block_id(slice_text, seen),
                "span": [cur_start, cur_end],
                "hash": hashing.sha256_text(slice_text),
            }
        )

    return out


def _block_id(slice_text: str, seen: dict[str, int]) -> str:
    """Content-derived id for a block: ``b`` + 12 hex of the normalized text's
    digest, with a ``:n`` suffix for normalized-identical repeats. ``seen``
    accumulates base-id occurrence counts across one ``split_blocks`` call.

    Identity is taken over the *normalized* text so reformatting (whitespace,
    case) does not change a block's id; the separate ``hash`` over the exact
    slice still captures byte changes for staleness. The empty-normalization
    fallback (hash the exact bytes instead) is defensive only: blank lines are
    already block boundaries, so every block holds ≥1 non-blank line and cannot
    normalize to empty — but the guard keeps the id total just in case.
    """
    norm = hashing.normalize(slice_text)
    digest = hashing.sha256_text(norm if norm else slice_text)
    base = "b" + digest.split(":", 1)[1][:12]
    n = seen.get(base, 0)
    seen[base] = n + 1
    return base if n == 0 else f"{base}:{n}"

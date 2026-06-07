from scrip import blocks, hashing

SAMPLE = (
    "# Title\n"
    "\n"
    "First paragraph line one.\n"
    "line two.\n"
    "\n"
    "Second paragraph.\n"
)


def _by_content(text: str) -> dict[str, str]:
    """Map each block's exact sliced text to its block_id."""
    out: dict[str, str] = {}
    for b in blocks.split_blocks(text):
        s, e = b["span"]
        out[text[s:e]] = b["block_id"]
    return out


def test_deterministic():
    assert blocks.split_blocks(SAMPLE) == blocks.split_blocks(SAMPLE)


def test_ids_are_content_derived_not_positional():
    ids = [b["block_id"] for b in blocks.split_blocks(SAMPLE)]
    # the old positional scheme is gone
    assert ids != ["b0", "b1", "b2"]
    # three distinct blocks -> three distinct ids
    assert len(ids) == 3
    assert len(set(ids)) == 3


def test_same_content_same_id_regardless_of_position():
    doc1 = "# T\n\nalpha block.\n\nbeta block.\n"
    doc2 = "# T\n\nbeta block.\n\nalpha block.\n"
    a, b = _by_content(doc1), _by_content(doc2)
    assert a["alpha block.\n"] == b["alpha block.\n"]
    assert a["beta block.\n"] == b["beta block.\n"]


def test_id_is_stable_under_whitespace_and_case_reflow():
    """Block identity survives reformatting (same normalization as anchors), even
    though the exact-slice ``hash`` changes."""
    b1 = blocks.split_blocks("Quick   BROWN fox.\n")[0]
    b2 = blocks.split_blocks("quick brown fox.\n")[0]
    assert b1["block_id"] == b2["block_id"]
    assert b1["hash"] != b2["hash"]  # exact bytes differ -> staleness still fires


def test_insert_block_preserves_other_block_ids():
    """THE insertion-stability property: adding a paragraph leaves every
    pre-existing block's id untouched (positional ids renumbered here)."""
    before = _by_content(SAMPLE)
    inserted = SAMPLE.replace(
        "line two.\n\nSecond paragraph.\n",
        "line two.\n\nInserted new paragraph.\n\nSecond paragraph.\n",
    )
    after = _by_content(inserted)
    for content, bid in before.items():
        assert after[content] == bid, f"id for {content!r} changed on insert"
    assert len(after) == len(before) + 1  # exactly one new block


def test_editing_a_block_changes_only_its_id():
    before = _by_content(SAMPLE)
    edited = SAMPLE.replace("Second paragraph.", "Second paragraph, revised.")
    after = _by_content(edited)
    # unchanged blocks keep their ids
    assert after["# Title\n"] == before["# Title\n"]
    assert (
        after["First paragraph line one.\nline two.\n"]
        == before["First paragraph line one.\nline two.\n"]
    )
    # the edited block's old id no longer exists
    assert before["Second paragraph.\n"] not in set(after.values())


def test_duplicate_blocks_get_distinct_ids():
    text = "# T\n\nrepeat me.\n\nrepeat me.\n"
    bs = blocks.split_blocks(text)
    dup_ids = [
        b["block_id"]
        for b in bs
        if "repeat me" in text[b["span"][0] : b["span"][1]]
    ]
    assert len(dup_ids) == 2
    assert dup_ids[0] != dup_ids[1]
    # the first occurrence keeps the bare id so it stays stable when a duplicate
    # is appended; later occurrences carry an occurrence suffix.
    assert dup_ids[1] == f"{dup_ids[0]}:1"


def _dup_ids(text: str, needle: str) -> list[str]:
    return [
        b["block_id"]
        for b in blocks.split_blocks(text)
        if needle in text[b["span"][0] : b["span"][1]]
    ]


def test_duplicate_insertion_shifts_occurrence_suffix():
    """Documented residual limitation (SPEC §7.2/§11): byte-identical blocks are
    disambiguated by occurrence order, so prepending an identical copy shifts the
    suffixes of the existing duplicates. Unique blocks are unaffected; only a
    dependency on a *duplicated* block is positional."""
    two = _dup_ids("# T\n\ndup.\n\ndup.\n", "dup.")
    assert ":" not in two[0]
    assert two[1] == f"{two[0]}:1"

    three = _dup_ids("# T\n\ndup.\n\ndup.\n\ndup.\n", "dup.")
    # the bare id stays with the first occurrence; the formerly-bare and formerly
    # ":1" blocks each shift down one — the known, inherent duplicate edge.
    assert three == [two[0], f"{two[0]}:1", f"{two[0]}:2"]


def test_spans_reconstruct_and_match_hash():
    for blk in blocks.split_blocks(SAMPLE):
        s, e = blk["span"]
        assert hashing.sha256_text(SAMPLE[s:e]) == blk["hash"]


def test_edit_shifts_later_spans_but_not_their_hash_or_id():
    """Editing an earlier paragraph moves the char-spans of later blocks but
    leaves their sliced content — hash and id — intact."""
    bs1 = blocks.split_blocks(SAMPLE)
    edited = SAMPLE.replace(
        "First paragraph line one.", "First paragraph line one EXTENDED."
    )
    bs2 = blocks.split_blocks(edited)
    assert bs1[1]["hash"] != bs2[1]["hash"]  # edited paragraph changed
    assert bs1[2]["hash"] == bs2[2]["hash"]  # later paragraph unchanged
    assert bs1[2]["block_id"] == bs2[2]["block_id"]  # ...and keeps its id
    assert bs1[2]["span"] != bs2[2]["span"]  # ...even though its span shifted


def test_blank_runs_are_boundaries_not_blocks():
    bs = blocks.split_blocks("\n\nonly paragraph\n\n")
    assert len(bs) == 1
    s, e = bs[0]["span"]
    assert "only paragraph" in "\n\nonly paragraph\n\n"[s:e]

from scrip import blocks, hashing

SAMPLE = (
    "# Title\n"
    "\n"
    "First paragraph line one.\n"
    "line two.\n"
    "\n"
    "Second paragraph.\n"
)


def test_deterministic():
    assert blocks.split_blocks(SAMPLE) == blocks.split_blocks(SAMPLE)


def test_block_count_and_positional_ids():
    bs = blocks.split_blocks(SAMPLE)
    # heading + 2 paragraphs
    assert [b["block_id"] for b in bs] == ["b0", "b1", "b2"]


def test_spans_reconstruct_and_match_hash():
    for blk in blocks.split_blocks(SAMPLE):
        s, e = blk["span"]
        assert hashing.sha256_text(SAMPLE[s:e]) == blk["hash"]


def test_edit_one_block_changes_only_that_hash():
    bs1 = blocks.split_blocks(SAMPLE)
    edited = SAMPLE.replace("Second paragraph.", "Second paragraph edited.")
    bs2 = blocks.split_blocks(edited)
    h1 = [b["hash"] for b in bs1]
    h2 = [b["hash"] for b in bs2]
    assert len(h1) == len(h2) == 3
    assert h1[0] == h2[0]
    assert h1[1] == h2[1]
    assert h1[2] != h2[2]


def test_edit_shifts_later_spans_but_not_their_hashes():
    """The core block-staleness property: editing an earlier paragraph moves the
    char-spans of later blocks but leaves their sliced content (and hash) intact."""
    bs1 = blocks.split_blocks(SAMPLE)
    edited = SAMPLE.replace(
        "First paragraph line one.", "First paragraph line one EXTENDED."
    )
    bs2 = blocks.split_blocks(edited)
    assert bs1[1]["hash"] != bs2[1]["hash"]  # edited paragraph changed
    assert bs1[2]["hash"] == bs2[2]["hash"]  # later paragraph unchanged
    assert bs1[2]["span"] != bs2[2]["span"]  # ...even though its span shifted


def test_blank_runs_are_boundaries_not_blocks():
    bs = blocks.split_blocks("\n\nonly paragraph\n\n")
    assert len(bs) == 1
    s, e = bs[0]["span"]
    assert "only paragraph" in "\n\nonly paragraph\n\n"[s:e]

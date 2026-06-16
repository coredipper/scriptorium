from scrip import anchors

SRC = "# Heading\n\nThe quick brown fox jumps over the lazy dog. Another sentence here.\n"


def test_anchor_resolves_in_its_source():
    a = anchors.make_anchor(SRC, "The quick brown fox jumps over the lazy dog.")
    assert anchors.resolve(SRC, a) == "OK"


def test_anchor_survives_reformatting_and_case():
    a = anchors.make_anchor(SRC, "The quick brown fox jumps over the lazy dog.")
    reflowed = (
        "#    Heading\n\nTHE   quick brown   fox\n"
        "jumps OVER the lazy dog.   Another sentence here.\n"
    )
    assert anchors.resolve(reflowed, a) == "OK"


def test_removed_quote_is_broken():
    a = anchors.make_anchor(SRC, "The quick brown fox jumps over the lazy dog.")
    assert anchors.resolve("Totally different text, no foxes at all.\n", a) == "BROKEN"


def test_duplicate_quote_is_ambiguous():
    dup = "alpha beta. alpha beta.\n"
    a = anchors.make_anchor(dup, "alpha beta.")
    assert anchors.resolve(dup, a) == "AMBIGUOUS"


def test_normalize_is_idempotent():
    once = anchors.normalize(SRC)
    assert anchors.normalize(once) == once


def test_make_anchor_roundtrips_through_parse():
    a = anchors.make_anchor(SRC, "Another sentence here.")
    parsed = anchors.parse_anchor(a)
    assert parsed["len"] == len(anchors.normalize("Another sentence here."))
    assert 0.0 <= parsed["loc"] <= 1.0

"""Embeddings-index cache invalidation. Hermetic: only ``_fingerprint`` is
exercised (no model backend needed) — the model-gated stale check in
``vector_search`` compares exactly this fingerprint."""

from scrip import embeddings, hashing, raw_dir


def _v1_fingerprint(root):
    """The pre-v2 fingerprint: a hash of raw *content* only, with no block-id
    schema marker. An index built this way carried positional block ids."""
    deps = {
        "raw/" + p.stem: hashing.content_hash_file(p) for p in sorted(raw_dir(root).glob("*.md"))
    }
    return hashing.input_hash(deps) if deps else "sha256:empty"


def test_fingerprint_invalidates_a_v1_positional_index(kb):
    """A v1 embeddings index (positional b0,b1,…) must read as STALE after the
    content-derived block-id switch even though raw content is unchanged — else
    `scrip search` returns block ids that no longer resolve."""
    kb.add_raw("a", "# A\n\nAlpha.\n\nBeta.\n")
    # raw content is identical, yet the schema-aware fingerprint must differ from
    # the content-only one a v1 index would have stored.
    assert embeddings._fingerprint(kb.root) != _v1_fingerprint(kb.root)


def test_fingerprint_stable_for_same_content_and_schema(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    assert embeddings._fingerprint(kb.root) == embeddings._fingerprint(kb.root)

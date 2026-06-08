"""`scrip new` — scaffold a wiki page's frontmatter for the agent to fill.
Deterministic, no model; acquires the write lock; refuses to overwrite."""

import pytest

from scrip import cli, frontmatter, graph, lock_path


def test_new_scaffolds_concept_page(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    rc = cli.main(
        ["new", "concept", "my-topic", "--from", "raw/a",
         "--title", "My Topic", "--root", str(kb.root)]
    )
    assert rc == 0
    path = kb.root / "vault" / "wiki" / "concepts" / "my-topic.md"
    meta, _ = frontmatter.load(path)
    assert meta["id"] == "concept/my-topic"
    assert meta["type"] == "wiki.concept"
    assert meta["title"] == "My Topic"
    assert meta["derived-from"] == ["raw/a"]
    # scaffold is uncompiled: no input-hash yet, so status flags it for compile
    assert "input-hash" not in meta
    res = graph.compute_status(kb.root, use_cache=False)
    assert "concept/my-topic" in {s["id"] for s in res["stale"]}


def test_new_entity_default_title_is_slug(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    rc = cli.main(["new", "entity", "duck-db", "--from", "raw/a", "--root", str(kb.root)])
    assert rc == 0
    meta, _ = frontmatter.load(kb.root / "vault" / "wiki" / "entities" / "duck-db.md")
    assert meta["id"] == "entity/duck-db"
    assert meta["type"] == "wiki.entity"
    assert meta["title"] == "duck-db"


def test_new_multiple_sources(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_raw("b", "# B\n\nBeta.\n")
    cli.main(["new", "concept", "x", "--from", "raw/a,raw/b", "--root", str(kb.root)])
    meta, _ = frontmatter.load(kb.root / "vault" / "wiki" / "concepts" / "x.md")
    assert meta["derived-from"] == ["raw/a", "raw/b"]


def test_new_refuses_overwrite_exit_2(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    assert cli.main(["new", "concept", "x", "--from", "raw/a", "--root", str(kb.root)]) == 0
    assert cli.main(["new", "concept", "x", "--from", "raw/a", "--root", str(kb.root)]) == 2


def test_new_missing_source_exit_3(kb):
    rc = cli.main(["new", "concept", "x", "--from", "raw/ghost", "--root", str(kb.root)])
    assert rc == 3


@pytest.mark.parametrize("bad", ["../evil", "a/b", "..", "/abs", ".hidden", "a b"])
def test_new_rejects_unsafe_slug_exit_2(kb, bad):
    """A slug must not be able to escape vault/wiki/{concepts,entities}."""
    kb.add_raw("a", "# A\n\nAlpha.\n")
    assert cli.main(["new", "concept", bad, "--from", "raw/a", "--root", str(kb.root)]) == 2
    # nothing was written outside the wiki concepts dir
    assert list((kb.root / "vault" / "wiki" / "concepts").glob("*.md")) == []
    assert not (kb.root.parent / "evil.md").exists()


def test_new_rejects_slug_with_trailing_newline(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    assert cli.main(["new", "concept", "x\n", "--from", "raw/a", "--root", str(kb.root)]) == 2


def test_new_rejects_unsafe_source_slug_exit_2(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    rc = cli.main(["new", "concept", "x", "--from", "../../etc/passwd", "--root", str(kb.root)])
    assert rc == 2


def test_new_then_stamp_goes_green(kb):
    """Scaffold integrates with the loop: after the body is filled and stamped,
    the page is fresh."""
    kb.add_raw("a", "# A\n\nAlpha fact.\n")
    cli.main(["new", "concept", "x", "--from", "raw/a", "--root", str(kb.root)])
    graph.stamp_artifacts(kb.root, ["vault/wiki/concepts/x.md"])
    assert graph.compute_status(kb.root, use_cache=False)["stale"] == []


def test_new_releases_lock(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    cli.main(["new", "concept", "x", "--from", "raw/a", "--root", str(kb.root)])
    assert not lock_path(kb.root).exists()

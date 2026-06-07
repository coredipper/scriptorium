import os
import shutil

from scrip import graph, manifest, manifest_path


def _dirty(res):
    return sorted(s["id"] for s in res["stale"])


def _okset(res):
    return sorted(o["id"] for o in res["ok"])


def test_losslessness_delete_and_rebuild_matches(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_raw("b", "# B\n\nBeta.\n")
    kb.add_wiki("x", ["raw/a"])
    kb.add_wiki("y", ["raw/b"])

    with_cache = graph.compute_status(kb.root, use_cache=True, rebuild=True)
    shutil.rmtree(kb.root / ".kb")
    from_files = graph.compute_status(kb.root, use_cache=False)

    assert _dirty(with_cache) == _dirty(from_files)
    assert _okset(with_cache) == _okset(from_files)


def test_cache_and_no_cache_agree_after_mutation(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"])
    graph.compute_status(kb.root, use_cache=True, rebuild=True)

    kb.mutate_raw("a", "# A\n\nAlpha changed.\n")
    cached = graph.compute_status(kb.root, use_cache=True)
    nocache = graph.compute_status(kb.root, use_cache=False)
    assert _dirty(cached) == _dirty(nocache) == ["concept/x"]


def test_manifest_written_and_shaped(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"])
    graph.compute_status(kb.root, use_cache=True, rebuild=True)

    assert manifest_path(kb.root).exists()
    data = manifest.load(kb.root)
    assert data["version"] == 1
    assert "raw/a" in data["raw"]
    assert "blocks" in data["raw"]["raw/a"]
    assert "concept/x" in data["derived"]


def test_same_size_edit_with_restored_mtime_is_still_detected(kb):
    """Regression for the cache-coherency hole: a byte change that preserves
    size AND restores the original mtime must still mark dependents stale,
    because status re-hashes raw content unconditionally."""
    kb.add_raw("a", "# A\n\nalpha value here.\n")
    kb.add_wiki("x", ["raw/a"])
    graph.compute_status(kb.root, use_cache=True, rebuild=True)  # seed the manifest

    p = kb.root / "vault" / "raw" / "a.md"
    st = p.stat()
    original = p.read_text()
    edited = original.replace("alpha", "ALPHA")  # same byte length, real change
    assert len(edited) == len(original)
    p.write_text(edited, encoding="utf-8")
    os.utime(p, (st.st_atime, st.st_mtime))  # restore the original mtime

    res = graph.compute_status(kb.root, use_cache=True)
    assert "concept/x" in {s["id"] for s in res["stale"]}


def test_corrupt_manifest_is_a_cache_miss_not_an_error(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"])
    manifest_path(kb.root).write_text("{ not json", encoding="utf-8")
    # Should silently fall back to recomputing from files.
    res = graph.compute_status(kb.root, use_cache=True)
    assert res["stale"] == []
    assert manifest.load(kb.root) is None

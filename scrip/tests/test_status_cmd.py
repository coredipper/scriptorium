"""`scrip status` at the CLI level: exit codes, --json shape, flag conflicts.
The staleness engine itself is covered in test_graph_status; this pins the
dispatch surface agents script against."""

import json

from scrip import cli, manifest_path


def test_status_clean_vault_exits_0(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"])
    assert cli.main(["status", "--root", str(kb.root)]) == 0
    assert "all artifacts fresh." in capsys.readouterr().out


def test_status_stale_exits_1(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    assert cli.main(["status", "--root", str(kb.root)]) == 1


def test_status_uncompiled_only_still_exits_0(kb):
    # UNCOMPILED is informational, not a finding: nothing depends on the source.
    kb.add_raw("a", "# A\n\nAlpha.\n")
    assert cli.main(["status", "--root", str(kb.root)]) == 0


def test_status_json_shape(kb, capsys):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    kb.add_raw("b", "# B\n\nBeta.\n")
    kb.add_wiki("x", ["raw/a"], stamp=False)
    rc = cli.main(["status", "--json", "--root", str(kb.root)])
    assert rc == 1
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"root", "stale", "ok", "uncompiled"}
    [stale] = data["stale"]
    assert set(stale) == {"id", "path", "reason", "changed_sources"}
    assert stale["id"] == "concept/x"
    assert [u["id"] for u in data["uncompiled"]] == ["raw/b"]


def test_status_fast_with_no_cache_is_usage_error(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    assert cli.main(["status", "--fast", "--no-cache", "--root", str(kb.root)]) == 2


def test_status_rebuild_manifest_writes_cache(kb):
    kb.add_raw("a", "# A\n\nAlpha.\n")
    assert not manifest_path(kb.root).exists()
    assert cli.main(["status", "--rebuild-manifest", "--root", str(kb.root)]) == 0
    assert manifest_path(kb.root).exists()


def test_status_outside_a_vault_is_usage_error(tmp_path):
    assert cli.main(["status", "--root", str(tmp_path / "nowhere")]) == 2

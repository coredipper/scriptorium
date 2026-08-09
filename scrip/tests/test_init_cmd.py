"""`scrip init` — create the root skeleton (vault/ layers + .kb/ cache) so a new
instance starts detectable and green. Idempotent in an existing root; refuses to
nest a new instance inside an existing one."""

import json

from scrip import cli, manifest_path


def test_init_creates_skeleton_and_manifest(tmp_path, capsys):
    root = tmp_path / "kb"
    assert cli.main(["init", str(root)]) == 0
    for rel in ("vault/raw", "vault/facts", "vault/wiki", ".kb"):
        assert (root / rel).is_dir()
    # same effect as `scrip status --rebuild-manifest`: the cache exists
    assert manifest_path(root).exists()
    out = capsys.readouterr().out
    assert f"initialized scriptorium root at {root}" in out
    assert "scrip ingest" in out  # next-steps hint: ingest -> compile -> verify
    assert "scrip verify" in out


def test_init_defaults_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    assert (tmp_path / "vault" / "raw").is_dir()
    assert (tmp_path / ".kb").is_dir()


def test_init_then_commands_resolve_root_without_flags(tmp_path, monkeypatch):
    """The dogfooding gap this command closes: after init, `scrip status` and
    `scrip verify` run green from inside the new root with no --root."""
    root = tmp_path / "kb"
    assert cli.main(["init", str(root)]) == 0
    monkeypatch.chdir(root)
    assert cli.main(["status"]) == 0
    assert cli.main(["verify"]) == 0


def test_init_existing_root_is_noop(tmp_path, capsys):
    root = tmp_path / "kb"
    assert cli.main(["init", str(root)]) == 0
    manifest_before = manifest_path(root).read_text(encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["init", str(root)]) == 0
    out = capsys.readouterr().out
    assert f"already a scriptorium root: {root}" in out
    # a true no-op: the manifest was not rewritten
    assert manifest_path(root).read_text(encoding="utf-8") == manifest_before


def test_init_detects_spec_marker_root_as_existing(kb, capsys):
    """A root marked by SPEC.md (no .kb/ needed) counts as already initialized."""
    assert cli.main(["init", str(kb.root)]) == 0
    assert "already a scriptorium root" in capsys.readouterr().out


def test_init_inside_existing_root_refused_exit_2(tmp_path):
    root = tmp_path / "kb"
    assert cli.main(["init", str(root)]) == 0
    nested = root / "vault" / "raw" / "sub"
    assert cli.main(["init", str(nested)]) == 2
    # nothing was created for the refused nested instance
    assert not nested.exists()


def test_init_target_is_a_file_exit_2(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("hi\n", encoding="utf-8")
    assert cli.main(["init", str(f)]) == 2


def test_init_fills_in_missing_layers(tmp_path):
    """A partial layout (vault/ alone is not a detectable root) is completed
    rather than refused."""
    root = tmp_path / "kb"
    (root / "vault" / "raw").mkdir(parents=True)
    assert cli.main(["init", str(root)]) == 0
    for rel in ("vault/facts", "vault/wiki", ".kb"):
        assert (root / rel).is_dir()


def test_init_layer_path_is_a_file_refused_exit_2(tmp_path):
    """A file squatting a layer path is refused cleanly (exit 2), not an
    uncaught FileExistsError mapped to the internal-error exit code."""
    root = tmp_path / "kb"
    (root / "vault").mkdir(parents=True)
    (root / "vault" / "facts").write_text("oops\n", encoding="utf-8")
    assert cli.main(["init", str(root)]) == 2


def test_init_json_shape(tmp_path, capsys):
    root = tmp_path / "kb"
    assert cli.main(["init", "--json", str(root)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"root", "status", "created"}
    assert data["status"] == "initialized"
    assert ".kb/manifest.json" in data["created"]
    assert cli.main(["init", "--json", str(root)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "exists"
    assert data["created"] == []

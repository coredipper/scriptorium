"""The public __version__ must match the installed package metadata, so a release
that bumps pyproject can't leave the runtime attribute stale."""

import importlib.metadata

import scrip_harness


def test_version_matches_package_metadata():
    assert scrip_harness.__version__ == importlib.metadata.version("scrip-harness")

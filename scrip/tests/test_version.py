"""The public __version__ must match the installed package metadata, so a release
that bumps pyproject can't leave the runtime attribute stale. (Dist name is
``scriptoria``; the import package is ``scrip``.)"""

import importlib.metadata

import scrip


def test_version_matches_package_metadata():
    assert scrip.__version__ == importlib.metadata.version("scriptoria")

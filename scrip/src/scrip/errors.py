"""Typed exceptions mapped to process exit codes.

Exit-code contract (uniform across subcommands):

    0  clean / success
    1  actionable finding (stale artifacts; broken citations) -- NOT an exception,
       it is a normal return value the agent branches on
    2  usage error (bad arguments, missing root, write blocked by the lock)
    3  data error (malformed frontmatter, unreadable NDJSON, missing source)
    4  internal error (any uncaught exception)

Only codes 2, 3 and 4 are raised as exceptions. Code 1 is returned by the
command handler because "your KB has stale pages" is an expected outcome, not a
failure.
"""

from __future__ import annotations


class ScripError(Exception):
    """Base class. Uncaught subclasses map to ``exit_code``."""

    exit_code = 4


class UsageError(ScripError):
    """Bad invocation: unknown args, unresolvable root, etc."""

    exit_code = 2


class DataError(ScripError):
    """The vault on disk violates the contract (bad frontmatter, bad NDJSON,
    a referenced source that does not exist, duplicate ids, ...)."""

    exit_code = 3


class LockError(ScripError):
    """A mutating command was blocked because another writer holds ``.kb/lock``.
    Maps to the usage exit code (2): it is an operational refusal, not bad data."""

    exit_code = 2

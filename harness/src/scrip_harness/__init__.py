"""scrip-harness — the runnable AGENT.md compile loop for scriptorium.

This is the **judgment** layer: it calls a model (Claude) to synthesize a wiki
page from a source, then delegates every *verifiable* step to the deterministic
``scrip`` CLI via subprocess — minting each citation with ``scrip anchor`` (which
rejects a quote that is not verbatim and unique) and recording provenance with
``scrip stamp``. So a hallucinated quote cannot survive into a stamped page.

``scrip`` never imports this package or any SDK; the dependency points the other
way. The harness is optional and lives outside the deterministic core.
"""

__version__ = "0.6.0"

# Reading note — Karpathy's LLM wiki

Karpathy points an agent at a local folder of markdown and has it build and maintain a wiki, browsed through Obsidian. The core stance is that Knowledge should be compiled into a maintained wiki, not retrieved from scratch on every query.

The division of labour: the agent maintains the wiki, while the human curates and asks questions. Raw sources stay immutable; the wiki layer is regenerable. Good answers should be filed back as wiki pages so the knowledge compounds.

What is left undefined: how freshness is tracked, how a claim is tied back to its source, and what 'lint' actually checks.

A later clarification: the wiki is a cache over the raw sources, never a replacement for them.

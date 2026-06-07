# Reading note — Ganglani's local RAG attempt

A hands-on local knowledge base built on llm.c: chunk, embed, retrieve top-k, generate, fully private. In practice it hits walls. Naive fixed-size chunking throws away document structure. Adding a new note currently means re-indexing everything. Answer quality lags GPT-4 class models, and CPU inference is slow.

The honest takeaway: the architecture is sound but the ergonomics are early, and nothing is ever synthesized — you still get fragments back.

# Reading note — RAG chunking limits

Fixed-size chunking severs sentences from their context and discards structure. The retriever then matches fragments by surface similarity, with no notion of which document or section they came from.

More fundamentally: retrieval surfaces fragments; it does not synthesize understanding. That is the gap a compiled wiki layer is meant to fill.

# Atlas Cache Policy

Atlas keeps prepared summaries in the compiled wiki before running broad raw retrieval. The policy says that fresh compiled notes are the first source for routine answers, because they already carry verified citations and current dependency hashes.

When compiled coverage is thin, Atlas falls back to raw source search and asks the model to cite a verbatim quote from the raw note. This fallback keeps answers possible without letting uncited wiki context become final evidence.

Every saved answer is written under explorations only after citation anchors resolve successfully. Operators can rerun status and verify after a saved answer to confirm the vault stayed green.

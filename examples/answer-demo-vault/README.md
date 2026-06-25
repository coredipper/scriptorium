# Answer Demo Vault

This is a small synthetic vault for exercising `scrip-harness answer` without
using private wiki data. It contains:

- two raw notes under `vault/raw/`
- four verified claim records under `vault/facts/claims.ndjson`
- a stamped `vault/facts/_meta.yaml`

Run:

```sh
scripts/demo_answer.sh
```

The default question is intentionally broad enough to gather both claim evidence
and raw fallback context.

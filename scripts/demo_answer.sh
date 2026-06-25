#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/demo_answer.sh [options] [question]

Run the answer flow against a green scriptorium vault. By default this uses the
sanitized fixture in examples/answer-demo-vault.

Options:
  --root PATH          Vault root to query (default: examples/answer-demo-vault)
  --provider NAME     auto, anthropic, openai, or gemini (default: auto)
  --model MODEL       Provider model id override
  --api-key-file PATH Provider API key file
  -k N                Evidence items per layer (default: 6)
  --save              Save the verified answer under vault/wiki/explorations/
  -h, --help          Show this help

Environment:
  SCRIP_CMD           Override the scrip executable
  SCRIP_HARNESS_CMD   Override the scrip-harness executable
EOF
}

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
pythonpath="$repo_root/harness/src:$repo_root/scrip/src${PYTHONPATH:+:$PYTHONPATH}"

root="$repo_root/examples/answer-demo-vault"
provider="${SCRIP_HARNESS_PROVIDER:-auto}"
model=""
api_key_file=""
save=0
k=6
question="How does Atlas answer questions safely?"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      root="$2"
      shift 2
      ;;
    --provider)
      provider="$2"
      shift 2
      ;;
    --model)
      model="$2"
      shift 2
      ;;
    --api-key-file)
      api_key_file="$2"
      shift 2
      ;;
    -k|--k)
      k="$2"
      shift 2
      ;;
    --save)
      save=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      question="$*"
      break
      ;;
    -*)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      question="$*"
      break
      ;;
  esac
done

if [[ -n "${SCRIP_CMD:-}" ]]; then
  scrip_cmd=("$SCRIP_CMD")
elif [[ -x "$repo_root/scrip/.venv/bin/python" ]]; then
  scrip_cmd=(env PYTHONPATH="$pythonpath" "$repo_root/scrip/.venv/bin/python" -m scrip.cli)
else
  scrip_cmd=(env PYTHONPATH="$pythonpath" uv run --project "$repo_root/scrip" python -m scrip.cli)
fi

if [[ -n "${SCRIP_HARNESS_CMD:-}" ]]; then
  harness_cmd=("$SCRIP_HARNESS_CMD")
elif [[ -x "$repo_root/harness/.venv/bin/python" ]]; then
  harness_cmd=(env PYTHONPATH="$pythonpath" "$repo_root/harness/.venv/bin/python" -m scrip_harness.cli)
else
  harness_cmd=(env PYTHONPATH="$pythonpath" uv run --project "$repo_root/harness" python -m scrip_harness.cli)
fi

echo "== status =="
"${scrip_cmd[@]}" status --root "$root"

echo
echo "== verify =="
"${scrip_cmd[@]}" verify --root "$root"

answer_cmd=(
  "${harness_cmd[@]}"
  answer "$question"
  --root "$root"
  --provider "$provider"
  -k "$k"
)
if [[ -n "$model" ]]; then
  answer_cmd+=(--model "$model")
fi
if [[ -n "$api_key_file" ]]; then
  answer_cmd+=(--api-key-file "$api_key_file")
fi
if [[ "$save" -eq 1 ]]; then
  answer_cmd+=(--save)
fi

echo
echo "== answer =="
exec "${answer_cmd[@]}"

#!/usr/bin/env bash
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" && source .venv/bin/activate && mkdir -p logs && rm -f logs/STOPPED

RULES="Nobody is available. Do not ask questions. Where the skill says to ask, \
take the most conservative reading and record it in docs/STATUS.md under 'Decisions for the human'. \
Never edit a frozen file (specs, contracts, acceptance tests) and never lower a metric floor. \
If the acceptance tests cannot pass without that, commit what works, write the blocker in docs/STATUS.md and stop. \
Module 4: write splits.json first and refit the feature thresholds on training scenes only before training any model."

run() {
  while :; do
    claude -p "$1" --permission-mode auto --permission-prompts none \
      --append-system-prompt "$RULES" --output-format stream-json --verbose > "$2" 2>&1
    res=$(jq -r 'select(.type=="result") | .result' "$2" 2>/dev/null | head -c 200)
    case "$res" in
      *"hit your weekly limit"*) echo "weekly limit" > logs/STOPPED; exit 1 ;;
      *"hit your session limit"*|*"hit your Opus limit"*|*"hit your Sonnet limit"*)
        mv "$2" "$2.limited.$(date +%H%M)"; sleep 600 ;;
      *) return 0 ;;
    esac
  done
}

for n in 4 5 6 8; do
  ok=0
  for try in 1 2 3; do
    run "/build-module $n" "logs/m${n}_try${try}.jsonl"
    if make accept N=$n > "logs/m${n}_accept.log" 2>&1; then ok=1; break; fi
    sleep 900
  done
  [ $ok = 1 ] || { echo "module $n failed its gate" > logs/STOPPED; exit 1; }
  [ "$n" = 4 ] && run "/leakage-check" logs/leakage.jsonl
done
echo done > logs/DONE

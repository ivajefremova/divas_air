#!/usr/bin/env bash
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" && source .venv/bin/activate && mkdir -p logs

RULES="Nobody is available until morning. Do not ask questions. Where the skill says to ask, \
take the most conservative reading and record it in docs/STATUS.md under 'Decisions for the human'. \
Never edit a frozen file (specs, contracts, acceptance tests) and never lower a metric floor. \
If the acceptance tests cannot pass without that, commit what works, write the blocker in docs/STATUS.md and stop."

run() {
  while :; do
    claude -p "$1" --permission-mode auto --permission-prompts none \
      --append-system-prompt "$RULES" --output-format stream-json --verbose > "$2" 2>&1
    grep -q "hit your weekly limit" "$2" && { echo "weekly limit" > logs/STOPPED; exit 1; }
    grep -qE "hit your (session|Opus|Sonnet) limit" "$2" || return 0
    mv "$2" "$2.limited.$(date +%H%M)"; sleep 600
  done
}

for n in 3 4 5 6 8; do
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
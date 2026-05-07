#!/usr/bin/env bash
# Run remaining ablation configs as subprocess with hard wall-clock timeout.
# Each config gets up to 45 min; if it hangs, the kernel kills the child
# and the orchestrator moves to the next config. Partial records survive
# because run_single_ablation_config.py writes after every question.
set -u

OUT_DIR="D:/adk/data_agent/nl2sql_eval_results/ablation_agentloop_2026-05-07_233516"
LOG="D:/adk/ablation3.log"
TIMEOUT_PER_CONFIG=2700  # 45 min
PY="D:/adk/.venv/Scripts/python.exe"
DRIVER="D:/adk/scripts/nl2sql_bench_cq/run_single_ablation_config.py"

export PYTHONPATH=D:/adk
export CQ_EVAL_QUESTION_TIMEOUT=90

mkdir -p "$OUT_DIR"

# Configs to run (resume: skip those with *_results.json already present)
ALL_CONFIGS=(Full noSemanticGrounding noIntentRouting noPostprocessor noSelfCorrection noFewShot)

echo "=== Ablation orchestrator starting $(date) ===" >> "$LOG"

for cfg in "${ALL_CONFIGS[@]}"; do
    result_file="$OUT_DIR/${cfg}_results.json"
    if [[ -f "$result_file" ]]; then
        echo "[skip] $cfg already done ($(date))" >> "$LOG"
        continue
    fi
    echo "--- [$cfg] start $(date) ---" >> "$LOG"
    timeout --signal=KILL "$TIMEOUT_PER_CONFIG" "$PY" "$DRIVER" "$cfg" "$OUT_DIR" >> "$LOG" 2>&1
    rc=$?
    echo "--- [$cfg] exit=$rc ($(date)) ---" >> "$LOG"
    # If timeout killed it (124 or 137), partial is still on disk — leave it
    # so a future rerun can resume from the same question count.
done

# Emit final summary
echo "" >> "$LOG"
echo "=== summary ===" >> "$LOG"
for cfg in "${ALL_CONFIGS[@]}"; do
    rf="$OUT_DIR/${cfg}_results.json"
    pf="$OUT_DIR/${cfg}_partial.json"
    if [[ -f "$rf" ]]; then
        line=$(python -c "import json; d=json.load(open('$rf',encoding='utf-8')); s=d['summary']; print(f'{s[\"ex\"]}/{s[\"n\"]} ({s[\"ex_rate\"]:.3f}) t={s[\"wall_clock_s\"]}s COMPLETE')")
    elif [[ -f "$pf" ]]; then
        line=$(python -c "import json; d=json.load(open('$pf',encoding='utf-8')); s=d['summary']; print(f'{s[\"ex\"]}/{s[\"n\"]} ({s[\"ex_rate\"]:.3f}) t={s[\"wall_clock_s\"]}s PARTIAL')")
    else
        line="NOT STARTED"
    fi
    printf "  %-25s %s\n" "$cfg" "$line" >> "$LOG"
done

echo "=== orchestrator done $(date) ===" >> "$LOG"

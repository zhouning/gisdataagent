#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

PYTHON_BIN="${PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
  if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

BUNDLE_DIR="${TWM_BUNDLE_DIR:-data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion}"
OPTIMIZATION_DIR="${TWM_OPTIMIZATION_DIR:-data_agent/test_data/twm_bishan_demo/optimization}"
OUTPUT="${TWM_VALIDATION_OUTPUT:-docs/reports/twm_validation_bundle.json}"
MARKDOWN_OUTPUT="${TWM_VALIDATION_MARKDOWN_OUTPUT:-docs/reports/twm_validation_bundle.md}"
SCENARIO="${TWM_VALIDATION_SCENARIO:-offline_validation_bundle}"
HORIZON="${TWM_VALIDATION_HORIZON:-3}"
SYNTHETIC_FOUNDATION="${TWM_SYNTHETIC_EXPERIMENT_FOUNDATION:-docs/reports/twm_synthetic_experiment_foundation.csv}"

ARGS=(
  "--bundle-dir" "$BUNDLE_DIR"
  "--optimization-dir" "$OPTIMIZATION_DIR"
  "--output" "$OUTPUT"
  "--markdown-output" "$MARKDOWN_OUTPUT"
  "--scenario" "$SCENARIO"
  "--horizon" "$HORIZON"
  "--synthetic-experiment-foundation" "$SYNTHETIC_FOUNDATION"
)

if [ -n "${TWM_PRODUCTION_OBSERVED_HISTORY:-}" ]; then
  ARGS+=("--production-observed-history" "$TWM_PRODUCTION_OBSERVED_HISTORY")
fi

if [ -n "${TWM_PRODUCTION_SCALE_PROFILE:-}" ]; then
  ARGS+=("--production-scale-profile" "$TWM_PRODUCTION_SCALE_PROFILE")
fi

if [ -n "${TWM_SCCA_OUTPUT_DIR:-}" ]; then
  ARGS+=("--scca-output-dir" "$TWM_SCCA_OUTPUT_DIR")
fi

if [ -n "${TWM_SCCA_RESULT_JSON:-}" ]; then
  ARGS+=("--scca-result-json" "$TWM_SCCA_RESULT_JSON")
fi

if truthy "${TWM_REQUIRE_SCCA_PASS:-0}"; then
  ARGS+=("--require-scca-pass")
fi

if truthy "${TWM_REQUIRE_PRODUCTION_READINESS:-0}"; then
  ARGS+=("--require-production-readiness")
fi

if truthy "${TWM_FAIL_ON_BLOCKED:-0}"; then
  ARGS+=("--fail-on-blocked")
fi

if truthy "${TWM_NO_WRITE_MARKDOWN:-0}"; then
  ARGS+=("--no-write-markdown")
fi

if ! truthy "${TWM_INCLUDE_AUXILIARY_TABLES:-1}"; then
  ARGS+=("--no-include-auxiliary-tables")
fi

echo "[twm-validation] python=${PYTHON_BIN}"
echo "[twm-validation] output=${OUTPUT}"
echo "[twm-validation] markdown=${MARKDOWN_OUTPUT}"
echo "[twm-validation] scenario=${SCENARIO}"
echo "[twm-validation] production_observed_history=${TWM_PRODUCTION_OBSERVED_HISTORY:-not_provided}"
echo "[twm-validation] production_scale_profile=${TWM_PRODUCTION_SCALE_PROFILE:-not_provided}"
echo "[twm-validation] require_production_readiness=${TWM_REQUIRE_PRODUCTION_READINESS:-0}"

cd "$ROOT_DIR"
exec "$PYTHON_BIN" "$ROOT_DIR/scripts/run_twm_validation_bundle.py" "${ARGS[@]}"

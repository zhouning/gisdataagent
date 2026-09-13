# TWM Offline Production Onboarding Hardening Design

- **Date**: 2026-06-26
- **Scope**: Narrow offline hardening slice for Territory World Model production onboarding
- **Status**: Approved for design by the user's request to proceed without real authoritative data

## Goal

Harden the TWM production-onboarding path while real authoritative natural-resource data remains unavailable outside the confidential intranet.

The work improves how the current scripts diagnose observed-history and production-scale readiness gaps, so future intranet onboarding can fail clearly, safely, and actionably. It must not upgrade any production-accuracy claim, fabricate production evidence, or change simulator/planner behavior.

## Non-Goals

- No production-readiness claim without real non-synthetic observed history.
- No synthetic data marked as production usable.
- No change to TWM dynamics, counterfactual rollout, causal calibration, planner ranking, or claim-ladder semantics.
- No large decomposition of `data_agent/territory_world_model/service.py`.
- No new UI surface unless existing reports expose enough stable output first.

## Current Context

The current handoff names real or sanitized observed history as the primary next step, but local discovery found only:

- `docs/reports/twm_production_observed_history_template.csv`
- `docs/reports/twm_structural_validation_observed_history.csv`
- `docs/reports/twm_production_scale_profile_template.json`

The existing runner already wires:

- `scripts/validate_twm_data_foundation.py`
- `scripts/run_twm_validation_bundle.py`
- `scripts/run_twm_production_onboarding.py`
- `data_agent/territory_world_model/deployment_punch_list.py`

The gap is not another synthetic benchmark. The useful offline task is to make production preflight diagnostics strict, explainable, and covered by edge-case tests.

## Approach

Implement a focused hardening pass across three surfaces.

1. **Observed-history schema diagnostics**
   - Preserve the existing field-group audit contract.
   - Add clearer per-gate summaries for identity, treatment/status, outcome, production flags, spatial support, covariates, treated/control balance, policy/action-mask fields, temporal split, and policy-version coverage.
   - Include remediation text that names acceptable fields or flags without requiring confidential data.

2. **Production scale profile readiness**
   - Keep the scale-profile input sanitized and metadata-only.
   - Strengthen diagnostics around layer counts, feature/raster scale, storage backend, partitioning, spatial index, temporal partitioning, and distributed compute readiness.
   - Keep status conservative: missing or partial profiles remain `review` unless strict production readiness is requested, in which case they block.

3. **Onboarding summary and punch list**
   - Make `twm_production_onboarding_summary.{json,md}` easier to hand to a data owner.
   - Group missing gates by phase: observed history, policy alignment, production scale, validation ladder, claim ladder, human review, spatial causal evidence.
   - Preserve the existing claim boundary that onboarding only checks ingestion and validation wiring.

## Expected Outputs

The implementation should update or add tests around these files:

- `data_agent/test_twm_production_onboarding.py`
- `data_agent/test_twm_data_foundation_validation.py`
- `data_agent/test_twm_validation_bundle_smoke_script.py`

The implementation may update these runtime files if needed:

- `scripts/validate_twm_data_foundation.py`
- `scripts/run_twm_validation_bundle.py`
- `scripts/run_twm_production_onboarding.py`
- `data_agent/territory_world_model/deployment_punch_list.py`

No core TWM model file should be edited unless a diagnostic currently cannot be produced from the script layer.

## Acceptance Criteria

- Missing production data still produces `review` or `blocked` status, never `pass`.
- A normalized but incomplete observed-history CSV reports exactly which field groups or production-quality checks failed.
- Synthetic or `not_for_production=true` rows cannot satisfy production candidate gates.
- A missing scale profile stays visible in both validation-bundle and onboarding punch lists.
- Strict readiness mode still exits non-zero only after writing summary artifacts.
- Markdown summaries contain enough remediation detail for a data owner to prepare a compliant sanitized file.
- Existing targeted onboarding and data-foundation tests pass.

## Testing Plan

Run focused tests first:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_production_onboarding.py \
  data_agent/test_twm_data_foundation_validation.py \
  data_agent/test_twm_validation_bundle_smoke_script.py
```

Run the onboarding smoke path with generated local fixtures:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python scripts/run_twm_production_onboarding.py \
  --raw-production-observed-history /private/tmp/twm_onboarding/raw_approval_export.csv \
  --normalized-production-observed-history-output /private/tmp/twm_onboarding/normalized.csv \
  --output-dir /private/tmp/twm_onboarding
```

The smoke command uses a local test fixture generated by the implementation tests. It is only for local fixture validation and must not be represented as production evidence.

## Risk Controls

- Keep every production claim boundary explicit in JSON and Markdown outputs.
- Prefer additive report fields so existing consumers remain compatible.
- Use negative tests for synthetic rows, missing production flags, missing holdout split, missing spatial support, and missing scale profile.
- Avoid editing `service.py`; if unavoidable, isolate the edit to a pure diagnostics helper and add a focused regression test.

## Deferred Work

- Real intranet production onboarding with authoritative observed history.
- Large `service.py` decomposition.
- TWM model registry and rollback chain.
- Mature policy-rule DSL with spatial and temporal expressions.
- Full FLUS ANN suitability workflow reproduction.

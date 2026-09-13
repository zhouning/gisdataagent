# UWM Next Window Handoff - 2026-07-09

## Branch

- Current branch: `feat/v12-extensible-platform`
- Remote: `origin git@github.com:zhouning/gisdataagent.git`

## Current UWM State

UWM livability analysis has moved beyond a final-action-only demonstration. The current implementation binds spatial causal question contracts at two levels:

1. Full-admin feasible action space:
   - graph nodes: 1017
   - graph edges: 7932
   - feasible actions: 1137
   - action counts:
     - `increase_green_infrastructure`: 81
     - `traffic_emission_control`: 77
     - `add_community_service`: 979
   - actions with spatial causal contracts: 1137
   - missing causal contracts: 0
   - underidentified observed-policy-effect actions: 1137
   - policy-outcome-claim-allowed actions: 0

2. Full-admin final decision package:
   - final recommended actions with spatial causal contracts: 6
   - missing causal contracts: 0
   - underidentified observed-policy-effect actions: 6
   - policy-outcome-claim-allowed actions: 0

## Claim Boundary

The current implementation supports bounded same-scene world-model evidence and action-level spatial causal question contracts. It still does not claim observed policy-outcome superiority or production policy-effect identification.

The blocking authoritative tables remain:

- `policy_project_history`
- `action_constraint_cost_model`
- `observed_outcome_validation_panel`
- `causal_effect_calibration_panel`
- `human_governance_review_log`

## Key Artifacts

Committed or force-added UWM evidence artifacts:

- `data/uwm_public_proxy/chongqing_central/spatial_causal_question_registry_2026_07_09/`
- `data/uwm_public_proxy/chongqing_central/full_admin_action_inventory_2026_07_08/`
- `data/uwm_public_proxy/chongqing_central/full_admin_livability_decision_package_2026_07_08/`
- `data/uwm_public_proxy/chongqing_central/data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json`

If regeneration is needed:

```bash
uv run python scripts/build_uwm_spatial_causal_question_registry.py
uv run python scripts/build_uwm_full_admin_action_inventory.py
uv run python scripts/build_uwm_full_admin_livability_decision_package.py
uv run python scripts/build_uwm_data_foundation_evidence_gate.py
```

## Verification

Fresh verification before handoff:

```bash
uv run pytest data_agent/test_uwm_*.py
# 257 passed

cd frontend && npm run build
# passed
```

Frontend build still reports the existing loaders.gl browser external `spawn` warning and large chunk warnings, but exits with code 0.

## Recommended Next Work

1. Propagate action-level causal contracts from `full_admin_action_inventory` into planner search traces and evaluated sequence candidates.
2. Add governance-cost placeholder interfaces that read only from authoritative `action_constraint_cost_model` when available, keeping planner governance binding blocked while tables are absent.
3. Start an authoritative-data adapter dry run with empty/invalid rows to prove the adapter rejects template, synthetic, and unsupported production values.
4. Add a compact frontend drilldown for action type distribution and causal-contract coverage across all 1137 feasible actions.

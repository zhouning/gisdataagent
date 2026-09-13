# UWM Full-Admin World-Model Superiority Dossier Design

Date: 2026-07-09

## Objective

Build a machine-checkable full-admin UWM superiority dossier that proves the
current urban livability world-model system is stronger than traditional static
methods within the real prepared Chongqing full-admin scene, while preserving
strict claim boundaries.

The dossier must aggregate evidence across the complete world-model stack:

```text
renderer -> full-admin Graph-MDP state -> simulator / learned dynamics
-> planner / trained value policy -> endpoint evaluator -> evidence gate
```

It must not upgrade bounded same-scene evidence into observed policy-outcome
superiority. The current production governance gate reports no accepted
authoritative intervention rows and five missing authoritative governance
tables, so observed policy-effect claims remain forbidden.

## Current Context

The repository already contains real full-admin UWM artifacts under
`data/uwm_public_proxy/chongqing_central`. The important verified counts are:

- 1017 full-admin graph nodes;
- 7932 graph edges;
- 2847 admin-boundary edges;
- 5085 geographic-similarity edges;
- 1137 feasible planner actions;
- 6817 simulator replay transitions;
- 1,194,351 local POI points;
- 50,366 local road features;
- 0 full-admin service-surface missing admin units.

The current stack includes:

- full-admin service accessibility surface and quality audit;
- geographic similarity kernel with rotated-target negative control;
- full-admin model-based graph-search planner replay;
- full-admin GraphDQN training report;
- full-admin learned world-model rollout;
- full-admin energy-regularized planner;
- full-admin livability decision package;
- spatial causal question registry;
- production governance planner binding gate;
- final livability endpoint suite and endpoint-aligned planner evaluator.

The gap is that these components are verified in separate tests and separate
reports. The system-level superiority claim can be read from the data
foundation evidence gate, but there is no single artifact that records the
complete evidence chain, exact full-data coverage, baseline families, causal
binding coverage, governance blockers, and forbidden claims in one auditable
object.

## Scope

In scope:

- Add a `full_admin_world_model_superiority_dossier` module.
- Add a builder script that reads existing real full-admin artifacts.
- Emit a JSON dossier artifact under the existing UWM data root.
- Add tests that require full-data counts and fail if smoke-sized data is used.
- Require planner-level causal binding coverage for all 1137 feasible actions.
- Require final-output causal binding for all recommended actions.
- Require endpoint-suite superiority over best traditional baselines.
- Require positive same-scene world-model advantages across planner, risk
  adjustment, GraphDQN, learned rollout, and energy-regularized planner.
- Require governance and claim-boundary fields that forbid observed policy
  outcome superiority.
- Surface remaining gates needed for true observed policy superiority.

Out of scope:

- No fabricated policy outcome data.
- No synthetic intervention logs.
- No claim that current outputs are empirical policy-outcome superiority.
- No frontend changes.
- No new planner algorithm in this slice.
- No network download requirement; use the prepared local full-admin artifacts.

## Claim Contract

The dossier may support this claim when every gate passes:

```text
bounded_full_admin_world_model_advantage_over_traditional_methods
```

The claim means:

- same real prepared full-admin scene;
- full renderer / simulator / planner / endpoint evidence chain;
- world-model methods beat traditional static baselines on required bounded
  metrics;
- all current action claims remain underidentified for observed policy effect;
- no observed policy outcome or empirical policy superiority is claimed.

The dossier must always expose:

```text
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

It must also include forbidden claims:

- `observed_policy_outcome_superiority`;
- `empirical_policy_superiority`;
- `causal_effect_identification_from_current_proxy_scene`;
- `authoritative_governance_deployment_readiness`.

## Architecture

### New Module

Create:

```text
data_agent/uwm/full_admin_world_model_superiority_dossier.py
```

The module exports:

```python
UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA
build_uwm_full_admin_world_model_superiority_dossier(...)
validate_uwm_full_admin_world_model_superiority_dossier(dossier)
```

The builder receives already-loaded artifact dictionaries and returns a
deterministic JSON-serializable dictionary.

### Builder Script

Create:

```text
scripts/build_uwm_full_admin_world_model_superiority_dossier.py
```

The script reads the prepared local artifacts and writes:

```text
data/uwm_public_proxy/chongqing_central/full_admin_world_model_superiority_dossier_2026_07_09/uwm_full_admin_world_model_superiority_dossier.json
data/uwm_public_proxy/chongqing_central/full_admin_world_model_superiority_dossier_2026_07_09/snapshot_manifest.json
```

The generated JSON artifact is ignored by git through the repository's
existing `/data/` ignore rule. Tests should be able to regenerate it.

### Dossier Sections

The dossier must contain these top-level sections:

```text
schema
dossier_id
created_at
experiment_scope
full_admin_scope_guard
traditional_baseline_matrix
world_model_system_matrix
endpoint_superiority_matrix
causal_and_governance_gate
claim_ladder
supported_claim
claim_boundary
forbidden_claims
remaining_gates
audit_trace
observed_policy_outcome_superiority_claim
empirical_superiority_claim
```

### Full-Admin Scope Guard

`full_admin_scope_guard.passed` is true only if the dossier can verify:

- graph node count is 1017;
- graph edge count is 7932;
- admin-boundary edge count is 2847;
- geographic-similarity edge count is 5085;
- available action count is 1137;
- transition count is 6817;
- service surface admin-unit count is 1017;
- local POI point count is 1,194,351;
- local road count is 50,366;
- service missing admin count is 0.

### Traditional Baseline Matrix

The matrix records the traditional comparison families already present in the
artifacts:

- final endpoint traditional baselines from `livability_endpoint_suite`;
- same-scene static heuristic baseline from the full-admin planner replay;
- traditional static baseline from the full-admin GraphDQN training report;
- static and one-step baselines from the learned world-model rollout;
- traditional static baseline from the full-admin energy-regularized planner.

The matrix must be descriptive and auditable. It must not invent a new
traditional method that was not evaluated.

### World-Model System Matrix

This matrix records each world-model component and whether it contributes
positive bounded advantage:

- full-admin model-based planner replay;
- risk-adjusted planner replay;
- full-admin GraphDQN value/policy training;
- full-admin learned world-model rollout vs static baseline;
- full-admin learned world-model rollout vs one-step policy;
- full-admin energy-regularized planner;
- full-admin final decision package;
- final endpoint suite.

The dossier is ready only if all required advantages are positive and the
source reports remain claim-safe.

### Endpoint Superiority Matrix

The endpoint matrix is built from `livability_endpoint_suite` and must require:

- at least three endpoints;
- every endpoint beats its best traditional baseline;
- mean and minimum relative MAE reductions are positive;
- all endpoint records have `policy_outcome_claim = false`.

### Causal And Governance Gate

This section combines:

- planner report `spatial_causal_contract_binding`;
- final decision package `spatial_causal_contract_binding`;
- spatial causal registry validation;
- production governance planner binding gate.

Readiness requires:

- planner candidate binding ready;
- planner feasible action count is 1137;
- planner attached action count is 1137;
- planner missing contract action count is 0;
- planner policy-outcome-claim-allowed action count is 0;
- final decision package binding ready;
- final recommended actions are causally bound;
- production governance gate is present and audited.

Production deployment readiness is false while authoritative governance data
closure is false.

### Claim Ladder

The claim ladder must include:

```text
bounded_full_admin_world_model_advantage_over_traditional_methods
```

with:

```text
claim_level = bounded_support
policy_outcome_claim = false
allowed_in_report = true
```

when all gates pass.

If any required gate fails, the dossier must emit:

```text
supported_claim = no_full_admin_world_model_superiority_claim_supported
claim_boundary.max_claim_level = not_for_claim
```

and include explicit failing gates in `remaining_gates`.

## Testing Strategy

Use test-first implementation.

Add:

```text
data_agent/test_uwm_full_admin_world_model_superiority_dossier.py
```

The tests must assert:

1. A generated dossier from real local artifacts has schema
   `uwm.full_admin_world_model_superiority_dossier.v1`.
2. `experiment_scope` is `full_admin_graph`.
3. The full-admin guard passes with the exact counts listed above.
4. The endpoint matrix contains all endpoint-suite endpoints and every endpoint
   beats the best traditional baseline.
5. The world-model matrix reports positive advantages for all required
   components.
6. Planner causal binding covers all 1137 candidate actions and allows zero
   policy-outcome claims.
7. Governance evidence blocks production deployment readiness while preserving
   the bounded system claim.
8. `supported_claim` is
   `bounded_full_admin_world_model_advantage_over_traditional_methods`.
9. Forbidden claims include observed policy outcome and empirical policy
   superiority.
10. Removing or corrupting a required full-admin count downgrades the dossier
    to `not_for_claim`.
11. The stored artifact is full scope and claim-safe after regeneration.

Verification command:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_full_admin_world_model_superiority_dossier.py -q
/Users/zhouning/gisdataagent/.venv/bin/python scripts/build_uwm_full_admin_world_model_superiority_dossier.py
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_*.py -q
```

When running the builder from a linked worktree, use `PYTHONPATH=.` so imports
come from the worktree source instead of the main checkout package.

## Failure Handling

The builder should not crash for ordinary evidence-gate failures. It should
return a dossier with `not_for_claim`, precise `remaining_gates`, and an audit
trace showing which artifact or count failed.

It may raise only for malformed inputs that cannot be represented as a dossier,
such as a non-dictionary source artifact where a dictionary is required.

## Acceptance Criteria

The implementation is acceptable only if:

- the focused dossier tests pass;
- the full UWM test suite passes;
- no smoke-sized or synthetic-only path can satisfy the dossier readiness gate;
- the generated artifact references real full-admin source paths;
- observed policy outcome superiority remains forbidden;
- all new production code has tests that failed before implementation.

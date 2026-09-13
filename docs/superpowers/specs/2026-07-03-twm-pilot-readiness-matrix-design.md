# TWM Pilot Readiness Matrix v1 Design

## Goal

Add a strict, machine-readable pilot readiness matrix for TWM that works without
authoritative production data while refusing to upgrade production, predictive,
causal or planning claims beyond review-only status.

## Problem

TWM currently has many evidence surfaces: data foundation assessment, roadmap
status, baseline evidence, validation ladder, dynamics readiness, planner
reports and production onboarding. They are useful but fragmented. When real
natural-resources data is unavailable, the project needs one concise report that
answers:

- what can be demonstrated with current data;
- what is only scaffold or review evidence;
- what is blocked until authoritative data arrives;
- which test data fixtures should be improved next.

## Design

Create `pilot_readiness_matrix_report()` on `TerritoryWorldModelService`.
The report will aggregate existing service facts only; it will not invent new
metrics or relax gates.

The report schema is:

```text
territory_world_model.pilot_readiness_matrix.v1
```

It contains six dimensions:

1. `data_foundation`
2. `policy_rules`
3. `simulator`
4. `planner`
5. `evidence_audit`
6. `production_gate`

Each dimension has:

- `status`: `pass`, `review` or `blocked`
- `score`: numeric readiness proxy from 0.0 to 1.0
- `evidence`: concrete current evidence
- `missing`: required missing evidence or fixtures
- `test_data_work`: focused test data improvements to make next

The aggregate status follows the strictest status:

- any `blocked` dimension -> report `blocked`
- otherwise any `review` dimension -> report `review`
- otherwise -> `pass`

Production gate must be blocked whenever production-ready observed history rows
or production policy-history rows are zero.

## API and Tooling

Expose the report through:

- `GET /api/twm/pilot-readiness-matrix`
- ADK tool `twm_pilot_readiness_matrix`

The endpoint and tool return the same JSON shape as the service method.

## Test Data Policy

Current demo and synthetic data remain useful, but only for structural and
regression checks. The readiness matrix must explicitly recommend fixture
improvements when production data is absent:

- add non-synthetic observed-history fixture template rows only when provided by
  an authorized source;
- improve synthetic fixtures for boundary cases, false allow/false block and
  same-case baseline format checks;
- keep synthetic rows marked `synthetic=true` and `not_for_production=true`;
- never let synthetic fixture completeness satisfy the production gate.

## Acceptance Criteria

- The service report returns six named dimensions.
- With the current repository data, aggregate status is `blocked`.
- Production gate reports zero production observed-history rows and zero policy
  history rows as blocking evidence.
- Simulator and planner dimensions can be `review` or better only by referencing
  existing scaffold, benchmark or bundle evidence.
- Route and tool tests verify the report is exposed consistently.
- Existing roadmap status behavior remains unchanged.


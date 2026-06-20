# TWM Current Handoff

Last updated: 2026-06-20

This document is the continuation entry point for Territory World Model (TWM)
development in this repository.

## Current State

TWM has an end-to-end prototype surface in `data_agent/territory_world_model/`:

- hierarchical GIS state construction from MMFE semantic bundles
- rule/evidence/review/audit pipeline
- action-conditioned forecast with multi-head outputs
- action mask / execution gate
- counterfactual rollout
- validation ladder
- functional world-model profile aligned to Fei-Fei Li's renderer/simulator/planner taxonomy
- dynamics training dataset, readiness, backend, objective and candidate reports
- constrained beam planning consumer
- trainable dynamics candidate backends:
  - `torch_multi_head_mlp`
  - `torch_hierarchical_graph`
  - `torch_spatiotemporal_transformer`
- local causal calibration backend:
  - stratified ATT
  - IPW ATE
  - augmented IPW ATE
  - overlap diagnostics
  - covariate balance diagnostics
  - spatial interference diagnostics for neighbor exposure, spatial cluster treatment concentration and residual spatial autocorrelation

The implementation remains a rigorous scaffold/candidate implementation, not a
final production-scale territorial world model. Claim upgrade is still governed
by readiness, backend, objective, causal, GeoFM and validation gates.

## Key Files

- Core package: `data_agent/territory_world_model/`
- API routes: `data_agent/api/territory_world_model_routes.py`
- ADK toolset: `data_agent/toolsets/territory_world_model_tools.py`
- Tests: `data_agent/test_territory_world_model.py`
- Architecture and lineage: `docs/twm-lineage-and-architecture.md`
- Scale and novelty analysis: `docs/twm-scale-and-novelty-analysis.md`
- Fei-Fei taxonomy alignment: `docs/twm-feifei-functional-taxonomy-alignment.md`
- Reference basis: `docs/twm-authoritative-references.md`

## Latest Verified Tests

Run from `/Users/zhouning/gisdataagent`:

```bash
python -m compileall -q data_agent/territory_world_model data_agent/test_territory_world_model.py
```

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  /Users/zhouning/gisdataagent/.venv/bin/pytest -q data_agent/test_territory_world_model.py
```

Latest full result before this handoff:

```text
44 passed, 4 warnings in 1046.42s
```

The 4 warnings are the known ADK `BaseAgentConfig is deprecated` warnings.

## Current Roadmap Position

Completed or scaffolded:

- TWM object/relation/rule/evidence/review core
- action-conditioned forecast and multi-head outputs
- counterfactual rollout and validation ladder
- dynamics training contracts and candidate reports
- three local trainable dynamics candidates
- GeoFM B0/B1 ablation gate scaffold
- local observational causal calibration backend with spatial interference diagnostics
- constrained beam planning consumer

Still important:

- replace rule-level spatial interference diagnostics with a real spatial treatment-effect estimator inspired by papers 6 and 7
- extend GeoFM gate beyond B0/B1 into D2/D3/D4 and real cross-region downstream planning experiments
- expand training dataset builder with more historical states, approvals, reviews and remote-sensing transitions
- upgrade lightweight graph/transformer candidates to production-scale territorial graph/transformer dynamics
- deepen ArcGIS/frontend deployment loop

## Suggested Next Task

Next session should continue with:

1. Implement a first-class spatial causal estimator adapter under `data_agent/territory_world_model/`.
2. Preserve the current `causal_calibration_report` schema and evidence-gate contract.
3. Add tests that distinguish:
   - ordinary observational AIPW pass
   - poor overlap review
   - spatial interference review
   - spatial estimator pass with balanced spatial units
4. Keep all claims review-only unless the estimator has enough observed, non-synthetic, spatially valid support.

## Important Working Notes

- Do not treat GeoFM as the default main model. It must pass downstream gates.
- Planner/beam/MPC are consumers of the world model, not the world model itself.
- Do not collapse TWM state into a flat vector. Keep parcel/block/township/county token semantics.
- Keep `forecast`, `rollout`, `beam_plan`, `dynamics_backend_report`, and `training_objective_report` contract-compatible.
- The repository has unrelated local changes in other areas. Avoid staging non-TWM changes unless explicitly requested.

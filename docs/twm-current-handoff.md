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
  - observed approval/review history ingestion from payload rows or CSV path before demo state-object fallback
  - causal record inventory diagnostics for source, treatment/control, spatial cluster, neighbor, coordinate and covariate coverage
  - state-object observational record extraction from approval, rule-evaluation and review-task objects before scaffold fallback
  - overlap diagnostics
  - covariate balance diagnostics
  - spatial interference diagnostics for neighbor exposure, spatial cluster treatment concentration and residual spatial autocorrelation
  - first-class spatial causal estimator adapter with mixed spatial-unit fixed effects and treated/control neighbor matching
  - spatial block bootstrap and leave-one-spatial-unit-out holdout uncertainty diagnostics
- GeoFM ablation gate:
  - B0/B1 downstream planning lift gate
  - optional D2 explicit planning holdout validation
  - optional D3 cross-region geographic robustness validation
  - optional D4 domain-shift, temporal holdout and production-label quality validation
  - architecture-aware audit for backbone, adapter type, fused-QKV target binding, input modalities, adapter capacity, geographic split, domain shift and label quality
  - optional D2/D3/D4 auto-inference from dynamics dataset plus B0/B1 prediction maps
  - downstream experiment report that wraps B0/B1 variants, architecture audit, D2/D3/D4 evidence and the gate decision
  - deterministic B0/B1 prediction scaffold for dataset-only experiment reports, explicitly marked review-only

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

Latest full result before the current GeoFM auto-inference continuation:

```text
47 passed, 4 warnings in 1096.09s (0:18:16)
```

The 4 warnings are the known ADK `BaseAgentConfig is deprecated` warnings.

Latest targeted GeoFM regression after the downstream experiment report update:

```text
9 passed, 42 deselected in 173.82s (0:02:53)
```

Latest targeted GeoFM regression after architecture-aware audit gate:

```text
11 passed, 49 deselected in 205.26s (0:03:25)
```

Latest route-level regression covering the GeoFM route:

```text
1 passed, 51 deselected in 122.73s (0:02:02)
```

Latest targeted causal calibration regression after observed history CSV spatial-support diagnostics:

```text
14 passed, 43 deselected in 197.70s (0:03:17)
```

Latest targeted data-foundation and causal calibration regression after local dataset validation:

```text
15 passed, 44 deselected in 213.19s (0:03:33)
```

Latest targeted data-foundation script and causal calibration regression after relation-derived neighbor augmentation:

```text
2 passed, 1 warning in 0.35s
15 passed, 43 deselected in 213.88s (0:03:33)
```

Latest targeted data-foundation script and causal calibration regression after Paper7 matched validation:

```text
3 passed, 1 warning in 0.34s
15 passed, 43 deselected in 213.98s (0:03:33)
```

Latest targeted data-foundation script and causal calibration regression after Paper7 caliper-matched validation:

```text
4 passed, 1 warning in 0.35s
15 passed, 43 deselected in 214.32s (0:03:34)
```

Latest targeted data-foundation script and causal calibration regression after production observed-history preflight and string-neighbor spatial edge fix:

```text
9 passed, 1 warning in 1.47s
15 passed, 43 deselected in 214.33s (0:03:34)
```

Latest targeted data-foundation script and causal calibration regression after project rule/review evidence augmentation:

```text
12 passed, 1 warning in 1.44s
15 passed, 43 deselected in 214.04s (0:03:34)
```

Latest targeted data-foundation script and causal calibration regression after evidence-augmented local matching:

```text
15 passed, 1 warning in 1.40s
15 passed, 43 deselected in 213.48s (0:03:33)
```

Latest targeted data-foundation script and causal calibration regression after structural-validation fixture generation:

```text
17 passed, 1 warning in 1.45s
15 passed, 43 deselected in 213.49s (0:03:33)
```

Latest targeted data-foundation script and causal calibration regression after Markdown health report generation:

```text
18 passed, 1 warning in 1.49s
15 passed, 43 deselected in 212.45s (0:03:32)
```

Latest targeted data-foundation script and causal calibration regression after synthetic experiment foundation generation:

```text
20 passed, 1 warning in 1.48s
15 passed, 43 deselected in 210.58s (0:03:30)
```

Latest synthetic experiment runner regression after context action-mask fallback and planner holdout analysis:

```text
3 passed, 23 deselected in 2.47s
```

Latest full data-foundation validation regression after context action-mask fallback and planner holdout analysis:

```text
26 passed in 2.57s
```

Latest full data-foundation validation regression after multi-action oracle synthetic foundation:

```text
26 passed in 2.45s
```

Latest full data-foundation validation regression after planner rollout matrix:

```text
26 passed in 2.43s
```

Latest full data-foundation validation regression after 8-period synthetic tail and graph/transformer action-mask calibration:

```text
27 passed in 3.05s
```

Latest data-foundation validation regression after context action-mask overblocking fix and transformer constraint-risk calibration:

```text
29 passed in 3.76s
```

Latest toolset regression:

```text
1 passed, 50 deselected, 4 warnings in 0.91s
```

## Current Roadmap Position

Completed or scaffolded:

- TWM object/relation/rule/evidence/review core
- action-conditioned forecast and multi-head outputs
- counterfactual rollout and validation ladder
- dynamics training contracts and candidate reports
- three local trainable dynamics candidates
- GeoFM B0/B1 ablation gate scaffold
- GeoFM optional D2/D3/D4 extended validation contract
- GeoFM D2/D3/D4 candidate-evidence auto-inference from holdout prediction comparisons
- GeoFM architecture-aware audit scaffold for paper 12 risks: backbone, adapter, fused-QKV binding, input modalities, capacity, geographic split, domain shift and label quality
- GeoFM downstream experiment report exposed through service, API route and ADK toolset
- GeoFM dataset-only downstream experiment scaffold that auto-generates B0/B1 prediction maps but keeps the report review-only
- local observational causal calibration backend with spatial interference diagnostics and spatial estimator adapter
- observed approval/review history causal ingestion from payload rows or CSV path, preserving provenance and non-demo evidence gates
- causal record inventory diagnostics for observed-history spatial support and source coverage
- state-object causal observation extraction before dynamics scaffold fallback, preserving synthetic/not-for-production review gates
- generated multi-region, multi-period synthetic experiment foundation for simulator training, holdout validation and planner-consumer rollout tests
- synthetic backend comparison with action-mask diagnostics and planner-consumer holdout regret by region, period and action type
- context action-mask calibration over `action_type+risk_bucket+mask_policy`, with current MLP, graph and transformer context variants reaching false_allow `0` and false_block `0` on the 256-row synthetic foundation
- candidate-split transformer constraint-risk calibration with stability gates for low prediction variance and degenerate calibration slope
- transformer context-residual constraint-risk head that reads action/context/temporal token embeddings before post-hoc calibration
- 13-candidate graph/transformer comparison, currently selecting `torch_spatiotemporal_transformer_constraint_risk_context_action_mask_calibrated`
- constrained beam planning consumer

Still important:

- replace the remaining post-hoc transformer affine risk calibration with learned risk-head calibration while preserving the current improvement in pre-calibration MAE
- turn post-hoc context action-mask calibration into a learned context-sensitive feasibility head while preserving the current zero false_allow / zero false_block regression target
- add harder context-generalization stress cases where high-risk actions can be allowed with conditions, not only blocked
- upgrade lightweight graph/transformer candidates to production-scale territorial graph/transformer dynamics with true relation-aware message passing
- deepen ArcGIS/frontend deployment loop

## Suggested Next Task

Previous session implemented:

1. A first-class spatial causal estimator adapter under `data_agent/territory_world_model/spatial_causal_estimator.py`.
2. Preservation of the current `causal_calibration_report` schema and evidence-gate contract, with `estimate.spatial_estimator` added as an internal estimate subreport.
3. Tests that distinguish:
   - ordinary observational AIPW pass
   - poor overlap review
   - spatial interference review
   - spatial estimator pass with balanced spatial units
4. Conservative claim gating: claims remain review-only unless records, overlap, balance, spatial diagnostics and model-effect calibration pass.

This session implemented:

1. A nested `evidence.extended_validation` contract inside `territory_world_model.geofm_ablation_gate.v1`, preserving the public schema version.
2. Optional D2/D3/D4 GeoFM checks:
   - D2: explicit downstream planning holdout lift/ranking/risk deltas
   - D3: cross-region geographic robustness
   - D4: domain shift, temporal holdout confidence and production label quality
3. Conservative promotion logic: B0/B1 behavior remains unchanged unless `thresholds.require_extended_validation` is true; when required, GeoFM is retained only if D2/D3/D4 pass.
4. Tests proving both retain and gate-out paths for required extended validation.

Current continuation implemented:

1. Auto-inference of GeoFM D2/D3/D4 candidate evidence from a dynamics dataset plus B0/B1 prediction maps.
2. D2 auto evidence from holdout prediction comparisons.
3. D3 auto evidence from holdout prediction comparisons grouped by region/provenance.
4. D4 auto evidence from holdout domain-shift proxy, regret/error proxy, temporal holdout confidence and production-label quality.
5. Conservative behavior preserved: inferred evidence can still block promotion, especially when holdout labels are synthetic, review-only or not-for-production.

Latest continuation implemented:

1. `territory_world_model.geofm_downstream_experiment_report.v1`.
2. Service method, API route and ADK toolset function for the experiment report.
3. Report structure that separates:
   - B0/B1 variant metrics and deltas
   - D2/D3/D4 evidence
   - final `geofm_ablation_gate` decision
   - renderer/simulator/planner boundary notes
4. Tests for service-level experiment report, API route, and toolset exposure.

Current continuation implemented:

1. Dataset-only GeoFM downstream experiment scaffold: if a dynamics dataset is present but B0/B1 prediction maps are missing, the report creates transparent deterministic B0/B1 prediction maps.
2. `evidence.prediction_evidence` now records whether prediction maps are explicit or scaffold-generated.
3. Scaffold-generated prediction maps can populate D2/D3/D4 evidence, but the experiment report remains `review` even if the internal gate would pass. This prevents treating GeoFM as a default core TWM component without explicit downstream predictions.
4. Added regression coverage for the review-only scaffold boundary.

Latest continuation implemented:

1. Causal calibration now tries state-object observations before falling back to `dynamics_training_examples_scaffold`.
2. State-object observations are derived from `approval_record` objects and enriched with project-linked `rule_evaluation`, persisted rule-hit and `review_task` evidence.
3. Each derived causal record preserves provenance fields such as `source_object_id`, `source_role`, `source_path`, supporting rule/review ids, treatment source and outcome source.
4. Demo/synthetic/not-for-production state evidence remains review-only by default: the report can expose `record_source=state_object_observations` and `raw_record_count=60`, while `usable_record_count=0` unless thresholds explicitly allow those flags.
5. Added regression coverage for both state-object observation precedence and empty-state scaffold fallback.

Latest continuation implemented:

1. Causal calibration now accepts observed approval/review history before demo state-object extraction via `observed_history`, `approval_review_history`, `approval_history` and matching `*_path` CSV payload keys.
2. Observed history rows are converted into causal records with provenance fields including `source_path`, `source_row_index`, `source_record_id`, `project_id`, `approval_id`, treatment source and outcome source.
3. Treatment can come from explicit treatment flags, approval status, or approved area; outcome can come from explicit utility/ranking fields or a transparent approval-area/risk/review proxy.
4. Non-synthetic, production-usable observed histories can now pass the causal gate without being blocked by the demo state bundle's synthetic/not-for-production flags.
5. Added regression coverage for both payload-row and CSV-path observed history ingestion.

Latest continuation implemented:

1. `causal_calibration_report.provenance.record_inventory` now summarizes record source paths, treatment/control counts, outcome/model-effect coverage, synthetic/not-for-production counts, strata, clusters, neighbor links, coordinates and covariate keys.
2. Observed approval/review histories with spatial clusters, neighbor links and coordinates can now be verified as sufficient support for the `spatial_fixed_effect_neighbor_adapter`.
3. Added regression coverage proving observed history records can drive the spatial causal estimator, not only the non-spatial AIPW path.

Current continuation implemented:

1. Tightened `record_inventory.spatial_support.spatial_record_count` so spatial support now means a cluster id, neighbor link, or complete x/y coordinate pair; partial coordinates no longer inflate spatial diagnostics.
2. Added CSV-path observed approval/review spatial-support coverage, including string neighbor parsing and x/y coordinate ingestion from local exports.
3. Added a direct inventory regression proving x-only or y-only records do not count as coordinate-backed spatial support.
4. Verified the causal calibration target suite after the change: `14 passed, 43 deselected in 197.70s`.

Current data-validation continuation implemented:

1. Added `scripts/validate_twm_data_foundation.py`, a reproducible local validation entry point that audits TWM tables and runs TWM `causal_calibration_report` against both local approval/review data and the Paper7 empirical causal dataset.
2. Generated `docs/reports/twm_data_foundation_validation.json`.
3. Validation result for `data_agent/test_data/twm_bishan_multi_admin_eval`:
   - `approval_records.csv`: 90 rows
   - `review_tasks.csv`: 114 rows
   - `rule_evaluation.csv`: 360 rows
   - `state_snapshots.csv`: 10 rows
   - production-ready observed approval rows: 0
   - all approval/review/rule rows remain `synthetic=True` and `not_for_production=True`, so the causal gate correctly stays `review`
4. Observed approval history now maps administrative codes such as `DKXZQDM` / `XZQDM` into causal `cluster`, improving spatial inventory diagnostics without relaxing evidence gates.
5. Paper7 empirical causal dataset validation:
   - 12,000 causal records mapped into TWM records
   - treated/control counts: 9,326 / 2,674
   - observed TWM AIPW effect: `0.024249`
   - calibration factor against Paper7 predicted ATT: `0.1`
   - gate remains `review` due to `covariate_balance` and `spatial_estimator`, which is the intended conservative behavior
6. Relation-derived spatial support augmentation:
   - `project_parcel_rel.csv` is now audited as a project-level spatial relation source.
   - Shared parcel overlaps produce project neighbor links for validation diagnostics.
   - Current local dataset yields 79 project neighbor edges and 73 approval rows with neighbor links.
   - The relation-augmented observed-history gate remains `review` because all rows are still synthetic/not-for-production; neighbor enrichment improves diagnostics but does not upgrade claims.
7. Paper7 matched causal validation:
   - Greedy one-to-one standardized nearest-neighbor matching now builds a deterministic validation subset without relaxing TWM thresholds.
   - Matched records: 5,348, with treated/control counts 2,674 / 2,674.
   - Matched observed effect: `0.108151`.
   - Matched calibration factor against Paper7 predicted ATT: `0.408608`.
   - Matching removes the `spatial_estimator` gate miss, but `covariate_balance` still blocks upgrade, so the final status remains `review`.
8. Paper7 caliper-matched causal validation:
   - Default caliper is standardized matching distance `2.0`.
   - Caliper-matched pairs: 2,445, records: 4,890.
   - Caliper-matched observed effect: `0.048491`.
   - Caliper-matched calibration factor against Paper7 predicted ATT: `0.183205`.
   - The caliper-matched Paper7 branch passes the current TWM causal gate without relaxing thresholds; this validates the data-quality path while the overall data-foundation summary remains `review` because local TWM approval/review rows are still synthetic/not-for-production.
9. Added tests for Paper7 mapping, Paper7 matching, caliper matching, observed-history admin-code cluster mapping, and shared-parcel neighbor augmentation.
10. Verified targeted data-foundation script tests and causal regression: `4 passed, 1 warning`; `15 passed, 43 deselected in 214.32s`.
11. Fixed a validation-chain bug where relation-derived string neighbors reached record inventory but did not become backend spatial neighbor edges. `causal_calibration.py` now parses list and delimited string neighbor ids before building the spatial attributes used by the estimator.
12. Added production observed-history schema preflight to `scripts/validate_twm_data_foundation.py`:
   - required field groups: unit identity, treatment, observed outcome/proxy, `synthetic`/`not_for_production` flags, spatial support and numeric covariates
   - optional `--production-observed-history` can audit a real non-synthetic approval/review export before running causal calibration
   - generated template: `docs/reports/twm_production_observed_history_template.csv`
13. Regenerated `docs/reports/twm_data_foundation_validation.json` with:
   - `production_observed_history_contract`
   - `twm_observed_history_schema_audit`
   - `production_observed_history_schema_audit`
   - `twm_spatial_relation_augmented_structural_check`
14. Current regenerated summary:
   - local TWM observed-history schema status: `review`
   - local production candidate rows: `0`
   - missing local schema data gates: `production_usable_rows`, `production_treated_rows`, `production_control_rows`
   - relation-derived backend spatial neighbor edges now register as `79`
   - relation structural check remains `review`, so the link plumbing is validated but the synthetic local records still do not justify production causal claims
   - Paper7 caliper-matched validation still passes: `2445` pairs, observed effect `0.048491`, calibration factor `0.183205`
15. Added project rule/review evidence augmentation to the data-foundation validation script:
   - `rule_evaluation.csv` is summarized by `project_id` into rule counts, hit counts, severity-derived `risk_score` and high/critical hit counts.
   - `review_tasks.csv` is summarized by `project_id` into task counts, open/completed counts, supplement-required counts, confirmed-violation counts and `review_penalty`.
   - `project_parcel_rel.csv` shared-parcel graph is converted into `shared_parcel_component_*` spatial clusters so the spatial estimator can test mixed project components rather than only the single admin-code cluster.
16. Regenerated `docs/reports/twm_data_foundation_validation.json` with:
   - `twm_dataset_audit.project_review_context`
   - `twm_evidence_augmented_gate`
   - `twm_evidence_augmented_structural_check`
17. Current evidence-augmented validation on `twm_bishan_multi_admin_eval`:
   - project review context covers 90 projects, 360 rule-evaluation rows and 114 review-task rows.
   - 68 projects have review-task context; 11 projects have confirmed-violation review results.
   - evidence-augmented rows with review context: 90 / 90.
   - shared-parcel component clusters: 24; mixed treated/control component clusters: 5.
   - structural check remains `review` with missing `covariate_balance`, `spatial_interference`, and `spatial_estimator`; this is the intended conservative result because the demo fixture has concentrated treatment/risk patterns.
   - default evidence-augmented gate remains blocked by `synthetic_records` and `not_for_production_records`.
18. Added local TWM evidence-augmented matching validation:
   - `match_twm_evidence_augmented_records` builds deterministic one-to-one treated/control pairs from evidence-augmented approval rows.
   - Matching covariates include area, risk score, review penalty, rule counts, review counts and confirmed-violation counts.
   - The matcher prioritizes same `shared_parcel_component_*` pairs, then same stratum, then global fallback; it preserves `cluster`, `neighbors`, `synthetic` and `not_for_production` fields.
   - Added default and structural-check report branches: `twm_evidence_augmented_matched_gate` and `twm_evidence_augmented_matched_structural_check`.
19. Regenerated `docs/reports/twm_data_foundation_validation.json` after local evidence matching:
   - matched pairs: 33, matched rows: 66.
   - same shared-parcel component pairs: 7.
   - mean standardized matching distance: `4.399582`.
   - matched structural neighbor edges: 59.
   - matched structural max covariate SMD: `1.761542`.
   - matched structural status remains `review`, missing `covariate_balance`, `spatial_interference` and `spatial_estimator`.
   - default matched gate remains blocked by `synthetic_records` and `not_for_production_records`.
20. Current data-foundation interpretation:
   - Existing local data is useful for renderer/plumbing validation and simulator calibration diagnostics.
   - The default evidence gate correctly stays conservative for synthetic/not-for-production rows.
   - Development should proceed through generated, labeled synthetic experiment foundations plus structural checks, rather than threshold tuning.
21. Added a generated structural-validation observed-history fixture:
   - Output: `docs/reports/twm_structural_validation_observed_history.csv`.
   - Default pair count: 24 treated/control pairs, 48 rows.
   - All rows are explicitly `synthetic=True`, `not_for_production=True`, `data_role=synthetic_structural_validation`.
   - Rows include balanced treatment/control, paired neighbor links, component clusters, coordinates, area, risk, rule/review covariates, propensity score and evidence weight.
   - Purpose: simulator causal/spatial plumbing regression, not deployment evidence.
22. Regenerated `docs/reports/twm_data_foundation_validation.json` with structural fixture diagnostics:
   - structural fixture default gate: `review`, missing `synthetic_records` and `not_for_production_records` among other default usable-record checks.
   - structural fixture structural check: `pass`.
   - structural check neighbor edges: 24.
   - structural check spatial estimator status: `pass`.
   - structural check max covariate SMD: `0.0`.
   - This proves the local TWM simulator calibration chain can pass on a controlled, balanced, spatially supported fixture while default claim gates remain conservative.
23. Added a human-readable data foundation health report:
   - Output: `docs/reports/twm_data_foundation_health.md`.
   - The report summarizes renderer/simulator/planner data scope, current table counts, structural fixture status, synthetic experiment status, gate summary, claim boundaries and next data work.
   - The JSON report remains the machine-readable source of truth; the Markdown report is for review, handoff and quick preview.
24. Added a generated synthetic experiment foundation:
   - Output: `docs/reports/twm_synthetic_experiment_foundation.csv`.
   - Default generation: 4 regions, 6 periods, 4 components per region-period, 96 counterfactual pairs and 192 rows.
   - Split counts: train 128, validation 32, test 32.
   - Rows include region code, period, time index, scenario id, split, action type, counterfactual group, treatment effect, baseline/next state score, constraint-risk delta, planning-utility delta and uncertainty.
   - All rows are explicitly `synthetic=True`, `not_for_production=True`, `data_role=synthetic_experiment_foundation`.
25. Regenerated reports with synthetic experiment diagnostics:
   - Synthetic experiment default gate: `review`, preserving conservative claim gating.
   - Synthetic experiment structural check: `pass`.
   - Synthetic experiment structural neighbor edges: 96.
   - Synthetic experiment spatial estimator status: `pass`.
   - Synthetic experiment max covariate SMD: `0.0`.
26. Added tests for synthetic experiment generation, split coverage, default gate behavior, structural check behavior and Markdown rendering.
27. Added a synthetic TWM experiment runner:
   - Script: `scripts/run_twm_synthetic_experiment.py`.
   - Output: `docs/reports/twm_synthetic_experiment_runner_report.json`.
   - The runner converts `twm_synthetic_experiment_foundation.csv` into `territory_world_model.dynamics_training_dataset.v1`.
   - It maps `train` to `candidate` and `validation`/`test` to `holdout`.
   - It preserves `synthetic=True`, `not_for_production=True`, `data_role=synthetic_experiment_foundation` and `claim_boundary=synthetic_experiment_only_not_for_production`.
   - It creates a lightweight hierarchical GIS state with county/township/block/parcel/project objects plus rule/evidence/review context so state-contract and backend gates can run.
28. Current runner result on the generated 192-row synthetic experiment foundation:
   - dynamics examples: 96 treated action-conditioned examples.
   - split counts: candidate 64, holdout 32.
   - action counts: protect 24, restore 24, approve_with_conditions 24, defer_review 24.
   - state objects: 397; state relations: 584.
   - readiness: `pass`.
   - fit: `pass`; fitted baseline predictions: 96.
   - evaluation: `pass`; mean transition error `0.01462`, mean constraint error `0.041667`, mean utility error `0.00555`, action-mask accuracy `1.0`.
   - backend adapter: `pass`.
   - training objective: `pass`; calibration coverage 96.
   - planner beam plan: `pass`; selected action is `protect`; `defer_review` stays review-required through action-mask gating.
   - counterfactual rollout: `pass`; dynamics candidate applied through rollout prediction aliases.
29. Added regression coverage for the runner:
   - CSV-to-dynamics conversion contract.
   - split/provenance/claim-boundary preservation.
   - end-to-end simulator/planner loop report structure.
30. Added calibration output to baseline dynamics predictions so the training objective can score calibration coverage instead of treating the baseline as missing a calibration head.
31. Extended the synthetic experiment runner with backend comparison:
   - The report now includes `backend_comparison` with schema `territory_world_model.synthetic_backend_comparison.v1`.
   - Default compared candidates:
     - `hierarchical_baseline_fit` using `evidence_supported_action_group_means`.
     - `weighted_group_means_trainer` using `weighted_multi_head_group_means`.
     - `torch_multi_head_mlp` using a small local multi-head MLP.
   - Optional CLI switches are available for slower candidates: `--include-graph` and `--include-transformer`.
   - The comparison ranks candidates only within the synthetic experiment boundary; it does not promote a production model.
32. Current backend-comparison result on `docs/reports/twm_synthetic_experiment_foundation.csv`:
   - candidate count: 3.
   - all three candidates returned forecast-consumable predictions and `pass` status under the synthetic experiment gate.
   - baseline group-mean fit: transition error `0.01462`, constraint error `0.041667`, utility error `0.00555`, action-mask accuracy `1.0`.
   - torch MLP: transition error `0.008446`, constraint error `0.067624`, utility error `0.002522`, action-mask accuracy `0.75`.
   - weighted group means matches the transparent baseline metrics but remains marked as a scaffold trainer.
   - current ranking selects `hierarchical_baseline_fit`; this is an experiment selection, not a production claim.
33. Added tests to prevent regression from backend comparison back to a single-backend runner:
   - `test_synthetic_experiment_runner_executes_simulator_planner_loop` now asserts all three default methods are present and emit predictions.
34. Added action-mask diagnostics to backend comparison:
   - Each candidate now includes `action_mask_diagnostics` with confusion counts, false-allow/false-block rates, by-action-type accuracy and mismatch examples.
   - The comparison now includes `action_mask_summary` with the best action-mask candidate, the highest false-allow candidate and worst action type.
   - `false_allow` is explicitly penalized in backend ranking because it can pass a blocked territorial action into planner consumers.
35. Current action-mask interpretation:
   - `hierarchical_baseline_fit`: action-mask accuracy `1.0`, false_allow `0`, false_block `0`.
   - `weighted_group_means_trainer`: action-mask accuracy `1.0`, false_allow `0`, false_block `0`.
   - `torch_multi_head_mlp`: action-mask accuracy `0.75`, false_allow `24`, false_block `0`.
   - MLP errors are concentrated on `defer_review`: accuracy `0.0`, mismatch_count `24`, all false_allow.
   - This explains why MLP can improve transition/utility errors but remain lower-ranked for TWM planning consumption: it fails the high-risk action feasibility head.
36. Added a unit test for the action-mask diagnostic:
   - `test_synthetic_runner_action_mask_diagnostics_identifies_false_allow` ensures a 0.0 action-type accuracy is preserved and not hidden by default-value fallback logic.
37. Added an action-mask calibrated MLP backend variant:
   - Candidate id: `torch_multi_head_mlp_action_mask_calibrated`.
   - Training method label: `torch_multi_head_mlp+action_mask_calibration`.
   - The variant keeps the trained MLP transition/constraint/utility predictions, but calibrates the action-mask head using candidate-split action-mask targets.
   - If an action type is consistently blocked or review-required in the candidate split, the calibrated prediction forces `action_mask.allowed=False` and carries required-review/hard-block metadata forward.
   - This is an experiment-level safety calibration layer, not a production deployment claim.
38. Current calibrated-backend result:
   - Backend comparison now includes 4 candidates.
   - `torch_multi_head_mlp_action_mask_calibrated` fixes the raw MLP action-mask failure, but no longer ranks first after planner-consumer regret is added to the synthetic experiment score.
   - Calibrated MLP keeps the raw MLP's lower transition and utility errors: transition error `0.008446`, utility error `0.002522`.
   - Action-mask accuracy improves from `0.75` to `1.0`.
   - `defer_review` false_allow count drops from `24` to `0`.
   - Planner holdout exact-match for the calibrated MLP is `0.0`, with mean regret `0.031412`; it selects `approve_with_conditions` or `restore` where the synthetic oracle selects `protect`.
   - The transparent baseline is currently the experiment-selected backend because it has zero planner holdout regret, not because it is a final production model.
39. Added calibration regression coverage:
   - `test_synthetic_runner_action_mask_calibration_blocks_review_actions` verifies a learned blocked action type is forced blocked and no longer produces false_allow.
40. Added mixed action-mask calibration stress:
   - Report section: `action_mask_stress` with schema `territory_world_model.action_mask_calibration_stress.v1`.
   - Stress examples: 96.
   - Mixed action types include `approve_with_conditions`, `defer_review` and `restore`.
   - Raw predictions and action-type-only calibration both stay at action-mask accuracy `0.885417`, with false_allow `4` and false_block `7`.
41. Added context action-mask calibration with high-risk fallback:
   - Context key: `action_type+risk_bucket`.
   - If candidate split lacks a high-risk action+risk context, the runner applies a conservative review/block fallback instead of allowing an unsupported high-risk action.
   - Current stress result: context calibration score `1.0`, action-mask accuracy `1.0`, false_allow `0`, false_block `0`.
   - Fallback was applied once, covering the previous unseen high-risk `restore` false_allow case.
42. Added planner-consumer holdout analysis to backend comparison:
   - Schema: `territory_world_model.planner_holdout_analysis.v1`.
   - Grouping: synthetic holdout examples are grouped by `region_code` and `period`, then ranked with the same `utility - risk + 0.1 * confidence` policy used by `beam_plan`.
   - Reported outputs include exact-match, mean/max regret, blocked-target selections, false-allow selections, by-region metrics, by-period metrics and by-action-type metrics.
   - This keeps the planner as a downstream consumer while testing whether simulator heads are useful for planning consumption.
43. Added planner-aware backend ranking:
   - `backend_comparison_rank_score` now includes planner holdout exact-match, regret, false-allow selections and missing selected predictions.
   - Current selected backend: `hierarchical_baseline_fit`, training method `evidence_supported_action_group_means`, rank score `3.752328`.
   - Current selected planner holdout: 8 groups, exact-match `1.0`, mean regret `0.0`, max regret `0.0`, false_allow selections `0`.
   - Calibrated MLP remains useful as the lower transition/utility-error neural candidate, but it is not selected under planner-aware scoring on the current synthetic holdout.
44. Current limitation exposed by the new planner analysis:
   - The current holdout oracle chooses `protect` in all 8 evaluated region/period groups.
   - This means the current synthetic foundation validates the plumbing and regret accounting, but still lacks enough optimal-action diversity to prove robust planning behavior.
45. Added regression coverage:
   - `test_synthetic_experiment_runner_executes_simulator_planner_loop` now asserts planner holdout report structure across backend candidates.
   - `test_synthetic_runner_context_action_mask_calibration_fallback_blocks_unseen_high_risk_context` locks the high-risk fallback behavior.
   - Latest full data-foundation validation suite: `26 passed in 2.57s`.
46. Expanded the synthetic experiment foundation with multi-action oracle profiles:
   - `write_twm_synthetic_experiment_foundation` now assigns scenario-specific preferred actions across `protect`, `restore` and `approve_with_conditions`.
   - `defer_review` remains a review/block negative action for action-mask validation.
   - Synthetic rows still preserve `synthetic=True`, `not_for_production=True` and development-only claim boundaries.
47. Added oracle-action diversity diagnostics to data foundation reports:
   - `twm_synthetic_experiment_foundation.csv` remains 192 rows and 96 treated/control pairs.
   - Scenario count is now `9`.
   - Holdout oracle group count is `8`.
   - Holdout oracle action counts are `approve_with_conditions: 3`, `protect: 2`, `restore: 3`.
   - Holdout oracle action type count is `3`, so the previous all-`protect` limitation is fixed.
48. Regenerated data foundation outputs:
   - JSON: `docs/reports/twm_data_foundation_validation.json`.
   - Markdown preview: `docs/reports/twm_data_foundation_health.md`.
   - Synthetic foundation: `docs/reports/twm_synthetic_experiment_foundation.csv`.
   - The data foundation summary now lists multi-action oracle diagnostics and updated next data work.
49. Current runner result after multi-action oracle foundation:
   - Report: `docs/reports/twm_synthetic_experiment_runner_report.json`.
   - Selected backend: `torch_multi_head_mlp_action_mask_calibrated`.
   - Training method: `torch_multi_head_mlp+action_mask_calibration`.
   - Rank score: `3.777672`.
   - Planner holdout exact-match: `1.0`.
   - Planner holdout mean regret: `0.0`.
   - Planner selected action counts match oracle counts: `approve_with_conditions: 3`, `protect: 2`, `restore: 3`.
   - The transparent baseline now selects `protect` in all 8 groups, exact-match `0.25`, mean regret `0.075119`; this confirms the new foundation actually stresses context-sensitive action selection.
50. Current action-mask stress after multi-action foundation:
   - Context calibration remains selected with score `1.0`.
   - Context calibration action-mask accuracy is `1.0`.
   - false_allow `0`, false_block `0`.
   - Fallback count is now `3`, reflecting additional unseen high-risk contexts in the harder synthetic foundation.
51. Latest regression after this continuation:
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj /Users/zhouning/gisdataagent/.venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py`
   - Result: `26 passed in 2.45s`.
52. Added multi-step planner-consumer rollout matrix:
   - Report schema: `territory_world_model.planner_rollout_matrix.v1`.
   - The matrix chains holdout decisions by `region_code` and sorted holdout period, so a region becomes a short synthetic rollout trajectory rather than only independent one-step rankings.
   - Metrics include trajectory count, step count, selected/oracle cumulative utility, selected/oracle cumulative constraint probability, utility gap, risk gap, cumulative regret, false-allow selections and blocked-target selections.
   - The selected rollout matrix is exposed at top level as `planner_rollout_matrix` and per backend under `planner_holdout_analysis.rollout_matrix`.
53. Current multi-step rollout result:
   - Selected backend remains `torch_multi_head_mlp_action_mask_calibrated`.
   - Trajectory count: `4`; total steps: `8`.
   - Mean cumulative regret: `0.0`; total regret: `0.0`.
   - Selected total utility delta: `0.710144`; oracle total utility delta: `0.710144`; utility gap `0.0`.
   - Selected total constraint probability: `1.786`; oracle total constraint probability: `1.786`; risk gap `0.0`.
   - False-allow selections: `0`; blocked-target selections: `0`.
   - Region sequences match oracle:
     - `SYN-R00`: `restore -> approve_with_conditions`
     - `SYN-R01`: `approve_with_conditions -> protect`
     - `SYN-R02`: `protect -> restore`
     - `SYN-R03`: `restore -> approve_with_conditions`
54. Backend comparison now penalizes rollout accumulation:
   - `backend_comparison_rank_score` now includes rollout mean cumulative regret, positive utility gap and positive risk gap.
   - The transparent baseline is now rank 3, because it still selects `protect` in all 8 steps and accumulates utility gap `0.442848`, risk gap `0.15`, total regret `0.600948`.
   - Raw MLP has zero selected-action rollout regret but still ranks below the calibrated MLP because global action-mask diagnostics still contain false_allow errors.
55. Regression after rollout matrix:
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj /Users/zhouning/gisdataagent/.venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py`
   - Result: `26 passed in 2.43s`.
56. Extended the synthetic experiment foundation from a 6-period/2-holdout-period setup to an 8-period/4-holdout-period setup:
   - `twm_synthetic_experiment_foundation.csv` now has 256 rows and 128 treated/control pairs.
   - Period count: `8`.
   - Holdout period count: `4`.
   - Split counts: `train: 128`, `validation: 64`, `test: 64`.
   - Holdout oracle groups: `16`.
   - Holdout oracle action counts: `approve_with_conditions: 5`, `protect: 5`, `restore: 6`.
   - The generated dynamics dataset now reports `holdout_period_count: 4` and `max_holdout_steps_per_region: 4`.
57. Regenerated data foundation reports after the longer temporal tail:
   - JSON: `docs/reports/twm_data_foundation_validation.json`.
   - Markdown preview: `docs/reports/twm_data_foundation_health.md`.
   - Synthetic foundation: `docs/reports/twm_synthetic_experiment_foundation.csv`.
58. Re-ran the default simulator/planner runner on the 8-period foundation:
   - Report: `docs/reports/twm_synthetic_experiment_runner_report.json`.
   - Selected backend remains `torch_multi_head_mlp_action_mask_calibrated`.
   - Planner rollout matrix now has `4` trajectories and `16` total steps.
   - Mean cumulative regret: `0.0`; total regret: `0.0`.
   - Selected and oracle action sequences match across all 4-step regional trajectories.
59. Added action-mask calibrated graph and transformer variants for optional backend comparison:
   - `torch_hierarchical_graph_action_mask_calibrated`.
   - `torch_spatiotemporal_transformer_action_mask_calibrated`.
   - These variants reuse the trained simulator heads but apply the same candidate-split/action-context safety calibration already used for MLP.
60. Re-ran optional graph/transformer comparison:
   - Report: `docs/reports/twm_synthetic_experiment_runner_report_graph_transformer.json`.
   - Candidate count: `8`.
   - Selected backend: `torch_hierarchical_graph_action_mask_calibrated`.
   - Selected rank score: `3.780059`.
   - Selected planner exact-match: `1.0`; planner mean regret `0.0`.
   - Selected rollout mean cumulative regret `0.0`, utility gap `0.0`, risk gap `0.0`.
   - Raw graph and raw transformer still produce `false_allow: 32` on the action-mask head, concentrated on `defer_review`.
   - Calibrated graph and calibrated transformer both reduce false_allow to `0`.
   - Transformer still has planner exact-match `0.625` and rollout mean cumulative regret `0.153424` even after safety calibration, so its transition/utility ranking heads need further work.
61. Regression after this continuation:
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj /Users/zhouning/gisdataagent/.venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py`
   - Result: `27 passed in 3.05s`.
62. Promoted mixed action-mask labels into data foundation health:
   - `docs/reports/twm_data_foundation_validation.json` summary now exposes allowed/blocked action-mask counts, mixed action-mask action types and per-action counts.
   - Current synthetic foundation remains 256 rows / 128 treated-control pairs / 8 periods / 4 holdout periods.
   - Current action-mask labels: allowed `64`, blocked `64`.
   - Mixed non-defer action types: `approve_with_conditions`, `protect`, `restore`.
   - Counts: `approve_with_conditions` allowed 19 / blocked 13; `protect` allowed 23 / blocked 9; `restore` allowed 22 / blocked 10; `defer_review` allowed 0 / blocked 32.
   - `docs/reports/twm_data_foundation_health.md` now shows these action-mask safety-head data diagnostics directly.
63. Added backend-level mixed action-mask generalization reporting:
   - Report field: `backend_comparison.mixed_action_mask_generalization`.
   - Schema: `territory_world_model.mixed_action_mask_generalization.v1`.
   - The report compares raw, action-type calibration and context calibration using false_allow/false_block tradeoffs.
   - Default runner result: action-type calibration still has false_allow `28`; context calibration has false_allow `0` and false_block `6`.
   - Full graph/transformer runner result: action-type calibrated variants still have false_allow range `15-32`; context calibrated variants have false_allow `0` and false_block `6`.
   - Interpretation: action-type-only safety calibration is now empirically insufficient on the synthetic mixed-risk foundation.
64. Added action-mask context feature channels to trainable simulator candidates:
   - File: `data_agent/territory_world_model/neural_dynamics.py`.
   - New feature namespace: `action_mask_context.*`.
   - Inputs include policy one-hot features, `policy_requires_review`, current/action-derived `risk_proxy`, risk-proxy source and risk-bucket one-hot features.
   - MLP, hierarchical graph and spatiotemporal transformer learned-parameter reports now expose `action_mask_context_feature_names`.
   - Runner backend entries now expose `architecture_summary` and `feature_contract_summary`, including `has_action_mask_policy_context` and `has_action_mask_risk_context`.
   - Current synthetic runner reports show 14 action-mask context features for MLP, graph and transformer candidates.
65. Current runner result after action-mask context feature channels:
   - Default report: `docs/reports/twm_synthetic_experiment_runner_report.json`.
   - Selected backend: `torch_multi_head_mlp_context_action_mask_calibrated`.
   - Training method: `torch_multi_head_mlp+context_action_mask_calibration`.
   - Rank score: `3.624277`.
   - Selected rollout mean cumulative regret: `0.027561`; total regret `0.110244`; utility gap `0.088144`; risk gap `0.022`.
   - Selected action-mask confusion: false_allow `0`, false_block `6`.
   - Transparent baseline is now rank 2: planner exact-match `0.75`, rollout mean cumulative regret `0.052276`.
66. Current full graph/transformer comparison after action-mask context feature channels:
   - Report: `docs/reports/twm_synthetic_experiment_runner_report_graph_transformer.json`.
   - Candidate count: `11`.
   - Selected backend remains `torch_multi_head_mlp_context_action_mask_calibrated`.
   - `torch_hierarchical_graph+context_action_mask_calibration`: rank 3, false_allow `0`, false_block `6`, planner exact-match `0.875`, rollout mean cumulative regret `0.228321`.
   - `torch_spatiotemporal_transformer+context_action_mask_calibration`: rank 4, false_allow `0`, false_block `6`, planner exact-match `0.875`, rollout mean cumulative regret `0.228321`.
   - Raw transformer still has false_allow `64`; action-type calibrated transformer still has false_allow `32`.
   - Next technical bottleneck is not data availability; it is reducing overblocking and planner/rollout regret in the learned simulator heads.
67. Regression after this continuation:
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_territory_world_model.py data_agent/test_twm_data_foundation_validation.py`
   - Result: `87 passed, 4 warnings in 1252.94s`.
   - Targeted follow-up: `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py data_agent/test_territory_world_model.py::test_train_dynamics_candidate_supports_neural_multi_head_trainer_contract data_agent/test_territory_world_model.py::test_train_dynamics_candidate_supports_hierarchical_graph_token_trainer_contract data_agent/test_territory_world_model.py::test_train_dynamics_candidate_supports_spatiotemporal_transformer_trainer_contract`
   - Result: `30 passed in 114.99s`.
68. Processed `docs/twm-technical-review-2026-06-20.md` and adopted the low-risk engineering recommendations that tighten current experiments without changing the core TWM boundary:
   - Correct and adopted: `beam_plan` no longer hides its ranking formula. It now emits `ranking_policy` with default `utility=1.0`, `risk=1.0`, `confidence=0.1`, `blocked_penalty=1.0`, `review_penalty=0.15`, and accepts payload-level `ranking_policy` / `planner_ranking_weights` overrides for holdout experiments.
   - Correct and adopted: `validate_twm_state_input` now checks role/type closure against `canonical_object_type_registry`, duplicated/missing role fields, component rule/objective references, and hard-constraint objective bindings in `optimization_interface`.
   - Correct but deferred: true R-GCN/HGT message passing over `TwmStateRelation`, full latent geometry/state transition beyond the current area/aggregate latent projection, explicit claim-promotion endpoint, and WORM/tamper-evident audit sink. These are larger roadmap items, not quick review fixes.
   - Correct interpretation to preserve: planner/beam/MPC are downstream consumers, not the TWM simulator core. TWM's core remains action-conditioned multi-head territorial dynamics with evidence/causal/action-mask gates.
   - Outdated or inaccurate in the review: the `47 passed` baseline is an earlier snapshot; the latest full TWM regression above is `87 passed, 4 warnings`. The current synthetic foundation is 256 rows / 128 pairs / 8 periods / 4 holdout periods, not the older 192-row foundation. The current selected synthetic runner is `torch_multi_head_mlp_context_action_mask_calibrated`, not the earlier graph action-mask variant.
   - Targeted regression after these review adoptions: `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_territory_world_model.py::test_beam_plan_ranks_candidate_actions_with_dynamics_backend_and_gate data_agent/test_territory_world_model.py::test_beam_plan_accepts_custom_ranking_policy_for_experimental_selection data_agent/test_twm_state_input.py`
   - Result: `8 passed in 40.77s`.
69. Continued with data-driven synthetic validation and reduced context action-mask overblocking without relaxing blocked-policy safety:
   - Root cause from the refreshed reports: the previous 6 false_block cases were all holdout high-risk target-bucket actions that the synthetic label allowed under an allowed policy, but the candidate split lacked the exact high-risk allowed context; the old fallback therefore blocked them with `context_calibration_missing_high_risk_support`.
   - Implementation: `scripts/run_twm_synthetic_experiment.py` now lets high-risk allowed-policy fallback remain allowed only when the candidate predicts non-high mitigated risk (`constraint_violation_probability < 0.3`) and no hard blocks. Blocked/review policy contexts still use conservative fallback.
   - Added calibration summary fields to backend comparison entries: `fallback_rule_prediction_count` and `mitigated_high_risk_fallback_prediction_count`.
   - Default MLP-only runner (`docs/reports/twm_synthetic_experiment_runner_report.json`): `torch_multi_head_mlp_context_action_mask_calibrated` remains selected; action-mask confusion improved from false_allow `0` / false_block `6` to false_allow `0` / false_block `0`; planner mean regret remains `0.00689`; rollout mean cumulative regret remains `0.027561`.
   - Full graph/transformer runner (`docs/reports/twm_synthetic_experiment_runner_report_graph_transformer.json`): selected backend is now `torch_hierarchical_graph_context_action_mask_calibrated`, rank score `3.783466`, false_allow `0`, false_block `0`, planner exact-match `0.9375`, planner mean regret `0.000418`, rollout mean cumulative regret `0.001673`.
   - `torch_multi_head_mlp_context_action_mask_calibrated` is now rank 2 in the full comparison with false_allow `0`, false_block `0`, planner mean regret `0.00689`, rollout mean cumulative regret `0.027561`.
   - `torch_spatiotemporal_transformer_context_action_mask_calibrated` still has false_allow `0`, false_block `6`; its mismatches have predicted constraint probabilities around `0.40-0.46`, so this is now a transformer risk-head calibration problem rather than an action-mask fallback problem.
70. Regression after this data-driven continuation:
   - `python -m py_compile scripts/run_twm_synthetic_experiment.py data_agent/test_twm_data_foundation_validation.py`
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py`
   - Result: `28 passed in 3.29s`.
71. Added candidate-split transformer constraint-risk calibration:
   - File: `scripts/run_twm_synthetic_experiment.py`.
   - New report schema: `territory_world_model.constraint_risk_calibration.v1`.
   - New candidate variants:
     - `torch_spatiotemporal_transformer_constraint_risk_calibrated`.
     - `torch_spatiotemporal_transformer_constraint_risk_context_action_mask_calibrated`.
   - The calibration learns an affine correction from the candidate split and applies it to transformer `constraint_violation_probability` predictions.
   - Stability gate: calibration is marked `review` and is not applied when prediction standard deviation is below `0.02` or fitted slope is below `0.1`. This prevents tiny/degenerate candidate splits from making transformer risk worse.
72. Latest full graph/transformer synthetic comparison:
   - Report: `docs/reports/twm_synthetic_experiment_runner_report_graph_transformer.json`.
   - Candidate count: `13`.
   - Selected backend remains `torch_hierarchical_graph_context_action_mask_calibrated`.
   - Selected rank score: `3.783466`; mean constraint error `0.046691`; false_allow `0`; false_block `0`.
   - Selected planner exact-match `0.9375`; planner mean regret `0.000418`; rollout mean cumulative regret `0.001673`.
   - `torch_spatiotemporal_transformer_constraint_risk_context_action_mask_calibrated` is rank 2 with rank score `3.781588`, mean constraint error `0.037035`, false_allow `0`, false_block `0`, planner exact-match `0.9375`, planner mean regret `0.000418`, and rollout mean cumulative regret `0.001673`.
   - Its risk calibration passed on 64 candidate samples: slope `0.850472`, intercept `-0.138157`, prediction std `0.041931`, MAE before `0.200425`, MAE after `0.026819`.
   - `torch_spatiotemporal_transformer_constraint_risk_calibrated` alone improves the risk head but remains unsafe for planning consumption: action-mask false_allow stays `64`, planner mean regret is `0.169615`, rollout mean cumulative regret is `0.678461`.
   - Interpretation: transformer risk calibration and context action-mask calibration solve different simulator failures. Risk calibration fixes overpredicted constraint risk; action-mask context calibration prevents illegal actions from reaching planner consumers.
73. Regression after transformer risk calibration:
   - `python -m py_compile scripts/run_twm_synthetic_experiment.py data_agent/test_twm_data_foundation_validation.py`
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py`
   - Result: `28 passed in 3.21s`.
74. Started internalizing transformer constraint-risk calibration into training:
   - File: `data_agent/territory_world_model/neural_dynamics.py`.
   - Added `constraint_risk_calibration_weight` to trainable dynamics config.
   - The MLP, graph and transformer training loops now support an explicit probability calibration loss on `constraint_violation_probability`; default weight is `0.0` to avoid changing MLP/graph behavior.
   - The synthetic experiment runner enables this only for `torch_spatiotemporal_transformer` with weight `0.35`.
   - Backend comparison entries now expose `training_diagnostics.constraint_risk_calibration_weight`.
75. Latest full graph/transformer comparison after training-internal risk calibration:
   - Report: `docs/reports/twm_synthetic_experiment_runner_report_graph_transformer.json`.
   - Candidate count remains `13`.
   - Selected backend remains `torch_hierarchical_graph_context_action_mask_calibrated`.
   - Graph context: rank score `3.783466`, constraint-risk calibration weight `0.0`, mean constraint error `0.046691`, false_allow `0`, false_block `0`, planner mean regret `0.000418`, rollout mean cumulative regret `0.001673`.
   - Transformer risk+context: rank `2`, rank score `3.781435`, constraint-risk calibration weight `0.35`, mean constraint error `0.037419`, false_allow `0`, false_block `0`, planner mean regret `0.000418`, rollout mean cumulative regret `0.001673`.
   - Transformer candidate-split risk calibration still passes, with MAE before `0.192913` and after `0.026611`. This is a small improvement over the previous pre-calibration MAE `0.200425`, but it has not removed the need for post-hoc calibration.
   - Raw transformer still has action-mask false_allow `64`; this confirms action-mask feasibility remains a separate head/gate problem from risk probability calibration.
76. Regression after training-internal risk calibration:
   - `python -m py_compile data_agent/territory_world_model/neural_dynamics.py data_agent/test_territory_world_model.py scripts/run_twm_synthetic_experiment.py data_agent/test_twm_data_foundation_validation.py`
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_territory_world_model.py::test_train_dynamics_candidate_supports_spatiotemporal_transformer_trainer_contract data_agent/test_twm_data_foundation_validation.py::test_synthetic_experiment_runner_calibrates_graph_and_transformer_action_masks`
   - Result: `2 passed in 40.11s`.
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py`
   - Result: `28 passed in 3.58s`.
77. Added transformer risk-calibration weight probing:
   - File: `scripts/run_twm_synthetic_experiment.py`.
   - New CLI/function inputs:
     - `--transformer-risk-calibration-weight`, initially tested with default `1.2`; superseded by item 82 where the context-residual risk head sets the current default to `0.0`.
     - `--probe-transformer-risk-weights`, optional comma-separated matrix outside the main backend ranking.
   - New report section: `transformer_risk_weight_probe`, schema `territory_world_model.transformer_risk_weight_probe.v1`.
   - The probe trains transformer candidates with alternative `constraint_risk_calibration_weight` values and reports raw mean constraint error, candidate-split MAE before/after affine calibration, action-mask confusion, planner regret and rollout regret.
   - Probe rows do not enter `backend_comparison.ranking`; main candidate count remains `13`.
78. Previous shared-head weight-probe result on the 256-row / 128-pair / 8-period synthetic foundation:
   - Weights tested: `0.0`, `0.35`, `0.7`, `1.2`.
   - Selected probe weight under the shared-head architecture: `1.2`.
   - Raw transformer mean constraint error improved from `0.178336` at weight `0.0` to `0.155325` at weight `1.2`.
   - Candidate-split MAE before post-hoc calibration improved from `0.200425` at weight `0.0` to `0.17825` at weight `1.2`.
   - Post-hoc calibrated MAE remains around `0.0266-0.0268`; the best pre-calibration weight therefore reduces dependence on affine correction but does not eliminate it.
   - false_allow remains `0`, false_block remains `0`, planner mean regret remains `0.000418`, and rollout mean cumulative regret remains `0.001673` for the calibrated risk+context transformer probe rows.
79. Previous full graph/transformer comparison after setting shared-head transformer risk weight to `1.2`:
   - `torch_hierarchical_graph_context_action_mask_calibrated` remains rank 1: rank score `3.783466`, mean constraint error `0.046691`, false_allow `0`, false_block `0`.
   - `torch_spatiotemporal_transformer_constraint_risk_context_action_mask_calibrated` remains rank 2: rank score `3.781534`, training risk weight `1.2`, mean constraint error `0.038044`, false_allow `0`, false_block `0`.
   - Raw transformer still has false_allow `64`, so action-mask feasibility remains a separate learned/gated head from risk probability calibration.
   - Superseded by items 81-84: the current context-residual risk head with weight `0.0` outperforms this scalar-weight result.
80. Regression after risk-weight probe:
   - `python -m py_compile scripts/run_twm_synthetic_experiment.py data_agent/test_twm_data_foundation_validation.py`
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py::test_synthetic_experiment_runner_calibrates_graph_and_transformer_action_masks data_agent/test_twm_data_foundation_validation.py::test_synthetic_runner_probes_transformer_risk_calibration_weights`
   - Result: `2 passed in 3.21s`.
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py`
   - Result: `29 passed in 3.76s`.
81. Added a structural transformer constraint-risk head:
   - File: `data_agent/territory_world_model/neural_dynamics.py`.
   - New training config: `risk_head_mode`, currently supporting `shared` and `context_residual`.
   - `context_residual` keeps the shared 6-head output contract but adds a residual logit to `constraint_violation_probability` from pooled transformer state plus explicit `action`, `context` and `temporal` token embeddings.
   - Architecture and training diagnostics now expose `constraint_risk_head`, `constraint_risk_context_tokens` and `risk_head_mode`.
82. Added risk-head and updated weight probes:
   - File: `scripts/run_twm_synthetic_experiment.py`.
   - Default transformer experiment now uses `risk_head_mode=context_residual` and `constraint_risk_calibration_weight=0.0`.
   - New report section: `transformer_risk_head_probe`, schema `territory_world_model.transformer_risk_head_probe.v1`.
   - The existing `transformer_risk_weight_probe` now records `risk_head_mode`, `risk_head_context_tokens`, blocked-training evidence and training status.
83. Latest full graph/transformer comparison on the 256-row / 128-pair / 8-period synthetic foundation:
   - Candidate count remains `13`.
   - Rank 1 is now `torch_spatiotemporal_transformer_constraint_risk_context_action_mask_calibrated`: rank score `3.802079`, risk head `context_residual`, risk weight `0.0`, mean constraint error `0.034328`, false_allow `0`, false_block `0`, planner exact-match `1.0`, planner mean regret `0.0`, rollout mean cumulative regret `0.0`.
   - Rank 2 is `torch_spatiotemporal_transformer_context_action_mask_calibrated`: rank score `3.797787`, mean constraint error `0.040459`, false_allow `0`, false_block `0`, planner exact-match `1.0`, planner mean regret `0.0`, rollout mean cumulative regret `0.0`.
   - Rank 3 is `torch_hierarchical_graph_context_action_mask_calibrated`: rank score `3.783466`, mean constraint error `0.046691`, false_allow `0`, false_block `0`, planner exact-match `0.9375`, planner mean regret `0.000418`, rollout mean cumulative regret `0.001673`.
84. Latest risk-head probe:
   - Shared transformer risk head selected weight `1.2`: raw mean constraint error `0.155325`, candidate-split MAE before affine calibration `0.17825`, calibrated mean constraint error `0.038044`, planner mean regret `0.000418`.
   - Context-residual risk head selected weight `0.0`: raw mean constraint error `0.040459`, candidate-split MAE before affine calibration `0.026218`, calibrated mean constraint error `0.034328`, planner mean regret `0.0`.
   - Interpretation: the major gain came from giving the simulator's risk head direct action/context/temporal token access, not from increasing the scalar calibration-loss weight. This is a more substantive TWM simulator improvement because it internalizes contextual territorial feasibility/risk structure into the dynamics head.
85. Regression after context-residual risk head:
   - `python -m py_compile scripts/run_twm_synthetic_experiment.py data_agent/territory_world_model/neural_dynamics.py data_agent/test_twm_data_foundation_validation.py`
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py::test_synthetic_experiment_runner_calibrates_graph_and_transformer_action_masks data_agent/test_twm_data_foundation_validation.py::test_synthetic_runner_probes_transformer_risk_calibration_weights`
   - Result: `2 passed in 4.90s`.
   - `PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/pytest -q data_agent/test_twm_data_foundation_validation.py`
   - Result: `29 passed in 5.13s`.

Next session should continue with:

1. Turn context action-mask calibration from post-hoc rule correction into a learned context-sensitive action-mask head while preserving the zero false_allow / zero false_block result on the 256-row synthetic foundation.
2. Continue replacing post-hoc transformer affine risk calibration with learned risk-head calibration; current context-residual head has already reduced candidate-split MAE before affine calibration to `0.026218`, so the next threshold should track whether post-hoc MAE improvement becomes marginal.
3. Add harder mixed-risk temporal tails where high-risk actions can be allowed with conditions instead of always blocked, and keep separate diagnostics for risk-head error versus action-mask feasibility error.
4. Keep `twm_structural_validation_observed_history.csv` as a regression fixture only; never use it to claim deployment causal support.
5. Use `twm_data_foundation_health.md` for quick review, but use `twm_data_foundation_validation.json` for exact diagnostics.
6. Use the evidence-augmented matching diagnostics to synthesize harder control records and mixed spatial units.
7. Keep GeoFM optional: feed the GeoFM downstream experiment report from explicit synthetic cross-region planning runs and temporal holdouts, then compare auto-inferred checks against explicit experiment reports.
8. Deepen ArcGIS/frontend deployment loop for causal calibration, synthetic experiment review and GeoFM review outputs.

## Important Working Notes

- Do not treat GeoFM as the default main model. It must pass downstream gates.
- Planner/beam/MPC are consumers of the world model, not the world model itself.
- Do not collapse TWM state into a flat vector. Keep parcel/block/township/county token semantics.
- Keep `forecast`, `rollout`, `beam_plan`, `dynamics_backend_report`, and `training_objective_report` contract-compatible.
- The repository has unrelated local changes in other areas. Avoid staging non-TWM changes unless explicitly requested.

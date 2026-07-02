# TWM Algorithm Model Roadmap

Date: 2026-07-02
Project: GIS Data Agent / Territory World Model
Status: post-P4B geospatial world-model reliability roadmap

## Executive Position

TWM should now be optimized as an evidence-gated, action-conditioned geospatial
world model for territorial governance. Its strongest current identity is not a
generic land-use simulator and not an automatic planner, but an auditable loop:

```text
hierarchical GIS state
  + governance action
  + scenario / policy context
  + evidence
  -> future-state latent, constraint risk, planning utility delta, uncertainty
  -> planner / reviewer / audit consumer
```

The right near-term target is a production-data-backed **L2 simulator** with
strict decision-centric evaluation. L3 self-evolution should remain a governed
scaffold until real observed-history feedback, model versioning, rollback and
regression gates are proven on pilot data.

## Current Boundary

Current TWM is already beyond a rule engine or map demo:

- hierarchical object-relation-rule-evidence state construction exists;
- action-conditioned forecast, counterfactual rollout and beam-planner consumer
  exist;
- trainable dynamics backends exist for MLP, hierarchical graph and
  spatiotemporal transformer candidates;
- future latent state v2 has moved from scalar proxy toward a
  multi-dimensional decoded state contract;
- evidence gates, claim ladder, causal calibration reports, GeoFM gates,
  Dynamic World / GeoSOS / FLUS benchmark adapters and model-registry gates
  exist as engineering surfaces.

The first strict evidence-gate slice is now implemented:

- dynamics datasets emit MREP-style trace metadata with semantic dataset hashes,
  lineage fields, split definitions, baseline versions and failure taxonomy;
- strict readiness can require production observed-history preflight;
- strict readiness can require same-case baseline evidence;
- production onboarding can run same-case baseline export validation and expose
  baseline evidence in JSON and Markdown;
- onboarding now summarizes a strict model-promotion gate while keeping
  non-strict runs diagnostic-only.

The remaining production blocker is pilot evidence quality, not gate plumbing:

- no authoritative production approval/review history is available yet;
- policy-action and action-feasibility labels are not available yet;
- same-case baseline evidence against human GIS, rule-only workflows and
  traditional simulators is still incomplete;
- public benchmark wins are metric-specific and do not justify blanket
  "TWM beats FLUS" language;
- local causal calibration is observational unless a stronger identification
  design is supplied.

## Theoretical Anchor

The roadmap follows the agentic world-model framing from paper `2604.22748v3`:

- **L1 Predictor**: predict next or near-future state under observed patterns.
- **L2 Simulator**: answer intervention and counterfactual queries under action
  and scenario conditions.
- **L3 Evolver**: revise the model from new feedback while preserving versioned
  evidence, boundary conditions and regression safety.

For TWM, the correct mapping is:

| Paper concept | TWM interpretation | Current status |
|---|---|---|
| L1 predictor | land/state transition and risk heads | candidate |
| L2 simulator | action-conditioned rollout with rule/evidence gates | main target |
| L3 evolver | feedback-driven model revision and promotion gate | scaffold only |
| decision-centric evaluation | planning lift, legal-feasible top-k, claim upgrade | partial |
| MREP-style reproducibility | dataset/model/rule/version trace, failure taxonomy | partial |

The roadmap therefore prioritizes instrumented simulation and decision value
over raw map accuracy alone.

## Roadmap Principles

1. **Separate learned from enforced.**
   The model may learn transition likelihoods, utility deltas and uncertainty.
   Legal constraints, hard action masks, lineage and audit rules must remain
   explicit and enforceable.

2. **Match representation to planner queries.**
   `future_latent_state` should predict the state summaries needed by planning
   and review: area, feature count, land-space type allocation, transition
   delta, risk and uncertainty. It should not claim full future parcel geometry
   generation until that is actually implemented and evaluated.

3. **Evaluate decisions, not only prediction.**
   TWM must report whether its simulator improves candidate filtering, ranking,
   legal feasibility, review efficiency and claim quality against same-case
   baselines.

4. **Instrument before iteration.**
   Every model improvement needs fixed dataset snapshots, model versions,
   baseline outputs, trace logs, error taxonomy and boundary conditions before
   it can be promoted.

5. **Keep claim language gate-controlled.**
   Synthetic, scaffold, public benchmark and production pilot results must be
   labeled separately.

## SWM / Lance Reference Refresh

Reference checked on 2026-07-01: the WeChat article URL was not directly
accessible from the automation environment, so the technical interpretation is
grounded in `stable-worldmodel` paper `2605.21800` and the public repository
`https://github.com/galilai-group/stable-worldmodel`.

`stable-worldmodel` is useful to TWM mainly as a reproducible world-model
platform pattern, not as a domain model to copy. Its relevant ideas are:

- a dataset-first pipeline for collection, conversion, training and evaluation;
- Lance-backed trajectory storage for fast random access to sequence/video-style
  training windows;
- standard `World`, `Policy`, `Solver` and dataset abstractions;
- baseline world models and planning solvers reported under the same harness;
- controllable factors of variation for out-of-distribution and zero-shot
  robustness testing.

TWM should translate those ideas into a geospatial-governance equivalent:

- define `TwmTrajectoryDataset` as the canonical state/action/next-state
  sequence contract;
- expose a stable model interface:
  `encode_state -> predict_next -> rollout -> score_action -> validate_gate`;
- run every dynamics model and planner through the same fixed replay harness;
- define TWM factors of variation across region, year, rule version, evidence
  completeness, policy scenario, label quality, CRS/data quality and baseline
  availability;
- keep `LanceDB` as an optional vector/trajectory sidecar for high-dimensional
  latent states, multimodal evidence embeddings and random-access sequence
  windows.

Storage boundary: Lance/LanceDB must not become the primary TWM lakehouse,
authoritative store or audit store. The primary chain remains
Iceberg + PostGIS + MinIO + Sedona. Lance datasets may store derived vectors,
latent tensors, image/evidence embeddings or trajectory windows, but every row
must link back to Iceberg/PostGIS object IDs, evidence IDs, state snapshot IDs,
dataset hashes and feature versions.

## Priority Roadmap

### P0. Production Evidence Gate: 2-4 Weeks

Goal: make real or sanitized pilot data the first-class blocker and promotion
gate for any algorithm claim.

Work items:

- define the authoritative pilot data intake contract:
  - administrative boundary and control-line versions;
  - project / parcel / review object IDs;
  - approval, rejection, supplementation, enforcement and later-change history;
  - policy-action labels and action-feasibility labels;
  - rule-hit, evidence-material and human-review outcomes;
  - same-case baseline artifacts.
- run `scripts/run_twm_production_onboarding.py` against at least one real or
  sanitized pilot package.
- generate a machine-readable production readiness report with:
  - observed-history row count;
  - policy-action row count;
  - temporal coverage;
  - spatial-unit coverage;
  - CRS and lineage diagnostics;
  - missing fields and blocking reasons.
- freeze one pilot evaluation package with dataset hash, rule version, state
  snapshot ID and baseline artifacts.

Acceptance gate:

- at least one pilot package can build a TWM state and a dynamics dataset without
  falling back to synthetic/not-for-production records;
- missing observed history or action labels blocks model promotion explicitly.

### P1. State / Action / Next-State Contract: 2-6 Weeks

Goal: turn the training dataset into a stable world-model contract rather than a
collection of convenient payload fields.

Work items:

- standardize the row contract:

```text
state_t: current_hierarchical_gis_state
  + action
  + scenario_context
  + evidence_context
  -> state_t+1: observed_next_state
  + constraint_outcome
  + utility_outcome
  + review_outcome
```

- publish the row contract as `TwmTrajectoryDataset.v1` with:
  - `state_t_ref`, `state_t_plus_1_ref` and state snapshot versions;
  - `action_id`, action parameters and action-mask context;
  - scenario, policy, rule and evidence context references;
  - `constraint_outcome`, `utility_outcome`, `review_outcome`;
  - `dataset_hash`, `split`, `source_lineage`, `baseline_version`;
  - optional `vector_feature_ref` or `trajectory_lance_ref` for sidecar features.
- finish and document `future_latent_state` v2 as the main next-state head:
  - `latent_vector`;
  - `decoded_state`;
  - land-space-type area and count summaries;
  - transition deltas;
  - representation boundary.
- add temporal and spatial split metadata to every training/evaluation package.
- make MREP-style trace requirements explicit:
  - dataset snapshot hash;
  - state/rule/model version;
  - random seed;
  - split definition;
  - baseline version;
  - failure taxonomy;
  - tail statistics.

Acceptance gate:

- model evaluation can fail when total area is correct but land-type allocation
  is wrong;
- every claim can be traced to state, dataset, rule and model versions.

### P2. Dynamics Model Optimization: 1-3 Months

Goal: improve the simulator as an action-conditioned, multi-head dynamics model,
not just a suitability scorer.

Model families to compare:

| Family | Role | Promotion condition |
|---|---|---|
| deterministic/rule baseline | lower bound and explainability baseline | always reported |
| Markov / persistence | simple land-transition baseline | always reported |
| MLP multi-head dynamics | small-data baseline | only for limited pilot scope |
| hierarchical graph dynamics | object-relation and admin hierarchy modeling | must beat MLP on holdout and decision metrics |
| spatiotemporal transformer | longer temporal context and regional transfer | must justify complexity with cross-time/cross-region gain |
| TWM-native suitability learner | compatibility with land-use simulation baselines | must retain action, evidence and rule gates |
| GeoFM-augmented variant | optional representation enhancement | only promoted through B0/B1 and D2/D3/D4 gates |

Optimization themes:

- add transition priors and demand constraints as explicit baselines, not hidden
  model advantages;
- model neighborhood influence and spatial spillover separately from causal
  effect claims;
- calibrate uncertainty and action-mask false allow / false block rates;
- evaluate seed stability and small-sample overfitting;
- report metric-specific comparison against FLUS/GeoSOS rather than broad
  superiority.

Acceptance gate:

- dynamics evaluation passes temporal holdout and at least one spatial holdout;
- target-head metrics include future-state latent quality, constraint risk,
  utility delta and uncertainty;
- promotion is blocked if gains only appear on scaffold or oracle-demand
  settings.

### P3. Planner-Coupled Evaluation: 2-4 Months

Goal: prove that the world model improves territorial decisions, not only raster
or state-transition metrics.

Decision metrics:

- legal-feasible top-k precision;
- blocked-action recall;
- false-allow and false-block rates for action masks;
- planner regret against same-case baseline;
- ranking lift over rule-only and manual baseline;
- review workload reduction without losing high-risk cases;
- explanation coverage for recommended / blocked / review candidates;
- constraint-risk calibration for selected plans.

Baselines:

- human GIS review artifacts;
- rule-only engine;
- persistence / Markov;
- GeoSOS / FLUS-style simulation where comparable;
- existing optimization or MPC workflow where available.

Acceptance gate:

- at least one same-case pilot shows where TWM improves, where it ties and where
  it loses;
- selected-plan claims stay at `review` unless evidence, causal and human-review
  gates are sufficient.

### P4. Causal, Evidence and GeoFM Upgrade: 3-6 Months

Goal: strengthen the evidence layer without overstating causality.

Work items:

- keep current causal calibration labeled as observational by default;
- add spatial fixed effects, matching diagnostics, overlap diagnostics and
  interference diagnostics to every causal report;
- integrate external SCCA evidence only as additional evidence, not as automatic
  causal truth;
- promote causal language only when the identification design supports it;
- keep GeoFM as gated enhancement:
  - B0/B1 downstream lift;
  - D2 explicit planning holdout;
  - D3 cross-region robustness;
  - D4 temporal/domain-shift and label-quality gate.

Acceptance gate:

- causal/evidence reports expose identification strength, assumptions,
  diagnostics and failure modes;
- GeoFM variants do not replace non-GeoFM baselines in reports.

### P5. Production Promotion and L3 Path: 6-12 Months

Goal: build the controlled evolution loop needed before calling TWM a governed
L3-style model.

Work items:

- split the large TWM service facade into clearer service boundaries:
  - state/data foundation;
  - rule/evidence/audit;
  - dynamics training/evaluation;
  - causal/evidence calibration;
  - planner consumer;
  - production readiness and model registry.
- harden model registry and release gates:
  - artifact URI;
  - training dataset hash;
  - rule/state version;
  - evaluation report ID;
  - rollback target;
  - canary/promotion status.
- add replay and regression gates:
  - same-case replay;
  - cross-version metric drift;
  - legal constraint regression;
  - high-risk tail cases;
  - failure taxonomy.
- complete large-scale data infrastructure:
  - CRS conversion ETL;
  - vector tiles or server-side chunking;
  - lakehouse snapshot export;
  - Iceberg/Sedona audit acceptance;
  - air-gapped deployment and sanitized diagnostic export.

Acceptance gate:

- no model version can be promoted without reproducible evidence and rollback;
- L3 self-evolution remains disabled or review-only until feedback loops are
  audited against production pilot data.

## 30 / 60 / 90 Day Execution View

### 30 Days

- treat `pilot_package.v1` as the mandatory experiment envelope for the next
  algorithm slice, with `package_id`, dataset hash, split summary and blockers
  pinned into every candidate report;
- freeze one strict pilot data package that satisfies production
  observed-history preflight and same-case baseline export requirements; until
  that package exists, keep P2B results diagnostic-only;
- use `dynamics_model_shootout_report.v1` as the first P2B artifact,
  aggregating deterministic/rule, persistence/Markov, MLP, graph and transformer
  candidates under the same `pilot_package.v1`;
- finish future latent v2 contract checks for area, land-space type allocation,
  transition deltas, risk and uncertainty;
- add explicit action-mask false allow / false block, seed stability, temporal
  holdout and spatial holdout reporting to the shootout summary;
- keep GeoFM, causal and production claims outside the shootout unless their
  separate gates are supplied.

### 60 Days

- train and compare MLP multi-head, hierarchical graph and spatiotemporal
  transformer dynamics on the same pilot package;
- add persistence, Markov, rule-only and deterministic TWM scaffold baselines to
  every dynamics report;
- add the P2C FoV robustness matrix for at least region, year/rule version,
  evidence completeness and sanitized/not-for-production label quality;
- run same-case planner replay against manual GIS, rule-only and comparable
  FLUS/GeoSOS outputs;
- report uncertainty calibration, tail-case failures, action-mask errors and
  cross-region/cross-time degradation;
- keep GeoFM and causal upgrades behind separate evidence gates.

### 90 Days

- nominate one strict model-promotion candidate with complete evidence bundle,
  model registry entry, rollback target and replay test;
- produce selected-plan reports with recommendation / block / review classes and
  human audit outcomes;
- connect causal/evidence diagnostics and planner replay results to claim-ladder
  status;
- define the first canary protocol, drift dashboard and regression suite;
- keep L3 self-evolution review-only until feedback-loop audits pass.

## Claim Upgrade Ladder

| Claim level | Allowed wording | Required evidence |
|---|---|---|
| L0 demo | TWM can run an auditable demo workflow | demo data, E2E, map consistency |
| L1 predictor candidate | TWM can predict selected future-state summaries | holdout metrics, baseline comparison |
| L2 simulator candidate | TWM can answer action-conditioned rollout queries | temporal/spatial holdout, counterfactual diagnostics, evidence gates |
| decision-support pilot | TWM improves selected planning/review decisions | same-case planner metrics and human review |
| production governed model | TWM can be promoted for controlled production use | real data, registry, replay, rollback, audit chain |
| L3 evolver | TWM can revise itself under governance | feedback loop, canary promotion, regression gates, failure taxonomy |

## Recommended External Wording

Use:

> TWM is an evidence-gated geospatial world model for territorial governance. It
> represents land systems as hierarchical GIS object-relation-rule-evidence
> states, learns action-conditioned multi-head dynamics, and upgrades planning
> claims only through validation, causal/evidence diagnostics and audit gates.

Avoid:

- TWM is already production-ready;
- TWM fully beats FLUS/GeoSOS;
- TWM generates full future parcel geometry;
- TWM proves causal effects without identification evidence;
- planner ranking alone is the world model.

## Immediate Next Decision

P2A now has the core package plumbing: `dynamics_evaluation_bundle.v1`,
`pilot_package.v1`, `trajectory_dataset_manifest.v1` and optional
`lance_sidecar_manifest.v1`. P2B now has the first algorithm-selection packet:
`dynamics_model_shootout_report.v1`.

The next implementation slice should feed real candidate reports from the
existing deterministic/rule, persistence/Markov, MLP, graph and transformer
contracts into that shootout. Any result with package, split or baseline
mismatch remains diagnostic-only. The first candidate that wins the shootout
still needs P3A same-case planner replay before promotion language is allowed.

## Implementation Checkpoint: P0/P1 Gate Hardening

Plan: `docs/superpowers/plans/2026-06-30-twm-p0-p1-production-evidence-contract.md`

The first implementation slice was intentionally gate-focused. It made
production observed-history preflight, same-case baseline evidence and MREP
traceability visible in strict readiness and onboarding reports before adding
more model architecture complexity.

## Post-P0/P1 Optimization Roadmap

The next development phase should optimize the model under the strict evidence
contract that now exists. The priority is not adding another broad surface area;
it is making each candidate dynamics model win or fail under the same pilot data,
same-case baselines and promotion gates.

### P2A. Pilot Dataset And Dynamics Bundle Hardening

Goal: make one pilot package the canonical training/evaluation unit.

Work items:

- define `pilot_package.v1` with:
  - observed approval/review history;
  - policy-action and feasibility labels;
  - same-case baseline exports;
  - state/rule/model version references;
  - temporal and spatial split definitions;
  - `TwmTrajectoryDataset.v1` export manifest;
  - not-for-production and sanitization flags.
- add `dynamics_evaluation_bundle.v1`:
  - MREP trace;
  - target-head metrics;
  - temporal/spatial holdout metrics;
  - seed stability;
  - action-mask false allow / false block;
  - failure taxonomy and tail statistics.
- require every model comparison to reference the same dataset snapshot and
  baseline versions.
- add a Lance sidecar manifest only when the pilot package needs high-dimensional
  latent vectors, multimodal embeddings or random-access trajectory windows:
  - Iceberg remains the authoritative tabular manifest;
  - Lance stores derived sequence/vector payloads;
  - rows must be addressable through `state_snapshot_id`, `object_id`,
    `evidence_id`, `dataset_hash` and `feature_version`.

Acceptance gate:

- a dynamics report cannot be promoted unless it links production onboarding,
  same-case baseline evidence, MREP trace and split definitions.

### P2B. Multi-Head Dynamics Model Shootout

Goal: compare model families on the same action-conditioned next-state contract.

Candidates:

- deterministic TWM scaffold and rule-only baseline;
- persistence / Markov transition baseline;
- MLP multi-head dynamics;
- hierarchical graph dynamics;
- spatiotemporal transformer dynamics;
- optional TWM-native suitability learner;
- optional GeoFM-augmented representation.

Required model interface:

- `encode_state(state_t, evidence_context)`;
- `predict_next(encoded_state, action, scenario_context)`;
- `rollout(state_t, action_sequence, scenario_context, horizon)`;
- `score_action(rollout, constraint_rules, utility_objective)`;
- `validate_gate(rollout, evidence_trace, claim_level)`.

Required heads:

- decoded future-state summaries;
- land-space type area and count allocation;
- transition deltas;
- constraint-risk probability;
- utility delta;
- review workload / intervention need;
- uncertainty and calibration.

Next implementation artifact:

- add `dynamics_model_shootout_report.v1` as the canonical comparison packet;
- inputs:
  - `pilot_package_report`;
  - one shared `package_id` and `dataset_snapshot_hash`;
  - baseline candidate reports for deterministic/rule and persistence/Markov;
  - candidate reports from existing MLP, graph and transformer trainer
    contracts;
  - optional comparable FLUS/GeoSOS/MPC baseline references;
  - optional GeoFM candidate only when B0/B1 and D2/D3/D4 evidence is supplied.
- report sections:
  - package integrity and mismatch blockers;
  - target-head metrics by model family;
  - constraint-risk, utility-delta and uncertainty metrics;
  - action-mask false allow / false block;
  - seed stability and small-sample warning flags;
  - temporal holdout, spatial holdout and FoV stress-test summary;
  - planner-coupled metrics where same-case replay is available;
  - promotion recommendation and claim boundary.

Acceptance gate:

- graph or transformer models must beat the MLP baseline on temporal holdout,
  at least one spatial holdout and planner-coupled metrics before their added
  complexity is justified;
- no model family can be recommended for promotion if the report detects
  package hash mismatch, split mismatch, stale baseline artifacts or missing
  production/same-case gates.

### P2C. SWM-Style Robustness And FoV Harness

Goal: convert SWM's controllable factors-of-variation idea into TWM-specific
distribution-shift tests.

TWM factors of variation:

- region and administrative hierarchy;
- year / policy cycle / planning horizon;
- rule version and control-line version;
- evidence completeness and evidence-source mix;
- label quality, missingness and sanitized/not-for-production flags;
- action-space scope and feasibility-label availability;
- CRS, scale, geometry quality and MMFE feature availability;
- baseline availability across human GIS, rule-only, FLUS/GeoSOS and MPC
  workflows.

Acceptance gate:

- every promoted dynamics result must report in-distribution, temporal holdout,
  spatial holdout and at least one explicit FoV stress test;
- robustness claims remain diagnostic if the FoV matrix is synthetic-only.

### P3A. Same-Case Planner Replay

Goal: prove decision value on historical cases, not only predictive fit.

Replay outputs:

- legal-feasible top-k precision;
- planner regret against human or rule-only choices;
- blocked-action recall;
- false allow and false block rates;
- review workload reduction;
- explanation coverage for recommended, blocked and review-only candidates;
- loss cases where TWM underperforms manual GIS or rule-only workflows.

Benchmark harness requirements:

- fixed replay budget and candidate-action budget per case;
- identical pilot split and baseline artifact versions for every solver;
- baselines include persistence, Markov, rule-only, FLUS/GeoSOS adapter where
  comparable, MLP, graph and transformer dynamics;
- report forecast-head quality, rollout regret, planning lift, false allow /
  false block, evidence-gate pass rate and selected-plan audit status together.

Acceptance gate:

- a decision-support claim remains `review` unless same-case replay shows where
  TWM improves, ties and loses, with human-auditable evidence.

### P3B. Promotion Candidate Evidence Bundle

Goal: prepare the first controlled promotion candidate without claiming
production readiness prematurely.

Bundle contents:

- model artifact URI;
- training dataset hash;
- state/rule/evidence version;
- evaluation bundle ID;
- same-case planner replay report;
- baseline comparison report;
- causal/evidence diagnostics;
- rollback target;
- canary scope;
- known failure taxonomy.

Acceptance gate:

- promotion is blocked if any required evidence is missing, stale, synthetic-only
  or not-for-production.

### P4A. Reliability, Drift And Tail-Case Gates

Goal: make model improvement durable across updates.

Work items:

- add cross-version metric drift checks;
- maintain high-risk tail-case replay suites;
- track action-mask false allow / false block drift;
- report uncertainty calibration drift;
- preserve boundary conditions in every release note;
- add failure replay cases whenever a planner or reviewer rejects a TWM output.

Acceptance gate:

- no candidate can move from review to controlled pilot if it regresses high-risk
  tail cases or legal constraint gates.

### Explicit Non-Goals For The Next Slice

- do not claim full future parcel geometry generation;
- do not claim broad FLUS/GeoSOS superiority from metric-specific wins;
- do not enable autonomous L3 self-evolution;
- do not promote GeoFM or causal claims without their own evidence gates;
- do not add new model complexity before the pilot package and evaluation bundle
  are stable.

## Implementation Checkpoint: P2A Dynamics Evaluation Bundle

Implemented and exposed as `territory_world_model.dynamics_evaluation_bundle.v1`.
The bundle now connects MREP trace, readiness, evaluation metrics, registry
metadata, split summary, evidence summary, promotion blockers and claim
boundaries without changing neural training behavior.

Engineering surfaces:

- service: `TerritoryWorldModelService.dynamics_evaluation_bundle`;
- API: `POST /api/twm/states/{id}/dynamics-evaluation-bundle`;
- tool: `twm_dynamics_evaluation_bundle`;
- tests: bundle schema, trace linkage, registry linkage, API and tool exposure.

Roadmap effect: P2A no longer needs more bundle plumbing before model-family
comparison. The blocker has shifted to making every model report bind to the
same pilot package and dataset hash.

## Implementation Checkpoint: P2A Pilot Package Manifest

Implemented and exposed as `territory_world_model.pilot_package.v1`. The pilot
package report is now the canonical envelope for P2B experiments. It links:

- state contract report;
- MREP trace and dataset snapshot hash;
- `trajectory_dataset_manifest.v1`;
- `dynamics_evaluation_bundle.v1`;
- production-data and same-case baseline gates;
- optional `lance_sidecar_manifest.v1` for derived vectors, embeddings and
  random-access trajectory windows.

Engineering surfaces:

- service: `TerritoryWorldModelService.pilot_package_report`;
- API: `POST /api/twm/states/{id}/pilot-package-report`;
- tool: `twm_pilot_package_report`;
- tests: pilot package schema, dataset hash linkage, sidecar storage boundary,
  missing same-case baseline blocker, API and tool exposure.

Roadmap effect: P2A can now serve as the fixed evidence envelope for algorithm
optimization. P2B should consume `pilot_package.v1`; it should not reopen the
package contract unless the first shootout exposes a concrete missing field.

## Next Algorithm Optimization Slice: P2B Shootout Bundle

The next TWM development task should implement
`dynamics_model_shootout_report.v1`.

Minimal scope:

- accept one `pilot_package_report` and a list of candidate reports;
- reject or downgrade candidates when `package_id`, `dataset_snapshot_hash`,
  split definition or baseline version does not match the package;
- compare deterministic/rule, persistence/Markov, MLP, hierarchical graph and
  spatiotemporal transformer families under the same target-head metrics;
- include optional FLUS/GeoSOS/MPC and GeoFM references only as gated
  comparators, not as implicit promotion evidence;
- emit a ranked but claim-bounded recommendation:
  `diagnostic_only`, `replay_ready`, `promotion_candidate_review` or `blocked`.

Acceptance gate:

- the report must explain why a model wins or loses by target head, constraint
  risk, utility ranking, uncertainty, action-mask errors, holdout split and
  same-case replay status;
- a candidate cannot outrank the baseline for promotion if it lacks the package
  hash, uses a different split, omits the same-case baseline, or only wins on
  scaffold/synthetic data.

## Implementation Checkpoint: P2B Shootout Bundle

Implemented and exposed as
`territory_world_model.dynamics_model_shootout_report.v1`. The report compares
candidate dynamics families under one fixed `pilot_package.v1` envelope and
keeps algorithm selection separate from production promotion.

Engineering surfaces:

- service: `TerritoryWorldModelService.dynamics_model_shootout_report`;
- API: `POST /api/twm/states/{id}/dynamics-model-shootout-report`;
- tool: `twm_dynamics_model_shootout_report`;
- tests: package binding, dataset hash mismatch blocker, split mismatch blocker,
  candidate ranking, claim boundary, API and tool exposure.

Current behavior:

- accepts one `pilot_package_report` and a list of candidate reports;
- optionally accepts `auto_trainers` plus the same `dataset` used by the pilot
  package, runs existing trainer contracts, and converts their train/evaluation
  outputs into shootout candidates;
- optionally accepts `include_baselines` and generates deterministic/rule,
  persistence and Markov transition baseline candidates under the same package;
- blocks or downgrades candidates with mismatched `package_id`,
  `dataset_snapshot_hash`, split summary, stale baseline or missing target-head
  metrics;
- ranks eligible candidates with a decision-oriented score using
  future-transition error, utility ranking, constraint error, uncertainty,
  action-mask errors, temporal/spatial holdout, seed stability and same-case
  planner lift;
- summarizes FoV stress tests by candidate and factor, and prevents candidates
  without FoV evidence from reaching `promotion_candidate_review`;
- emits claim-bounded recommendations:
  `diagnostic_only`, `replay_ready`, `promotion_candidate_review` or `blocked`.

Roadmap effect: P2B now has the comparison packet and required lower-bound
baselines needed to decide whether MLP, hierarchical graph or spatiotemporal
transformer candidates justify additional model complexity. The next algorithm
work should connect the shootout winner to P3A same-case planner replay and
make FoV matrices real-data-backed rather than synthetic-only.

## Implementation Checkpoint: P2C FoV Stress Summary

Implemented inside `territory_world_model.dynamics_model_shootout_report.v1` as
`fov_stress_summary`.

Current behavior:

- accepts per-candidate `fov_stress_tests`, `fov_stress_results` or
  `factors_of_variation` rows;
- summarizes candidate coverage, missing FoV count, factors and aggregate
  status;
- attaches candidate-level `fov_stress` and `promotion_limits`;
- limits candidates with missing FoV evidence to `replay_ready` even if same-case
  replay is present;
- allows candidates with FoV status `review` to remain
  `promotion_candidate_review`, because production promotion is still blocked by
  registry, replay and governance gates.

Roadmap effect: P2C has the first enforcement point in the P2B comparison
packet. The next FoV work should make generated matrices decision-metric-aware,
not merely coverage-aware.

## Implementation Checkpoint: P2C Auto FoV Stress Generation

Implemented inside `territory_world_model.dynamics_model_shootout_report.v1` as
`auto_fov_stress_generation`.

Current behavior:

- only runs when the caller explicitly sets `auto_fov_stress`,
  `generate_fov_stress`, `auto_fov_stress_generation` or
  `generate_fov_stress_tests`;
- reads the same pilot `dataset` or `training_dataset` used by the shootout and
  blocks generation if its dataset snapshot hash does not match the
  `pilot_package.v1` envelope;
- generates dataset-partition FoV rows for requested `fov_factors`, defaulting
  to region, year, rule version and evidence completeness;
- injects generated FoV rows only into candidate reports that did not already
  provide `fov_stress_tests`, `fov_stress_results` or
  `factors_of_variation`;
- reports generated row count, injected candidate count, existing FoV coverage
  and missing factors in the top-level shootout packet;
- when candidate predictions are supplied, enriches each generated FoV row with
  partition-level transition, constraint and utility errors, worst partition
  and max cross-partition metric deltas;
- marks generated FoV rows as `review` when partition metric deltas exceed
  caller-provided `fov_metric_thresholds`.

Roadmap effect: P2C now has a real-data-backed FoV coverage harness for the
first comparison packet. Region/year/rule/evidence partitions can now test
candidate degradation when predictions are available. The next step is to add
tail-case exemplars and loss-case IDs per factor so reviewer workflows can jump
from a weak partition to concrete cases.

## Roadmap Refresh: Next TWM Algorithm Optimization Backlog

Refresh date: 2026-07-02.

The current algorithm stack has moved from "can train/evaluate a candidate" to
"can compare candidates inside one evidence envelope." The remaining work should
therefore optimize the **decision simulator loop** rather than add model
families indiscriminately.

Current implemented foundation:

- `pilot_package.v1` is the experiment envelope;
- `dynamics_model_shootout_report.v1` compares candidate families under one
  package, dataset hash and split definition;
- deterministic/rule, persistence and Markov baselines can be auto-generated;
- MLP and hierarchical graph trainers can be auto-run through the shootout;
- FoV stress rows can be supplied manually or generated from dataset partitions;
- generated FoV rows can include partition-level metric deltas when candidate
  predictions are available;
- generated FoV rows can attach concrete tail examples with compact
  target-vs-prediction deltas for reviewer inspection;
- compact prediction traces now cover auto baselines and auto-trained MLP/graph
  candidates, making FoV diagnostics comparable across candidate families;
- `complexity_gain_gate.v1` prevents graph, transformer or GeoFM-style
  candidates from claiming superiority unless they improve cross-time,
  cross-space/FoV and decision metrics together;
- `same_case_planner_replay_report.v1` binds model selection to
  action-conditioned planning value, including improve/tie/lose cases;
- `dynamics_promotion_evidence_bundle.v1` binds shootout, replay, registry,
  rollback and failure cases into one review-only promotion packet;
- `dynamics_reliability_drift_report.v1` blocks cross-version regressions in
  legal feasibility, high-risk same-case losses and weak FoV partitions;
- `dynamics_regression_suite_manifest.v1` turns those loss cases into an active
  review-suite manifest for future replay, shootout and drift gates;
- `active_regression_suite_gate.v1` now lets shootout, same-case replay and
  reliability drift reports enforce that active suite before stronger promotion
  language is allowed;
- `dynamics_geospatial_hard_negative_mining_report.v1` clusters active-suite
  failures by geospatial governance axes and turns them into replay/sampling
  diagnostics;
- `dynamics_canary_failure_memory_protocol.v1` binds suite version, hard-negative
  mining, canary scope, lakehouse table plan and registry pointer into one
  review-only protocol;
- `dynamics_hard_negative_replay_scheduler_report.v1` turns failure-memory
  clusters and sampling weights into a review-only replay schedule bound to the
  same suite, dataset snapshot and failure-memory version;
- `dynamics_failure_memory_materialization.v1` writes protocol-bound
  failure-memory artifacts as local parquet lakehouse boundary files for
  regression cases, hard-negative clusters, canary scope, replay schedules and
  registry pointers;
- `dynamics_reviewer_feedback_ingestion_report.v1` converts audited reviewer
  corrections into regression-suite proposals without automatic activation.
- `dynamics_accepted_feedback_suite_update_report.v1` converts explicitly
  accepted reviewer-feedback proposals into a next-version regression suite
  manifest while retaining reviewer, evidence, region, rule and action
  provenance.
- `dynamics_canary_replay_execution_report.v1` resolves scheduled canary replay
  results against the same failure-memory version and emits cluster/risk drift
  dashboard inputs with rollback evidence.
- `dynamics_failure_memory_registration_plan.v1` generates Iceberg table DDL,
  PostGIS index specs and registry commit preconditions for failure-memory
  artifacts without executing registration or activation.

Main gaps that still block stronger algorithm claims:

- failure-memory durability now has local parquet artifacts and registration
  plans, but catalog execution, PostGIS index creation and registry
  commit/activation are still not implemented;
- hard-negative replay schedules can now be executed into review-only canary
  evidence, but durable replay-result persistence and trainer/evaluation
  scheduler integration are still missing;
- reviewer-feedback proposals can now be accepted into a next-version suite
  manifest, but suite activation, registry commit and replay re-materialization
  remain explicit follow-up steps;
- canary replay execution now emits drift dashboard inputs, but production
  dashboard serving, alert routing and registry promotion automation are still
  missing;
- no L3-style self-evolution claim is allowed until regression-suite reuse,
  canary evidence and rollback audits are proven on pilot feedback.

### P2D. FoV Tail-Case And Loss-Case Harness

Goal: turn FoV stress rows from aggregate diagnostics into reviewer-actionable
failure evidence.

Current status: first slice implemented for generated FoV rows with candidate
predictions. Tail cases now cover transition, constraint, utility and
action-mask false allow / false block failures. Remaining P2D work should focus
on richer reviewer summaries and on auto-generated candidates via P2E prediction
traces.

Implementation target:

- extend generated FoV rows with `tail_examples`:
  - `example_id`;
  - factor and partition value;
  - transition error;
  - constraint error;
  - utility error;
  - split;
  - source lineage / not-for-production flags;
  - compact target-vs-prediction deltas.
- expose `loss_case_count` and `tail_case_count` in
  `auto_fov_stress_generation`;
- keep payload size controlled with `max_fov_tail_examples`, defaulting to a
  small reviewer-friendly number such as 5 per factor.

Acceptance gate:

- every FoV row with `status=review` or `status=blocked` must include at least
  one concrete example ID when predictions are available;
- action-mask failures must identify the example, expected mask, predicted mask
  and false-allow / false-block class;
- synthetic or not-for-production examples must remain labeled and cannot
  upgrade robustness claims.

### P2E. Prediction Trace Preservation For Auto Candidates

Goal: make auto-generated baselines and auto-trained candidates eligible for the
same FoV metric and tail-case diagnostics as manually supplied candidates.

Implementation target:

- add compact `prediction_trace` summaries to auto baseline and auto trainer
  candidate reports without dumping unbounded prediction payloads by default;
- support an opt-in `include_candidate_predictions` or
  `prediction_trace_mode=compact|full|none`;
- preserve enough per-example values for:
  - future-state latent error;
  - constraint probability error;
  - utility delta error;
  - action-mask false allow / false block;
  - FoV tail-case ranking.

Acceptance gate:

- deterministic/rule, persistence, Markov, MLP and graph candidates can all
  produce comparable FoV metric deltas under the same dataset snapshot;
- full prediction payload export remains opt-in to avoid oversized API/tool
  responses.

### P2F. Complexity-Gain Gate For Model Families

Goal: justify graph and transformer complexity with reproducible gains, not
model-family preference.

Implementation target:

- add a `complexity_gain_gate` section to the shootout report;
- compare each non-baseline model against:
  - deterministic/rule baseline;
  - persistence baseline;
  - Markov baseline;
  - MLP multi-head baseline;
  - best simpler eligible candidate.
- report gain by metric:
  - future transition error;
  - spatial holdout error;
  - temporal holdout error;
  - FoV partition degradation;
  - action-mask false allow / false block;
  - planner lift where replay exists.

Acceptance gate:

- graph or transformer candidates remain `replay_ready` unless they beat the
  MLP and simple baselines on at least temporal holdout, one spatial/FoV axis
  and one decision metric;
- if gains are metric-specific, the report must preserve metric-specific
  wording and avoid broad "model family superiority" claims.

### P3A. Same-Case Planner Replay From Shootout Winner

Goal: connect model-selection evidence to planning value evidence.

Implementation target:

- add a replay packet that consumes:
  - `pilot_package_report`;
  - `dynamics_model_shootout_report`;
  - selected candidate ID or top eligible candidate;
  - baseline planner artifacts.
- report:
  - legal-feasible top-k precision;
  - blocked-action recall;
  - false allow and false block rates;
  - planner regret against human/rule-only baseline;
  - ranking lift;
  - review workload impact;
  - loss cases.

Acceptance gate:

- no candidate can move beyond `promotion_candidate_review` without same-case
  replay evidence;
- replay output must show where TWM improves, ties and loses.

### P3B. Promotion Candidate Evidence Bundle

Goal: collapse scattered promotion evidence into one auditable bundle.

Implementation target:

- add `dynamics_promotion_evidence_bundle.v1` linking:
  - pilot package;
  - shootout report;
  - FoV stress and tail cases;
  - same-case planner replay;
  - model registry entry;
  - causal/evidence diagnostics;
  - rollback target;
  - claim boundary and non-goals.

Acceptance gate:

- the bundle status is `blocked` if any required evidence is stale, missing,
  synthetic-only, package-mismatched or not tied to rollback metadata.

### P4A. Reliability, Drift And Regression Gates

Goal: make algorithm improvement durable across model and rule updates.

Implementation target:

- add cross-version metric drift reports for:
  - transition error;
  - utility ranking;
  - constraint calibration;
  - action-mask false allow / false block;
  - FoV weak partitions;
  - high-risk tail cases.
- maintain a small replay suite of known failure examples from P2D/P3A.

Acceptance gate:

- a candidate cannot be promoted if it regresses legal constraints, high-risk
  tail cases or previously accepted FoV partitions.

## Updated 30 / 60 / 90 Day Algorithm Execution View

### Next 30 Days

- use the new hard-negative replay scheduler to drive candidate shootout,
  same-case replay and reliability-drift checks under one failure-memory
  version;
- define an accepted-proposal workflow for adding reviewer-feedback proposals to
  a new suite version;
- keep all results claim-bounded to `replay_ready` or
  `promotion_candidate_review`.

### Next 60 Days

- persist versioned regression suites in the lakehouse/registry boundary so
  failures survive service restarts and model-release cycles;
- add reviewer feedback ingestion so rejected or corrected TWM outputs become
  candidate replay cases after human audit;
- verify whether model improvements survive the active failure suite, not only
  average temporal/spatial/FoV holdout metrics.

### Next 90 Days

- define the first controlled canary protocol and drift dashboard;
- nominate at most one controlled pilot candidate whose shootout, replay,
  promotion bundle, drift gate and active regression suite all reference the
  same package and dataset snapshot;
- start a review-only L3 feedback-loop audit in which new pilot feedback can
  propose, but not autonomously activate, model updates;
- keep autonomous L3 evolution disabled until replay, rollback and drift gates
  are audited on production pilot feedback.

## Implementation Checkpoint: P2D FoV Tail-Case Slice

Implemented inside `territory_world_model.dynamics_model_shootout_report.v1` as
tail-case enrichment for generated FoV stress rows.

Current behavior:

- when generated FoV rows are marked `review` by partition metric deltas, the
  report can attach `tail_examples`;
- each tail example includes:
  - `example_id`;
  - factor and partition value;
  - split;
  - transition, constraint and utility errors where available;
  - action-mask false allow / false block class where available;
  - compact target-vs-prediction deltas;
  - not-for-production flag;
  - compact source lineage;
- top-level `auto_fov_stress_generation` reports `tail_case_count` and
  `loss_case_count`, plus `action_mask_loss_case_count`;
- output volume is controlled by `max_fov_tail_examples`.

Roadmap effect: P2D now gives reviewers concrete weak-partition examples for
the first auto-generated FoV path. The next algorithm step should preserve
prediction traces for auto-generated baselines and trainers through P2E, then
feed the same loss cases into P3A same-case planner replay.

## Implementation Checkpoint: P2E Auto-Baseline Prediction Trace Slice

Implemented inside `territory_world_model.dynamics_model_shootout_report.v1` for
auto-generated deterministic/rule, persistence and Markov baseline candidates.

Current behavior:

- auto baseline candidates now include `prediction_trace.v1`;
- `prediction_trace_mode` supports `compact`, `full` and `none`;
- compact mode preserves only the target-head fields needed for FoV diagnostics:
  future latent state, constraint probability, utility delta and action mask;
- generated FoV rows can use auto-baseline prediction traces to produce
  partition metric summaries without requiring manually supplied candidate
  predictions.

Roadmap effect: P2E now makes simple baselines first-class participants in FoV
metric and tail-case diagnostics. The next P2E slice should preserve compact
prediction traces for auto-trained MLP and hierarchical graph candidates, so
all model families can be compared under the same FoV/tail-case harness.

## Implementation Checkpoint: P2E Auto-Trainer Prediction Trace Slice

Implemented inside `territory_world_model.dynamics_model_shootout_report.v1` for
auto-trained MLP and hierarchical graph dynamics candidates.

Current behavior:

- auto-trained candidates now include `prediction_trace.v1`;
- compact mode preserves the same target-head fields as auto baselines:
  future latent state, constraint probability, utility delta and action mask;
- generated FoV rows can use auto-trainer prediction traces to produce
  partition metric summaries and tail examples without requiring manually
  supplied candidate predictions;
- auto baselines, manual candidates and auto-trained candidates now share the
  same FoV/tail-case diagnostic path.

Roadmap effect: P2E closes the main symmetry gap in the P2B/P2C comparison
packet. The next algorithm slice should add P2F `complexity_gain_gate`, so graph
and transformer families must justify their complexity against deterministic,
persistence, Markov and MLP alternatives under the same evidence envelope.

## Implementation Checkpoint: P2F Complexity-Gain Gate

Implemented inside `territory_world_model.dynamics_model_shootout_report.v1` as
a promotion-boundary gate for complex dynamics families.

Current behavior:

- graph, transformer and GeoFM-style dynamics families are treated as complex
  candidates rather than automatically better candidates;
- each complex candidate is compared against simpler eligible candidates from
  the same pilot package, including MLP and simpler baselines when present;
- the gate reports metric-specific gains for future transition error, temporal
  holdout, spatial holdout, FoV partition degradation, action-mask false
  allow/block rates, utility ranking and planner lift;
- passing complexity requires all three geospatial-world-model axes:
  temporal holdout gain, one spatial/FoV gain, and one decision-metric gain;
- if a complex model only improves a generic future-state metric but fails the
  cross-time, cross-space or planner-decision axes, the candidate receives the
  `complexity_gain_gate` promotion limit and remains `replay_ready`.

Roadmap effect: P2F converts model-family comparison from a generic ML
leaderboard into an action-conditioned geospatial world-model discipline. More
expressive architectures are useful only when they improve reproducible
spatiotemporal generalization and planning behavior under the same evidence
envelope.

## Implementation Checkpoint: P3A Same-Case Planner Replay Packet

Implemented as `territory_world_model.same_case_planner_replay_report.v1` with
service, API route and toolset entry points.

Current behavior:

- consumes the same `pilot_package_report` and
  `dynamics_model_shootout_report` used for model-family selection;
- selects either the payload-selected candidate or the top eligible shootout
  candidate;
- binds replay interpretation to the same package ID, dataset snapshot hash and
  split summary;
- scores same-case planning behavior with legal-feasible top-k precision,
  blocked-action recall, false allow / false block rates, planner regret
  reduction, ranking lift and review workload impact;
- preserves case-level `improve`, `tie` and `lose` outcomes plus compact
  `loss_cases` for action-mask and planner-regret feedback loops;
- caps the claim boundary at `promotion_candidate_review`, keeping production
  and registry promotion claims out of this packet.

Roadmap effect: P3A connects TWM model selection to action-conditioned
geospatial governance value. A candidate is no longer evaluated only by future
state fit or model-family rank; it must show how it changes decisions on the
same cases, including where it improves, ties and loses against a rule/human
baseline.

## Implementation Checkpoint: P3B Promotion Evidence Bundle

Implemented as `territory_world_model.dynamics_promotion_evidence_bundle.v1`
with service, API route and toolset entry points.

Current behavior:

- links `pilot_package_report`, `dynamics_model_shootout_report`,
  `same_case_planner_replay_report`, `dynamics_model_registry_report`,
  rollback evidence, FoV tail cases and optional canary scope into one packet;
- validates that the selected candidate, package ID, dataset snapshot hash and
  split summary remain consistent across pilot, shootout and same-case replay;
- requires registry promotion evidence, required registry metadata and rollback
  metadata before the bundle can reach review status;
- extracts FoV tail cases and same-case loss cases so weak partitions and
  decision failures travel with the promotion candidate;
- blocks the bundle when replay, registry, rollback or package-binding evidence
  is missing, stale or mismatched;
- caps the claim at controlled pilot review and explicitly prevents production
  activation language.

Roadmap effect: P3B closes the first evidence loop for TWM as a geospatial world
model. A candidate is not just a high-scoring dynamics model; it must carry the
same spatial-temporal data snapshot, same-case decision replay, weak-area loss
cases, registry lineage and rollback path before promotion language is allowed.

## Implementation Checkpoint: P4A Reliability, Drift And Regression Gates

Implemented as `territory_world_model.dynamics_reliability_drift_report.v1`
with service, API route and toolset entry points.

Current behavior:

- compares a previous promotion evidence bundle with a candidate promotion
  evidence bundle under the same package and dataset snapshot;
- reports cross-version deltas for action-mask false allow / false block,
  ranking lift, planner-regret reduction, FoV tail cases, same-case loss cases
  and high-risk loss cases;
- blocks candidates when legal feasibility regresses, FoV weak partitions
  increase, high-risk replay losses increase, ranking lift drops below the
  configured threshold or rollback evidence is no longer passing;
- emits compact regression cases from new same-case loss cases and FoV tail
  cases so the failure examples can be fed back into P2D/P3A suites;
- caps the result at controlled pilot candidate review and never treats drift
  pass/fail as production activation.

Roadmap effect: P4A turns TWM improvement into a cross-version reliability
discipline. A geospatial world model can become more expressive only if it does
not regress legal constraints, weak spatial partitions or previously accepted
high-risk replay cases.

## Implementation Checkpoint: P4B Regression Suite Manifest

Implemented as
`territory_world_model.dynamics_regression_suite_manifest.v1` with service, API
route and toolset entry points.

Current behavior:

- collects compact cases from `dynamics_promotion_evidence_bundle.v1`
  same-case loss cases and FoV tail cases;
- collects new regression cases emitted by
  `dynamics_reliability_drift_report.v1`;
- accepts explicit manual regression cases for legal-frontier and reviewer
  feedback scenarios;
- de-duplicates cases by stable case/example ID while preserving the first
  observed case type;
- reports case-type counts, high/critical risk counts, package/dataset binding
  and required downstream consumers;
- caps the claim boundary at
  `regression_suite_manifest_is_replay_contract_not_training_ground_truth`.

Roadmap effect: P4B gives TWM a geospatial world-model memory. The system no
longer treats model improvement as average-metric progress alone; it must
remember weak regions, weak evidence partitions, rule-boundary failures and
same-case decision losses, then replay them before stronger promotion language
is allowed. This is a TWM-specific algorithmic direction because the failure
memory is indexed by spatial partition, policy/rule context, action feasibility
and evidence completeness, not just by generic prediction error.

## Implementation Checkpoint: P4C Active Regression-Suite Enforcement

Implemented as `territory_world_model.active_regression_suite_gate.v1` inside
the existing shootout, same-case replay and reliability drift reports.

Current behavior:

- `dynamics_model_shootout_report.v1` accepts
  `dynamics_regression_suite_manifest.v1` and downgrades candidates to
  `replay_ready` when their candidate report does not cover required active
  suite case IDs;
- `same_case_planner_replay_report.v1` blocks the replay promotion gate when
  replay cases omit active legal-frontier, weak-region or FoV-tail cases;
- `dynamics_reliability_drift_report.v1` blocks candidate promotion decisions
  when the candidate bundle does not prove active-suite replay coverage;
- all gates keep package ID and dataset snapshot binding aligned with the
  manifest;
- the suite remains a replay contract and explicitly does not become training
  ground truth.

Roadmap effect: P4C makes TWM's failure memory operational. The breakthrough is
not just storing loss cases; the world model now has a geospatial governance
invariant: future model-family wins, planner replay gains and cross-version
drift passes are insufficient unless known weak geographies, rule-frontier
actions and evidence-completeness failures have been replayed under the same
package snapshot.

## Implementation Checkpoint: P4D Geospatial Hard-Negative Mining

Implemented as
`territory_world_model.dynamics_geospatial_hard_negative_mining_report.v1` with
service, API route and toolset entry points.

Current behavior:

- consumes `dynamics_regression_suite_manifest.v1` as the source of active
  failure cases;
- enriches each case with geospatial governance dimensions such as
  `region_code`, `rule_version`, `evidence_gap`, `action_type`, `loss_type` and
  `case_type`;
- clusters failures by those axes and ranks clusters by high/critical risk,
  false-allow severity, FoV-tail status and case count;
- emits priority-weighted replay/sampling diagnostics per case;
- reports retraining target axes while preserving the boundary that these cases
  are diagnostics, not automatically promoted training ground truth.

Roadmap effect: P4D turns TWM's active failure memory into a geospatial
hard-negative mining layer. This is the point where TWM starts behaving less
like a generic model leaderboard and more like a governance world model: weak
counties, weak rule versions, evidence gaps and risky action types become
explicit targets for replay, sampling and review diagnostics.

## Implementation Checkpoint: P5A Canary And Failure-Memory Protocol

Implemented as
`territory_world_model.dynamics_canary_failure_memory_protocol.v1` with service,
API route and toolset entry points.

Current behavior:

- binds an active regression suite, hard-negative mining report and canary scope
  into one failure-memory version;
- derives a stable `failure-memory:<suite_id>:<hash>` version and registry key;
- defines lakehouse table names for regression-suite cases, hard-negative
  clusters, canary scopes and replay results;
- defines required keys that preserve geospatial governance context:
  state version, dataset snapshot, case ID, region, rule version, evidence gap
  and action type;
- requires shootout, same-case replay, drift, hard-negative mining and rollback
  evidence to resolve the same failure-memory version before stronger promotion
  language;
- remains protocol-only and writes no Iceberg/PostGIS/registry rows yet.

Roadmap effect: P5A gives TWM a versioned failure-memory and canary protocol
without crossing into autonomous L3 activation. This is the governance bridge:
known weak geographies and evidence/rule/action failure modes can now be named,
versioned and required by future reports, while actual persistence and model
activation remain review-gated.

## Implementation Checkpoint: P5B Reviewer Feedback Ingestion

Implemented as
`territory_world_model.dynamics_reviewer_feedback_ingestion_report.v1` with
service, API route and toolset entry points.

Current behavior:

- accepts audited reviewer feedback rows and ignores draft or unaudited rows;
- converts model-vs-corrected decision differences into proposal-only
  regression cases, including false-allow and false-block classes;
- preserves reviewer provenance, review task ID, evidence IDs, region, rule
  version and action type in `source_lineage`;
- de-duplicates proposals against the active suite's existing case IDs;
- emits an activation policy that forbids automatic suite update, automatic
  training label creation, production activation and autonomous L3 evolution.

Roadmap effect: P5B connects human governance feedback to TWM's geospatial
failure memory without weakening the evidence boundary. Reviewer corrections can
now become candidate suite additions, but they still require explicit acceptance
before they affect active replay suites or model training diagnostics.

## Implementation Checkpoint: P5C Hard-Negative Replay Scheduler

Implemented as
`territory_world_model.dynamics_hard_negative_replay_scheduler_report.v1` with
service, API route and toolset entry points.

Current behavior:

- consumes the geospatial hard-negative mining report and canary
  failure-memory protocol;
- binds every schedule to `failure_memory_version_id`, active suite ID, package
  ID and dataset snapshot hash;
- converts hard-negative cluster membership and case sampling weights into a
  deterministic replay order;
- preserves per-case `cluster_ids`, sampling weight and cluster priority so
  weak counties, rule versions, evidence gaps and action types remain visible;
- requires candidate shootout, same-case planner replay and reliability-drift
  reports for scheduled cases;
- remains report-only: no replay jobs are started, no replay result rows are
  written and no synthetic training ground truth is created.

Roadmap effect: P5C turns TWM's failure memory from a static diagnostic into a
geospatial replay queue. This is specific to a geospatial world model: the
scheduler does not sample generic errors uniformly, but promotes spatial,
rule/evidence and action-conditioned failure clusters into the next model
comparison loop. The boundary is still strict: it schedules review obligations,
not model retraining or autonomous activation.

## Implementation Checkpoint: P5D Durable Failure-Memory Materialization

Implemented as
`territory_world_model.dynamics_failure_memory_materialization.v1` with service,
API route and toolset entry points.

Current behavior:

- consumes active regression suite manifest, hard-negative mining report,
  canary failure-memory protocol and replay scheduler report;
- writes local parquet artifacts for `regression_suite_cases`,
  `hard_negative_clusters`, `canary_scopes`, `replay_schedules` and
  `registry_pointers`;
- preserves `failure_memory_version_id`, suite ID, dataset snapshot hash and
  package ID in every artifact row;
- stores geospatial governance columns directly in the durable rows: region,
  rule version, evidence gap, action type, cluster axis/value and targeting
  policy;
- emits a manifest and readiness flags for later Iceberg/registry registration;
- explicitly keeps model activation, canary execution, synthetic training label
  creation and L3 self-evolution outside this slice.

Roadmap effect: P5D makes TWM's geospatial failure memory durable. The
important algorithmic shift is that future model comparisons can replay against
the same versioned spatial/rule/evidence/action failure memory, rather than a
transient in-process report. This supports genuine geospatial world-model
iteration while keeping the governance boundary intact.

## Implementation Checkpoint: P5E Accepted Reviewer-Feedback Suite Update

Implemented as
`territory_world_model.dynamics_accepted_feedback_suite_update_report.v1` with
service, API route and toolset entry points.

Current behavior:

- consumes the active regression suite manifest and reviewer-feedback ingestion
  report;
- accepts only proposal IDs explicitly listed in `accepted_proposal_ids`;
- generates a next-version `dynamics_regression_suite_manifest.v1` with status
  `active_review_suite_proposal`;
- preserves existing suite cases and appends accepted reviewer-feedback cases;
- carries reviewer ID, review task ID, evidence IDs, region, rule version,
  evidence/action context and human acceptance metadata into `source_lineage`;
- blocks automatic suite activation, automatic training-ground-truth creation,
  automatic model activation and L3 self-evolution claims.

Roadmap effect: P5E closes the human feedback loop without weakening TWM's
evidence boundary. The geospatial world model can now turn audited county/rule/
evidence/action failures into a versioned failure-memory suite, but those cases
remain replay obligations and governance memory, not training labels.

## Implementation Checkpoint: P5F Canary Replay Execution And Drift Dashboard Inputs

Implemented as
`territory_world_model.dynamics_canary_replay_execution_report.v1` with
service, API route and toolset entry points.

Current behavior:

- consumes canary failure-memory protocol and hard-negative replay scheduler
  report;
- binds replay execution to the same `failure_memory_version_id`, suite ID,
  dataset snapshot and schedule ID;
- accepts candidate replay observations and compares candidate vs target
  decisions case by case;
- classifies false allow, false block, pass and missing replay outcomes;
- aggregates failed replay cases by geospatial hard-negative cluster and risk
  level for drift dashboard inputs;
- preserves rollback evidence and blocks automatic model/registry activation.

Roadmap effect: P5F gives TWM a controlled canary evidence layer. This is where
the geospatial world model starts checking candidate behavior against durable
spatial/rule/evidence/action failure memory, not just aggregate validation
metrics. The output is still review evidence and dashboard input, not a
production scheduler or autonomous promotion system.

## Implementation Checkpoint: P5G Iceberg/PostGIS Registration Plan

Implemented as
`territory_world_model.dynamics_failure_memory_registration_plan.v1` with
service, API route and toolset entry points.

Current behavior:

- consumes failure-memory materialization and canary replay execution reports;
- generates Iceberg table specs for all failure-memory artifacts;
- embeds `failure_memory_version_id`, suite ID and dataset snapshot hash into
  each table's version-resolution contract;
- generates PostGIS index specs for geospatial governance query axes such as
  region, rule version, evidence gap, action type, cluster axis/value and
  registry key;
- emits registry commit preconditions that require rollback evidence and block
  automatic registry/model activation;
- remains a plan only: no DDL, PostGIS index or registry commit is executed.

Roadmap effect: P5G makes TWM's failure memory query-addressable. The
geospatial world model now has a concrete bridge from durable artifacts to
spatial/rule/evidence/action replay analysis, while still preserving human
review gates before catalog execution or model promotion.

## Benchmark Checkpoint: 2026-07-02 Topology-Stability Guard

Implemented a train-only topology-stability guarded Dynamic World candidate:
`twm_topology_stability_guarded_persistence_forecast_demand`.

What changed:

- penalizes non-persistence changes inside train-stable same-class interiors;
- preserves or supports changes near observed train-change frontiers;
- supports target-class neighborhood expansion from the current spatial state;
- allocates the result through persistence forecast demand so target demand
  remains count-conserving;
- records `training_topology_stability` diagnostics and an explicit
  `topology_stability_guard` component flag.

100-case reused-FLUS Dynamic World recompute:

- output: `/private/tmp/twm_dynamic_world_flus_topology_verify_2026-07-02.json`;
- status: pass;
- case count: 100;
- mean change FoM: 0.205632;
- mean change F1: 0.338643;
- mean overall accuracy: 0.897029;
- mean kappa: 0.761089;
- mean macro-F1: 0.472769;
- total target-demand absolute error: 0.

Relative to the previous current top
`twm_pair_false_alarm_guarded_persistence_forecast_demand`:

- change FoM improved by +0.011648;
- change F1 improved by +0.016242;
- overall accuracy improved by +0.001771;
- kappa improved by +0.004305;
- macro-F1 improved by +0.005644.

Relative to `flus_console_direct`:

- mean change FoM delta: +0.054676;
- wins/losses by change FoM: 71/29;
- sign-test p-value for change FoM: 3.216001529566633e-05;
- mean change F1 delta: +0.084304;
- mean overall accuracy delta: -0.021367;
- mean kappa delta: -0.049385;
- mean macro-F1 delta: -0.032757.

Promotion boundary:

- promote this candidate as the current 100-case Dynamic World change-detection
  leader over the previous pair false-alarm guarded persistence candidate;
- claim only metric-specific superiority over FLUS/GeoSOS-style baselines:
  change FoM and change F1 on the evaluated slice;
- do not claim broad TWM superiority over FLUS, because OA, kappa and macro-F1
  still trail the FLUS baseline;
- the inherited benchmark caveat around holdout-aware `valid` masks is resolved
  by the strict valid-mask protocol checkpoint below.

## Benchmark Checkpoint: 2026-07-02 Strict Valid-Mask Protocol

Implemented prediction/evaluation valid-mask separation for the Dynamic World /
FLUS comparison runner and the public land-cover benchmark runner.

Protocol change:

- prediction-time mask uses train start and train end class/nodata validity;
- evaluation-time mask additionally requires holdout class/nodata validity;
- FLUS landuse/restrict/probability packaging and TWM `model_inputs["valid"]`
  use the prediction-time mask;
- pixel metrics and report `valid_cell_count` use the evaluation-time mask;
- reports now expose `prediction_valid_cell_count`,
  `evaluation_valid_cell_count` and `mask_protocol`.

Current 100-case Dynamic World manifest diagnostic:

- case count: 100;
- cases where prediction/evaluation masks differ: 0;
- total prediction-valid cells: 3,182,460;
- total evaluation-valid cells: 3,182,460;
- total prediction-valid but evaluation-invalid cells: 0.

Strict-mask 100-case reused-FLUS recompute:

- output:
  `/private/tmp/twm_dynamic_world_flus_topology_strict_mask_verify_2026-07-02.json`;
- status: pass;
- topology candidate mean change FoM: 0.205632;
- topology candidate mean change F1: 0.338643;
- topology candidate mean overall accuracy: 0.897029;
- topology candidate mean kappa: 0.761089;
- topology candidate mean macro-F1: 0.472769;
- topology delta vs previous pair false-alarm candidate:
  +0.011648 change FoM, +0.016242 change F1, +0.001771 OA,
  +0.004305 kappa and +0.005644 macro-F1;
- topology delta vs FLUS remains metric-specific:
  +0.054676 mean change FoM and +0.084304 mean change F1, but
  -0.021367 OA, -0.049385 kappa and -0.032757 macro-F1.

Roadmap effect: the previous holdout-availability caveat is now removed from
prediction-time mechanics for these benchmark runners. The next algorithmic
target is no longer protocol cleanup; it is a genuine map-level gap reduction
task under the stricter protocol, especially OA/kappa/macro-F1 without giving
back the change FoM gain.

## Benchmark Checkpoint: 2026-07-02 Topology False-Alarm Churn Guard

Implemented a train-only Pareto-balanced topology candidate:
`twm_topology_stability_false_alarm_churn_guarded_persistence_forecast_demand`.

What changed:

- starts from the topology-stability score field;
- keeps the persistence forecast-demand projection and demand conservation;
- uses train-replay false-alarm precision to adapt the count-neutral churn
  fraction between 0.5 and 0.9;
- records both topology diagnostics and
  `territory_world_model.train_replay_false_alarm_guard.v1` churn diagnostics;
- remains holdout-label free in training and allocation.

100-case strict-mask reused-FLUS recompute:

- output:
  `/private/tmp/twm_dynamic_world_flus_topology_churn_guard_verify_2026-07-02.json`;
- status: pass;
- mean change FoM: 0.203663;
- mean change F1: 0.335771;
- mean overall accuracy: 0.897726;
- mean kappa: 0.762791;
- mean macro-F1: 0.475089;
- total target-demand absolute error: 0.

Relative to the fixed-churn topology candidate:

- change FoM: -0.001969;
- change F1: -0.002872;
- overall accuracy: +0.000697;
- kappa: +0.001702;
- macro-F1: +0.002320;
- predicted changes: 234,738 vs 238,684;
- change false alarms: 148,281 vs 151,231;
- change precision: 0.354428 vs 0.350661;
- change recall: 0.330068 vs 0.336702.

Relative to FLUS:

- mean change FoM delta: +0.052708;
- mean change F1 delta: +0.081432;
- wins/losses by change FoM: 70/30;
- mean overall accuracy delta: -0.020671;
- mean kappa delta: -0.047682;
- mean macro-F1 delta: -0.030437.

Promotion boundary:

- keep `twm_topology_stability_guarded_persistence_forecast_demand` as the
  change-FoM leader;
- promote
  `twm_topology_stability_false_alarm_churn_guarded_persistence_forecast_demand`
  as the balanced topology candidate for OA/kappa/macro-F1 gap reduction;
- still do not claim broad TWM superiority over FLUS, because the map-level
  metrics remain below FLUS even though the gap narrowed.

## Benchmark Checkpoint: 2026-07-02 Strict Topology False-Alarm Churn Guard

Implemented a stricter train-only map-gap candidate:
`twm_topology_stability_strict_false_alarm_churn_guarded_persistence_forecast_demand`.

What changed relative to the balanced topology churn guard:

- keeps the same topology-stability score and persistence demand projection;
- raises train-replay precision target from 0.45 to 0.60;
- uses precision floor 0.30 and minimum churn fraction 0.45;
- preserves explicit `uses_holdout_labels_for_training = false`;
- records `strict_train_replay_false_alarm_churn_guard` in component flags.

100-case strict-mask reused-FLUS recompute:

- output:
  `/private/tmp/twm_dynamic_world_flus_topology_strict_churn_guard_verify_2026-07-02.json`;
- status: pass;
- mean change FoM: 0.194707;
- mean change F1: 0.323252;
- mean overall accuracy: 0.900897;
- mean kappa: 0.770375;
- mean macro-F1: 0.483463;
- total target-demand absolute error: 0.

Relative to the balanced topology churn guard:

- change FoM: -0.008956;
- change F1: -0.012519;
- overall accuracy: +0.003171;
- kappa: +0.007584;
- macro-F1: +0.008374;
- predicted changes: 214,572 vs 234,738;
- change false alarms: 134,101 vs 148,281;
- change precision: 0.364636 vs 0.354428;
- change recall: 0.302717 vs 0.330068.

Relative to fixed-churn topology:

- overall accuracy: +0.003868;
- kappa: +0.009286;
- macro-F1: +0.010694;
- change FoM remains above FLUS by +0.043752.

Promotion boundary:

- keep fixed-churn topology as the change-detection leader;
- keep balanced topology churn guard as the middle Pareto candidate;
- promote strict topology churn guard as the current map-gap reduction leader;
- still do not claim broad superiority over FLUS, but the OA/kappa/macro-F1 gap
  is now materially smaller while change FoM and change F1 remain above FLUS.

## Benchmark Checkpoint: 2026-07-02 Topology Support Strict Churn Guard

Implemented a train-only spatial-support variant:
`twm_topology_support_strict_false_alarm_churn_guarded_persistence_forecast_demand`.

What changed:

- adds `territory_world_model.train_unsupported_transition_pressure_score_guard.v1`;
- penalizes non-persistence target assignments that are neither near observed
  train-change frontiers nor near the current target-class neighborhood;
- keeps the same strict false-alarm churn guard as the previous strict
  candidate, so any gain comes from geospatial support ranking rather than a
  lower change budget;
- preserves demand conservation and holdout-free training metadata.

100-case strict-mask reused-FLUS recompute:

- output:
  `/private/tmp/twm_dynamic_world_flus_topology_support_strict_churn_verify_2026-07-02.json`;
- status: pass;
- mean change FoM: 0.194893;
- mean change F1: 0.323515;
- mean overall accuracy: 0.900930;
- mean kappa: 0.770457;
- mean macro-F1: 0.484252;
- total target-demand absolute error: 0.

Relative to strict topology churn guard:

- change FoM: +0.000186;
- change F1: +0.000263;
- overall accuracy: +0.000033;
- kappa: +0.000082;
- macro-F1: +0.000789;
- predicted changes: unchanged at 214,572;
- change hits: 80,538 vs 80,471;
- change false alarms: 134,034 vs 134,101;
- change precision: 0.364995 vs 0.364636;
- change recall: 0.302915 vs 0.302717.

Relative to FLUS:

- mean change FoM delta: +0.043937;
- mean change F1 delta: +0.069176;
- mean overall accuracy delta: -0.017466;
- mean kappa delta: -0.040016;
- mean macro-F1 delta: -0.021274.

Promotion boundary:

- promote this support variant as the current map-gap reduction leader because
  it improves every tracked metric over the strict churn guard without reducing
  predicted change budget;
- treat the improvement as incremental, not breakthrough-scale;
- next work should look beyond scalar churn pressure toward class-pair and
  region-specific topology support, because global support pressure is now
  producing only small marginal gains.

## Benchmark Checkpoint: 2026-07-02 Pair Topology Support Strict Churn Guard

Implemented a train-only class-pair spatial-support variant:
`twm_pair_topology_support_strict_false_alarm_churn_guarded_persistence_forecast_demand`.

What changed:

- adds `territory_world_model.train_pair_unsupported_transition_pressure_score_guard.v1`;
- uses train-replay source->target false-alarm metrics to identify unreliable
  transition pairs, then penalizes only unsupported cells for those pairs;
- stacks on the global topology-support guard and the strict false-alarm churn
  guard, so the test isolates finer geospatial ranking rather than a new demand
  or churn budget;
- preserves demand conservation and keeps holdout labels out of training.

100-case strict-mask reused-FLUS recompute:

- output:
  `/private/tmp/twm_dynamic_world_flus_pair_topology_support_strict_churn_verify_2026-07-02.json`;
- status: pass;
- mean change FoM: 0.194927;
- mean change F1: 0.323562;
- mean overall accuracy: 0.900939;
- mean kappa: 0.770485;
- mean macro-F1: 0.484297;
- total target-demand absolute error: 0.

Relative to global topology-support strict churn guard:

- change FoM: +0.000034;
- change F1: +0.000047;
- overall accuracy: +0.000009;
- kappa: +0.000028;
- macro-F1: +0.000045;
- predicted changes: unchanged at 214,572;
- change hits: 80,548 vs 80,538;
- change false alarms: 134,024 vs 134,034;
- change misses: 167,559 vs 167,569;
- pair guard activity: 1,309 penalized transition-pair rows across 100 cases,
  covering 9,014,473 candidate cells before quota allocation.

Relative to FLUS:

- mean change FoM delta: +0.043972;
- mean change F1 delta: +0.069223;
- mean overall accuracy delta: -0.017457;
- mean kappa delta: -0.039989;
- mean macro-F1 delta: -0.021229;
- change-FoM wins/losses vs FLUS: 69 / 31.

Promotion boundary:

- promote this pair-support variant as the current map-gap reduction leader,
  because it improves every tracked aggregate metric over the previous
  support-strict candidate while preserving target-demand conservation;
- treat the gain as diagnostic and micro-scale, not a breakthrough;
- the result supports the TWM-specific hypothesis that geospatial world-model
  improvement should come from spatially grounded transition-pair constraints,
  but the current hand-built pressure still needs stronger region- and
  class-conditioned learning to close the OA/kappa/macro-F1 gap to FLUS.

## Benchmark Checkpoint: 2026-07-02 Pair Topology Support Contrast Guard

Implemented a train-only contrast variant:
`twm_pair_topology_support_contrast_strict_false_alarm_churn_guarded_persistence_forecast_demand`.

What changed:

- adds `territory_world_model.train_pair_topology_support_contrast_score_guard.v1`;
- keeps the pair-specific unsupported-cell penalty from the previous candidate,
  but also boosts supported cells for the same high false-alarm source->target
  pair;
- uses train-replay false-alarm rate and precision to decide which pairs get
  contrast, while spatial support still comes from train-change frontiers and
  target-class neighborhoods;
- keeps the same strict false-alarm churn guard and persistence demand
  projection, so the observed gain comes from spatial ranking, not from a
  different change budget or demand target.

100-case strict-mask reused-FLUS recompute:

- output:
  `/private/tmp/twm_dynamic_world_flus_pair_topology_support_contrast_strict_churn_verify_2026-07-02.json`;
- status: pass;
- mean change FoM: 0.195662;
- mean change F1: 0.324579;
- mean overall accuracy: 0.900997;
- mean kappa: 0.770697;
- mean macro-F1: 0.484675;
- total target-demand absolute error: 0.

Relative to pair topology-support strict churn guard:

- change FoM: +0.000735;
- change F1: +0.001017;
- overall accuracy: +0.000058;
- kappa: +0.000212;
- macro-F1: +0.000378;
- predicted changes: unchanged at 214,572;
- change hits: 80,738 vs 80,548;
- change false alarms: 133,834 vs 134,024;
- change misses: 167,369 vs 167,559;
- contrast guard activity: 1,309 penalized transition-pair rows and 1,345
  boosted transition-pair rows across 100 cases, covering 9,014,473 penalized
  candidate cells and 2,165,138 boosted candidate cells before quota
  allocation.

Relative to FLUS:

- mean change FoM delta: +0.044707;
- mean change F1 delta: +0.070240;
- mean overall accuracy delta: -0.017399;
- mean kappa delta: -0.039776;
- mean macro-F1 delta: -0.020851;
- change-FoM wins/losses vs FLUS: 69 / 31.

Promotion boundary:

- promote this contrast variant as the current map-gap reduction leader because
  it improves every tracked aggregate metric over the previous pair-support
  candidate while preserving predicted change count and target-demand
  conservation;
- the result is still not broad superiority over FLUS because OA, kappa and
  macro-F1 remain below FLUS;
- the useful signal is stronger than the previous micro-gain: supported-cell
  boosting within high-risk source->target pairs improved hits by 190 without
  increasing predicted changes;
- next algorithm work should learn support floors and contrast weights from
  region/class-pair strata instead of using fixed global thresholds.

## Immediate Implementation Order After Current P5G Slice

1. **P5H accepted-suite rematerialization gate**
   - service/API/tool: require accepted suite updates to re-run mining,
     failure-memory protocol, replay scheduler and materialization before any
     candidate promotion language;
   - test: updated suite ID, dataset snapshot and accepted feedback lineage
     resolve across all downstream reports;
   - acceptance: accepted feedback becomes durable replay memory only after the
     full geospatial failure-memory chain is refreshed.

2. **P5I canary dashboard serving contract**
   - service/API/tool: expose dashboard-ready summaries for spatial/rule/
     evidence/action failures and rollback readiness;
   - test: dashboard rows resolve failure-memory version, canary scope and
     replay-result lineage;
   - acceptance: dashboard makes canary evidence inspectable but still does not
     perform registry activation.

3. **P5J catalog execution dry-run gate**
   - service/API/tool: validate Iceberg/PostGIS registration plan against
     available catalog/schema capabilities before execution;
   - test: dry run detects missing tables, missing rollback preconditions and
     failure-memory version mismatches;
   - acceptance: dry run improves operational readiness but still does not
     execute production DDL or activate models.

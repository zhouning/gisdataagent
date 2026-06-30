# TWM Algorithm Model Roadmap

Date: 2026-06-30
Project: GIS Data Agent / Territory World Model
Status: roadmap refresh, approved design direction

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

The production blocker is still evidence, not ambition:

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
current_hierarchical_gis_state
  + action
  + scenario_context
  + evidence_context
  -> observed_next_state
  + constraint_outcome
  + utility_outcome
  + review_outcome
```

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

- freeze one pilot data intake template;
- run production onboarding against real or sanitized records;
- finish future latent v2 contract checks in evaluation reports;
- add temporal/spatial split metadata to dynamics datasets;
- document same-case baseline requirements.

### 60 Days

- train and compare MLP, graph and transformer candidates on pilot or sanitized
  data;
- add explicit action-mask false allow / false block reporting;
- publish a dynamics evaluation bundle with seed stability and holdout results;
- report FLUS/GeoSOS comparison as metric-specific evidence only.

### 90 Days

- run planner-coupled evaluation on at least one pilot workflow;
- produce selected-plan reports with recommendation / block / review classes;
- connect causal/evidence diagnostics to claim-ladder status;
- define the first model promotion candidate and its rollback evidence.

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

The next implementation slice should not add another large feature surface first.
It should choose one pilot data package and make the production-data gate,
dynamics dataset contract and same-case baseline report unavoidable. Only after
that should model architecture complexity increase.

## Implementation Checkpoint: P0/P1 Gate Hardening

Plan: `docs/superpowers/plans/2026-06-30-twm-p0-p1-production-evidence-contract.md`

The first implementation slice is intentionally gate-focused. It should make
production observed-history preflight, same-case baseline evidence and MREP
traceability visible in strict readiness and onboarding reports before adding
more model architecture complexity.

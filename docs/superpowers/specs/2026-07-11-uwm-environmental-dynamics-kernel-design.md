# UWM Environmental Dynamics Kernel Design

Date: 2026-07-11

## 1. Purpose

This design implements customer demand 11, environmental quality and climate comfort, as the next production UWM livability capability. It is not a static environmental score page and it does not duplicate traditional GIS diagnosis. Its purpose is to represent an observed environmental state, evolve that state through time under external forcing, apply a controlled intervention, propagate bounded spatial effects, compare counterfactual trajectories and expose the evidence limits of every reported difference.

The first release uses the existing Chongqing environmental evidence foundation. It must not present Khalifa City or another customer geography as executed without corresponding data.

## 2. Why This Requires UWM

Traditional GIS remains responsible for current heat, vegetation, pollution, facility and accessibility maps. UWM is required only for the dynamic questions:

- how environmental state evolves under observed or scenario meteorology;
- how a declared intervention changes the transition trajectory;
- how an effect propagates across a spatial graph;
- how baseline and intervention futures differ over multiple steps;
- whether a plan remains useful under external uncertainty;
- which claims are supported by observed calibration versus bounded proxy assumptions.

The runtime chain is:

```text
observed environmental evidence
  -> versioned environmental state graph
  -> canonical intervention action
  -> temporal external dynamics
  -> action response kernel
  -> spatial propagation kernel
  -> baseline/intervention rollouts
  -> evidence gate and uncertainty envelope
  -> planner-ready evaluation package
```

## 3. Scope and Release Boundary

### 3.1 Included

- versioned environmental state nodes for a real Chongqing scene;
- PM2.5 temporal dynamics using existing TAP-like calibration and holdout contracts;
- temperature, vegetation and built-environment context when supported by current evidence bundles;
- controlled green-infrastructure intervention actions;
- explicit separation of temporal dynamics, direct action response and spatial propagation;
- multi-step baseline and intervention trajectories;
- counterfactual deltas, uncertainty and claim boundaries;
- API/service product suitable for the existing UWM livability tab;
- a map payload that distinguishes observed state, directly affected area and propagated context.

### 3.2 Excluded from the First Release

- claiming causal policy effectiveness without observed intervention-outcome data;
- invented temperature reduction, pollution reduction or health benefits;
- building-scale computational fluid dynamics;
- authoritative microclimate or regulatory compliance conclusions;
- citywide five-year socioeconomic forecasts;
- a learned green-infrastructure policy unless the calibration gate passes;
- replacing current-state environmental GIS analysis.

## 4. State Contract

Each state bundle uses `uwm.environmental_state.v1` and includes:

```text
state_id
scene_id
snapshot_time
geography_version
spatial_nodes[]
spatial_edges[]
external_forcing
source_dataset_ids[]
evidence_bundle_id
kernel_versions
claim_boundary
```

Each spatial node contains only available quantities and labels their support independently:

```text
node_id
node_type
geometry_ref
pm25_ugm3
pm25_support_level
temperature_c
temperature_support_level
vegetation_fraction
vegetation_support_level
built_fraction
built_fraction_support_level
population_exposure_proxy
exposure_support_level
uncertainty
missing_fields[]
```

Missing measurements remain null and enter the evidence gate. They must not be filled with arbitrary defaults. Population exposure is optional and must remain a labelled proxy unless an authoritative aligned population surface is bound.

## 5. Spatial Graph

The kernel reuses canonical administrative and gridded crosswalks where available. The first release supports:

- `grid_adjacent_grid` for local spatial propagation;
- `grid_within_admin` for aggregation and reporting;
- `admin_adjacent_admin` only when an existing verified crosswalk exists;
- optional geographic-similarity edges for evaluation, never as a substitute for physical adjacency.

Every edge stores distance, shared boundary or crosswalk evidence, graph version and support level. Name similarity is not a valid crosswalk.

## 6. Action Contract

The canonical action schema is `uwm.environmental_action.v1`.

Initial actions:

```text
no_intervention(target_node_ids)

green_infrastructure_change(
    target_node_ids,
    action_type,
    declared_area_m2,
    vegetation_fraction_delta,
    implementation_stage,
    rationale,
    actor
)
```

Allowed `action_type` values initially are:

- `increase_tree_canopy_proxy`;
- `increase_green_surface_proxy`;
- `convert_declared_parcel_to_green_proxy` only when a valid S2 parcel transition artifact is supplied.

The service binds the actor, snapshot digest, geometry and evidence versions. The action is rejected if the target does not exist, the snapshot is stale, declared area exceeds bound geometry, vegetation change is outside `[0, 1]`, or a parcel conversion lacks a valid S2 transition artifact.

The word `proxy` is mandatory until a calibrated local action-response model exists.

## 7. Hybrid Dynamics Kernel

The runtime transition is decomposed rather than hidden in one score:

```text
S(t+1) = Temporal(S(t), X(t))
       + DirectAction(S(t), A(t))
       + SpatialPropagation(S(t), A(t), G)
```

### 7.1 Temporal External Dynamics

PM2.5 temporal evolution reuses the current TAP external-dynamics contract and must report calibration and holdout readiness. Meteorology is an external forcing, not an action effect.

Temperature dynamics initially preserve observed/scenario forcing and uncertainty. No green-action cooling coefficient is enabled as empirical unless supported by a local intervention dataset.

### 7.2 Direct Action Response

Direct response produces a mechanism vector rather than an unsupported outcome claim:

```text
vegetation_state_delta
surface_state_delta
direct_pm25_response
direct_temperature_response
support_level
coefficient_source
uncertainty
```

For the first release:

- vegetation and declared surface changes may be deterministic state edits;
- temperature and PM2.5 responses are `bounded_proxy` or `unavailable` unless a calibration artifact is supplied;
- no fixed benefit label is embedded in the action definition;
- zero is not used to disguise an unavailable effect.

### 7.3 Spatial Propagation

Propagation uses physical adjacency and distance-decay evidence through the existing spillover-kernel patterns. Each propagated message stores:

```text
source_node_id
target_node_id
relation_type
effect_channel
raw_weight
normalized_weight
hop
support_level
uncertainty
coefficient_source
claim_level
```

Propagation channels are separate:

- pollution transport/context;
- thermal context;
- vegetation or green-continuity context.

A channel is disabled when its evidence is unavailable. The kernel must not reuse one coefficient across different channels merely to produce a complete-looking result.

## 8. Evidence and Calibration Gate

Support levels are:

- `observed_calibrated`: calibrated with scene-aligned observations and passed holdout criteria;
- `observed_context`: observed state, but no intervention response calibration;
- `bounded_proxy`: transparent, bounded mechanism assumption;
- `unavailable`: insufficient evidence for the transition channel.

The gate evaluates independently:

- state observation readiness;
- temporal calibration readiness;
- action-response calibration readiness;
- spatial propagation readiness;
- external-forcing alignment;
- counterfactual claim readiness.

A PM2.5 temporal model passing holdout does not automatically validate green-action PM2.5 effects. Each mechanism requires its own evidence binding.

Maximum claims:

- observed current state;
- calibrated temporal replay/forecast where the temporal gate passes;
- bounded scenario comparison for proxy channels;
- no causal policy-effect or health-benefit claim in the first release.

## 9. Rollout Contract

Every request executes at least two trajectories from an identical state and forcing package:

```text
baseline:
  S0 -> no_intervention -> S1 ... SH

intervention:
  S0 -> green_infrastructure_change -> S1' ... SH'
```

Required controls:

- identical initial state, horizon and external forcing;
- stable random seed when stochastic uncertainty is sampled;
- immutable action and evidence digests;
- per-step mechanism decomposition;
- no comparison when scene, forcing or graph versions differ.

The rollout returns:

```text
baseline_trajectory
intervention_trajectory
counterfactual_delta_by_step
mechanism_contributions
propagation_messages
uncertainty_envelope
evidence_gate
production_blockers
not_a_causal_effect_estimate
```

`not_a_causal_effect_estimate` remains true until an explicit causal evidence gate exists and passes.

## 10. Planner Boundary

The first release produces a planner-ready evaluator but not an autonomous policy claim. Candidate actions may be compared on:

- declared green-area change;
- number and area of directly affected nodes;
- propagated context coverage;
- uncertainty width;
- evidence completeness;
- constraint violations.

It must not rank actions by invented degrees of cooling, avoided pollution exposure, monetary benefit or health benefit. If outcome channels are unavailable, the product reports that the action cannot yet be ordered by that outcome.

## 11. Product and API

Proposed endpoints:

```text
GET  /api/uwm/livability/environmental-kernel/scene
GET  /api/uwm/livability/environmental-kernel/evidence-gate
POST /api/uwm/livability/environmental-kernel/rollout
GET  /api/uwm/livability/environmental-kernel/map
```

The existing UWM livability tab adds an Environmental Dynamics section with:

- observed scene and evidence period;
- state variables and missing fields;
- external-forcing timeline;
- controlled action editor;
- baseline/intervention trajectory chart;
- direct versus propagated mechanism breakdown;
- evidence-level badges and production blockers;
- map layers for target nodes, direct effects and propagated context;
- an explicit statement that proxy deltas are not causal policy-effect estimates.

The UI must not label a proxy trajectory as a predicted real-world benefit.

## 12. Real Product Scene

The initial product is generated from the current Chongqing environmental evidence artifacts. It records the actual scene period, datasets and alignment status discovered at build time.

If no geometry-aligned vegetation intervention scene is available, the product must still provide:

- observed environmental state and temporal baseline when supported;
- action contract validation;
- evidence gate showing action-response or propagation blockers;
- no fabricated intervention outcome.

A closed result is preferable to a synthetic success.

## 13. Verification

Tests must cover:

- state schema and missing-value preservation;
- stale snapshot and invalid geometry rejection;
- S2 binding for parcel conversion actions;
- temporal/action/spatial mechanism separation;
- propagation channel isolation;
- identical baseline/intervention forcing;
- per-mechanism evidence levels;
- inability to promote temporal calibration into action-effect calibration;
- counterfactual comparison invariants;
- fail-closed behavior when coefficients or alignment are absent;
- API actor isolation and immutable request binding;
- frontend contract prohibiting causal or authoritative benefit language;
- real Chongqing product build and verification with zero fabricated values.

## 14. Acceptance Criteria

The capability is accepted only if:

1. a real, versioned environmental state is built from existing evidence;
2. the kernel executes multi-step baseline and intervention trajectories;
3. temporal, direct-action and spatial effects are separately inspectable;
4. unsupported action effects remain `bounded_proxy` or `unavailable`;
5. the same external forcing is used for counterfactual comparison;
6. no unavailable value is silently replaced with zero or a guessed coefficient;
7. production blockers and maximum claim level are exposed through service, API and UI;
8. tests and a real-product verification report demonstrate the evidence boundary;
9. the result cannot be mistaken for a static GIS score or a causal policy-effect estimate.

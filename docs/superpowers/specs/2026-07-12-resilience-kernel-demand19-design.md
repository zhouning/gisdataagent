# Resilience World Model Kernel Foundation Demand 19 Design

**Date:** 2026-07-12  
**Branch:** `feat/resilience-kernel-demand19`  
**Product:** 韧性世界模型（需求19）

## 1. Objective

Implement a real resilience-state, spatial-graph and evidence-gated UWM Kernel foundation. The first release exposes observed resilience context and explicit mechanism readiness while failing closed for unsupported disturbance, propagation, response, recovery and intervention transitions.

The product upgrades demand 19 from a route contract to an evidence-bounded world-model architecture. It does not claim hazard loss prediction, response effectiveness, recovery forecasting or policy robustness.

## 2. Why UWM Is Required

Demand 19 inherently concerns:

- disturbance-conditioned future states;
- spatial propagation;
- response actions;
- recovery trajectories;
- counterfactual interventions;
- robust planning under uncertainty.

These are dynamic transition questions and belong in UWM. Static GIS remains responsible for observed inventories, graph construction, coverage diagnostics and evidence provenance.

## 3. Available Evidence

The initial state may bind:

- verified administrative units and explicit adjacency graph;
- mobility/network context;
- observed public-service, fire-service and healthcare facility evidence;
- observed environmental state;
- calibrated PM2.5 external temporal dynamics;
- demand-24 cross-domain source registry;
- demand-25 resilience dependency chain.

These inputs provide context and readiness only. They do not constitute observed disaster response or recovery outcomes.

## 4. Missing Evidence

Current blockers include:

```text
authoritative_hazard_event_timeseries_missing
population_and_asset_exposure_missing
observed_damage_state_missing
emergency_response_time_missing
response_capacity_observations_missing
hazard_spatial_propagation_calibration_missing
recovery_state_timeseries_missing
recovery_transition_calibration_missing
resilience_intervention_registry_missing
intervention_outcome_evidence_missing
held_out_event_evaluation_missing
```

Missing values remain null and mechanisms remain closed.

## 5. World Model Contract

The standard interface is:

```text
state_t
disturbance_t
action_t
transition_t_to_t1
propagation
response
recovery
counterfactual
uncertainty
```

### State

Observed state contains only source-supported fields:

```text
node_id
admin_unit_id
admin_name
spatial_grain
network_context
public_service_context
emergency_facility_context
environment_context
evidence_coverage
source_trace
limitations
```

No resilience score, safety level, vulnerability, loss, mortality or expected recovery time is derived.

### Disturbance

A production disturbance must reference a registered observed or approved scenario artifact with type, spatial footprint, start time, duration, intensity definition and provenance. Arbitrary user-entered hazard intensity cannot be promoted into a predicted impact.

### Action

Actions require an explicit intervention type, target, timing, constraints and calibrated response evidence. Without intervention-response evidence, action rollout is closed.

## 6. Spatial Graph

The graph uses the verified administrative adjacency product. Each edge contains:

```text
source_node_id
target_node_id
edge_type
edge_provenance
shared_boundary_or_network_basis
propagation_parameter=null
```

Adjacency is not a hazard-transmission coefficient. No propagation weight may be inferred from distance, border length or road connectivity without calibration evidence.

## 7. Evidence Gates

Required gates:

```text
hazard_evidence_gate
exposure_evidence_gate
response_capacity_evidence_gate
propagation_evidence_gate
recovery_evidence_gate
intervention_evidence_gate
evaluation_evidence_gate
```

Each gate includes:

```text
status
support_level
source_ids
required_evidence
blockers
max_supported_claim
```

Statuses:

```text
observed_context
calibrated_limited
closed
```

`calibrated_limited` must identify the exact variable and evaluation scope. The PM2.5 temporal channel may be registered separately but cannot be relabelled as disaster propagation or recovery.

## 8. Current Production Rollout

The first production rollout is intentionally fail-closed:

```text
disturbance_transition_status=closed
hazard_propagation_status=closed
response_capacity_status=closed
recovery_transition_status=closed
intervention_effect_status=closed
counterfactual_status=closed
```

The rollout returns baseline observed context, graph metadata, gate states, blockers and required next evidence. It returns no fabricated future-state trajectory.

## 9. Kernel Opening Rules

### Disturbance Transition

Requires registered hazard events, observed pre/during/post state snapshots and a defined state target.

### Propagation

Requires spatially and temporally resolved event observations, calibrated edge or neighbourhood mechanism and held-out spatial evaluation.

### Response

Requires dispatch, response-time, capacity, availability and outcome observations linked to events.

### Recovery

Requires repeated post-event state observations, recovery target definition and calibrated transition uncertainty.

### Intervention and Counterfactual

Requires explicit intervention histories, timing, affected units, outcome observations, confounding controls and held-out evaluation.

No gate opens because a model interface exists.

## 10. Product Contract

Schema:

```text
uwm.resilience_kernel_foundation.v1
```

Immutable bundle:

```text
overview.json
state.json
graph.json
evidence_gates.json
current_rollout.json
dependency_chain.json
map.json
```

## 11. API and UI

Authenticated read-only endpoints:

```text
/api/uwm/resilience-kernel/overview
/api/uwm/resilience-kernel/state
/api/uwm/resilience-kernel/graph
/api/uwm/resilience-kernel/gates
/api/uwm/resilience-kernel/rollout
/api/uwm/resilience-kernel/dependencies
/api/uwm/resilience-kernel/map
```

Independent tab: `韧性世界模型`.

The UI displays observed nodes and graph coverage, source evidence, gate readiness, closed rollout mechanisms, calibrated external environmental channel, dependency-chain tasks and explicit prohibited claims.

## 12. Mandatory Claim Boundaries

```text
network_context_not_hazard_propagation=true
facility_presence_not_response_capacity=true
adjacency_not_transmission_coefficient=true
environment_temporal_dynamics_not_disaster_recovery=true
closed_rollout_not_failed_simulation=true
evidence_gap_not_resilience_risk=true
dependency_task_not_intervention_recommendation=true
```

Forbidden fields:

```text
resilience_score
vulnerability_score
hazard_loss
expected_damage
mortality
response_effectiveness
recovery_time
recovery_probability
intervention_benefit
robustness_score
```

## 13. Verification

Independent verification rejects:

- bundle mismatch;
- graph edges without provenance;
- non-null propagation parameters;
- unsupported gate promotion;
- future trajectories in a closed rollout;
- arbitrary disturbance impacts;
- forbidden risk, loss, response or recovery fields;
- missing demand-25 dependency trace;
- fabricated values above zero.

## 14. Maximum Claim and Ledger

Maximum claim:

```text
observed_resilience_context_spatial_graph_and_fail_closed_kernel_readiness
```

Demand 19 target:

```text
implementation_status=implemented_evidence_bounded
```

The product is a real world-model foundation with executable evidence gates. It is not yet a calibrated hazard propagation, emergency response, recovery or intervention simulator.

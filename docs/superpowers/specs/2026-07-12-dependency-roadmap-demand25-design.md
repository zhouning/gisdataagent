# Dependency-Aware Implementation Roadmap Demand 25 Design

**Date:** 2026-07-12  
**Branch:** `feat/dependency-roadmap-demand25`  
**Product:** 建议与实施路线图（需求25）

## 1. Objective

Implement demand 25 as an evidence-dependency and verification-gated implementation roadmap. The product converts demand 24 source-product states, comparability results, production blockers, dynamic-channel states and dependency graph into an executable task DAG.

The roadmap answers what evidence, calibration and verification work can start now, what remains blocked, which tasks unlock multiple later capabilities, and what stronger claim becomes permissible after verified completion.

It does not generate unsupported policy, construction, investment, budget, duration, benefit or organizational commitments.

## 2. Authoritative Input Contract

Primary input:

```text
data/uwm_public_proxy/chongqing_central/cross_domain_impact_chongqing
```

Required files:

```text
overview.json
source_products.json
comparability_matrix.json
priority_units.json
dependency_graph.json
map.json
```

All input files must share one demand-24 bundle ID. Missing or inconsistent inputs fail closed.

Demand 25 may trace other source bundles only through demand 24's registered source-product lineage. It cannot discover or promote unregistered capabilities by repository scanning.

## 3. Roadmap Phases

```text
phase_0_operate_verified_capabilities
phase_1_data_and_crosswalk_foundation
phase_2_kernel_calibration
phase_3_independent_verification
phase_4_decision_product_release
```

### Phase 0

Operate verified traditional GIS products and calibrated environmental temporal evidence. Monitor bundle health, freshness, source availability and claim boundaries. Closed Kernel gates remain closed.

### Phase 1

Acquire authoritative observations and crosswalks required by later calibration. Examples include housing stock and household transitions, heritage register and condition history, licences and economic lifecycle observations, hazards and recovery observations, intervention-response data, authoritative administrative crosswalks, service capacity and population matching.

### Phase 2

Calibrate a Kernel only when all declared phase-1 prerequisites are verified. Kernel tasks include explicit state, action, transition, uncertainty and calibration-evaluation contracts.

### Phase 3

Require held-out temporal or spatial validation, baseline comparison, uncertainty evaluation, negative-control or counterfactual checks, failure-closed behavior and an independent verification artifact.

### Phase 4

Release stronger decision products only after phase-3 verification. Dynamic prediction, intervention comparison, portfolio analysis and cost-benefit linkage remain blocked until their exact prerequisites pass.

## 4. Task Contract

Each task contains:

```text
task_id
domain
phase
task_type
title
status
priority_rank
prerequisite_task_ids
blocking_evidence
source_bundle_ids
completion_evidence_requirements
verification_gate
allowed_next_claim
owner_role
spatial_scope
temporal_scope
limitations
```

Task IDs are deterministic and stable across rebuilds when the dependency meaning does not change.

## 5. Status Machine

Allowed statuses:

```text
blocked
ready
in_progress
verification_required
verified
deferred
```

Initial production rules:

- phase-0 tasks are `verified` only when the source product is registered, its evidence artifact exists, fabricated values equal zero and its claim boundary is present;
- phase-1 tasks are `ready` when they have no unmet task prerequisite, otherwise `blocked`;
- phase-2 tasks are `blocked` until every required phase-1 task is verified;
- phase-3 tasks are `blocked` until their Kernel calibration task is complete; externally supplied completion may move them to `verification_required`;
- phase-4 tasks are `blocked` until the associated independent-verification task is verified;
- no language-model inference may promote a status;
- no task automatically becomes `in_progress`.

The first published product is an immutable planning snapshot, not a mutable project-management database.

## 6. Dependency Graph and Priority

The task graph must be acyclic. Independent verification rejects missing task references, self-dependencies and cycles.

Priority is determined by:

1. number of descendant tasks unlocked;
2. number of domains sharing the prerequisite;
3. whether the task can open a closed UWM gate;
4. whether completion evidence is explicit and testable;
5. whether a verified source bundle supports the task;
6. phase order;
7. deterministic task ID tie-break.

Priority is implementation-readiness priority, not district need, policy urgency, public value or investment return.

## 7. Shared Dependencies

Shared tasks are created where one evidence foundation unlocks multiple domains. Initial shared foundations include:

- authoritative district/township/analytical-unit crosswalk;
- longitudinal intervention registry with timestamps and spatial scope;
- held-out evaluation protocol and immutable evaluation bundles;
- source-product freshness and bundle-lineage monitoring;
- cost, benefit, feasibility, funding and risk evidence contract for any future investment analysis.

Shared dependencies reference all affected domains and must not be duplicated into contradictory domain tasks.

## 8. Domain Chains

### Housing

```text
housing_state_inventory
household_transition_observations
housing_intervention_registry
housing_kernel_calibration
housing_kernel_independent_verification
housing_dynamic_decision_release
```

### Culture

```text
authoritative_heritage_register
cultural_asset_condition_timeseries
cultural_activity_and_intervention_registry
culture_kernel_calibration
culture_kernel_independent_verification
culture_dynamic_decision_release
```

### Economy

```text
authoritative_licence_lifecycle
employment_transaction_or_revenue_evidence
economic_intervention_registry
economy_kernel_calibration
economy_kernel_independent_verification
economy_dynamic_decision_release
```

### Resilience

```text
hazard_exposure_observations
response_capacity_inventory
propagation_and_recovery_timeseries
resilience_kernel_calibration
resilience_kernel_independent_verification
resilience_dynamic_decision_release
```

### Environment

The observed state and PM2.5 external temporal dynamics are phase-0 verified capabilities. Intervention response, spatial propagation, temperature and vegetation calibration remain separate blocked chains.

## 9. Recommendation Boundary

The roadmap may recommend:

- data acquisition;
- administrative crosswalk preparation;
- model calibration;
- independent verification;
- monitoring and source governance;
- decision-product release gates.

It cannot recommend or fabricate:

```text
construction_project
facility_quantity
capital_budget
operating_budget
implementation_duration
start_date
completion_date
responsible_agency
expected_benefit
investment_return
policy_effect
preferred_vendor
```

Missing values remain null.

## 10. Product Contract

Schema:

```text
uwm.dependency_aware_implementation_roadmap.v1
```

Immutable bundle:

```text
overview.json
tasks.json
dependency_graph.json
domain_chains.json
gates.json
map.json
```

The map layer may show demand-24 district evidence-orchestration priority for context, but district rank cannot alter task readiness or create district-specific projects.

## 11. API and UI

Authenticated read-only endpoints:

```text
/api/uwm/implementation-roadmap/overview
/api/uwm/implementation-roadmap/tasks
/api/uwm/implementation-roadmap/dependencies
/api/uwm/implementation-roadmap/domains
/api/uwm/implementation-roadmap/gates
/api/uwm/implementation-roadmap/map
```

Independent tab: `建议与实施路线图`.

UI views:

- current verified capabilities;
- ready and blocked tasks;
- shared dependencies;
- domain chains;
- Kernel opening paths;
- verification gates;
- demand-24 input lineage;
- forbidden recommendation boundary.

## 12. Verification

Independent verification rejects:

- bundle mismatch;
- dependency cycles or missing task references;
- unsupported status values;
- blocked tasks promoted without verified prerequisites;
- phase-4 release before phase-3 verification;
- missing completion-evidence requirements;
- unregistered source bundles;
- fabricated budget, dates, benefits, organizations or policy effects;
- task priority represented as need, impact or investment priority;
- fabricated values above zero.

## 13. Maximum Claim and Ledger

Maximum claim:

```text
evidence_dependency_and_verification_gated_implementation_roadmap
```

Demand 25 target:

```text
implementation_status=implemented_evidence_bounded
```

The product is a technical implementation roadmap. It is not an approved government program, procurement plan, budget plan or policy commitment.

# Cross-Domain Impact Evidence and Priority Demand 24 Design

**Date:** 2026-07-12  
**Branch:** `feat/cross-domain-impact-demand24`  
**Product:** 跨领域影响证据与优先级（需求24）

## 1. Objective

Implement demand 24 as a cross-domain evidence orchestration product. It combines verified outputs from completed traditional GIS products and calibrated UWM channels without erasing source semantics, spatial grain, temporal scope, evidence quality or claim boundaries.

The product answers:

- which domain evidence products are available;
- which administrative or analytical units can be compared exactly;
- where evidence gaps are concentrated across compatible domains;
- which domains are ready for static diagnosis, dynamic UWM analysis, or further data acquisition;
- what dependencies block stronger impact or intervention claims.

It does not produce a universal livability score, problem-severity score, investment-return score or guaranteed policy-impact ranking.

## 2. Source Products

Initial source adapters cover:

- demand 8 mobility and accessibility;
- demands 12/21 social infrastructure and public services;
- demand 9 public space;
- demand 10 safety, security and comfort evidence readiness;
- demand 11 environmental UWM Kernel;
- demand 13 housing and community composition evidence;
- demand 14 daily convenience and business-activity evidence;
- demand 16 cultural heritage and place-context evidence.

Observed product grains include:

- district products: 39 administrative units;
- housing/population proxy: 852 administrative units;
- mobility/environment reference products: 1,017 analytical units;
- UWM environmental dynamics: scene, time and intervention-conditioned outputs.

These grains are not interchangeable.

## 3. Architecture

The product contains four layers:

```text
source_product_registry
comparability_matrix
cross_domain_evidence_priority
uwm_dynamic_channel_registry
```

### 3.1 Source Product Registry

Each source product registers:

```text
domain_id
demand_ids
product_schema
bundle_id
technology_route
spatial_grain
temporal_scope
unit_count
unit_identifier_contract
max_claim_level
fabricated_value_count
production_blockers
source_artifacts
```

`technology_route` is one of:

```text
traditional_gis
uwm_calibrated_dynamic
uwm_closed_gate
```

Product presence does not imply full requirement completion.

### 3.2 Comparability Matrix

For each domain pair, the matrix records:

```text
exact_comparable
aggregate_reference_only
reference_only
incompatible
```

A pair is `exact_comparable` only if:

- the unit identifier contract is identical;
- spatial grain is identical;
- administrative membership is explicit;
- temporal scopes are compatible for the requested analysis;
- the compared values have compatible semantics.

Names, centroids, row order, nearest-neighbour proximity and approximate boundary overlap cannot create an exact join.

District-level products may coexist in one district matrix when their explicit district codes match. Township or analytical-unit products remain separate unless an authoritative parent-code mapping is present. Aggregation never creates an observed value at the target grain.

### 3.3 Cross-Domain Evidence Priority

The product emits `cross_domain_evidence_priority_rank` only for units with explicitly compatible identifiers.

Priority components are evidence-readiness facts:

- number of compatible domains represented;
- number of source products with explicit evidence gaps;
- number of unavailable channels;
- number of production blockers;
- presence of a calibrated UWM dynamic channel;
- dependency count before stronger claims are possible;
- source and grain consistency.

The rank means evidence-orchestration priority, not actual deprivation, risk, urgency, policy benefit or investment return.

No weighted average of domain scores is permitted. Domain-native ranks remain ranks in their own products and are not normalized into a universal outcome score.

## 4. District Evidence Matrix

The first production matrix uses the explicit 39-district identifier contract shared by district products. Supported district-domain channels include public service, public space, daily convenience and cultural-place evidence. Other products may appear as `reference_only` when their grain does not exactly match.

Each district row contains:

```text
admin_unit_id
admin_name
domain_evidence
compatible_domain_count
reference_only_domain_count
unavailable_channel_count
production_blocker_count
cross_domain_evidence_gap_reasons
dependency_requirements
cross_domain_evidence_priority_rank
source_trace
limitations
```

A domain's native evidence-gap rank is reported with its original name and interpretation. Missing values remain null. Missing domain rows do not become zero evidence.

## 5. UWM Dynamic Channel Registry

The environmental Kernel is registered only when its verified evidence bundle and evaluation artifacts exist. Its registry entry must identify:

- observed state variables;
- calibrated temporal transition variables;
- supported intervention/action variables;
- evaluation scope;
- uncertainty and blocker fields;
- maximum dynamic claim.

Housing, culture, economic vitality and resilience UWM channels remain `uwm_closed_gate` until their data and calibration gates are satisfied.

The product must visibly distinguish:

```text
static_traditional_evidence
dynamic_uwm_evidence
closed_uwm_readiness_gate
```

A closed UWM gate is not a simulated result.

## 6. Impact Claim Contract

Supported maximum claim:

```text
cross_domain_evidence_compatibility_priority_and_dynamic_channel_readiness
```

Mandatory flags:

```text
cross_domain_priority_not_outcome_severity=true
evidence_gap_not_observed_deprivation=true
rank_not_investment_return=true
product_presence_not_requirement_completion=true
reference_only_not_joined_observation=true
static_evidence_not_dynamic_impact=true
closed_uwm_gate_not_simulation=true
calibrated_environment_channel_not_general_uwm=true
```

Forbidden fields and claims:

```text
overall_livability_score
composite_impact_score
policy_benefit_score
investment_return_score
worst_district
best_intervention
predicted_housing_impact
predicted_cultural_impact
predicted_economic_impact
predicted_resilience_impact
```

## 7. Dependency Graph

Each stronger claim has explicit prerequisites. Examples:

- housing impact requires housing-stock state, household transitions, interventions and held-out calibration;
- cultural impact requires longitudinal asset condition, activity and intervention outcomes;
- economic impact requires authoritative licences, lifecycle, employment, revenue or transaction evidence;
- resilience impact requires hazards, exposure, response capacity, propagation and recovery observations;
- investment prioritization requires authoritative cost, benefit, funding, feasibility and risk inputs.

The graph is machine-readable and becomes the input foundation for demand 25. Demand 24 reports dependencies but does not yet produce an implementation roadmap.

## 8. Product Contract

Schema:

```text
uwm.cross_domain_impact_evidence.v1
```

Immutable bundle:

```text
overview.json
source_products.json
comparability_matrix.json
priority_units.json
dependency_graph.json
map.json
```

The product is immutable, bundle-consistent and independently verifiable.

## 9. API and UI

Authenticated read-only endpoints under:

```text
/api/uwm/cross-domain-impact
```

Endpoints expose overview, source products, comparability matrix, priority units, dependency graph and map payload.

An independent `跨领域影响与优先级` tab displays:

- traditional GIS versus UWM route status;
- source-product health and claim boundaries;
- comparability matrix;
- district evidence-orchestration priorities;
- UWM dynamic channels and closed gates;
- dependency graph for stronger claims;
- explicit warnings against universal scores and causal overclaiming.

## 10. Verification

Independent verification rejects:

- mismatched bundle IDs;
- fabricated values above zero;
- inferred exact joins;
- unregistered spatial-grain conversion;
- universal or weighted composite scores;
- missing claim-boundary flags;
- closed UWM gates represented as dynamic outputs;
- missing source-product bundle trace;
- priority rows without exact compatible identifiers;
- non-null forbidden impact predictions.

## 11. Ledger Target

Demand 24 target:

```text
implementation_status=implemented_evidence_bounded
max_claim_level=cross_domain_evidence_compatibility_priority_and_dynamic_channel_readiness
```

Demand 25 remains not implemented until this product is verified and can serve as its dependency input.

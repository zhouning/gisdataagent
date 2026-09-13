# Business Licence and Economic Activity Evidence Demand 20 Design

**Date:** 2026-07-12  
**Branch:** `feat/business-licence-demand20`  
**Product:** 企业执照与经济活动证据（需求20）

## 1. Objective

Implement demand 20 as an evidence-bounded product with three separated views:

```text
business_poi_spatial_evidence
authoritative_licence_readiness
business_lifecycle_uwm_readiness
```

The product reuses demand-14 verified business POI evidence as spatial leads, defines the authoritative DED-style licence and entity-lifecycle contracts required for production analysis, and exposes closed lifecycle UWM mechanisms.

It does not treat POIs as legal entities, valid licences, active businesses, employers or economic-output observations.

## 2. Available POI Evidence

Verified demand-14 evidence:

- business activity POIs: 3,749;
- company POIs: 3,110;
- industrial-enterprise POIs: 422;
- business-park POIs: 195;
- logistics-enterprise POIs: 22;
- explicit administrative codes for supported district aggregation;
- source dataset and source-record lineage;
- null operating, employment, revenue and transaction fields.

These records support business-place spatial evidence only.

## 3. Business POI Contract

Supported fields:

```text
place_id
name
canonical_category
longitude
latitude
admin_unit_id
source_dataset
source_record_id
classification_reason
source_trace
```

Required interpretation:

```text
company_poi_not_legal_entity_registry=true
poi_presence_not_valid_business_licence=true
poi_presence_not_active_operation=true
company_name_not_authoritative_entity_match=true
industrial_poi_not_observed_production=true
business_count_not_employment_or_output=true
```

No fuzzy entity matching is performed.

## 4. Authoritative Licence Contract

Required fields:

```text
licence_id
entity_id
entity_name
licence_type
licensed_activity
issuing_authority
issue_date
expiry_date
licence_status
registered_address
operating_address
longitude
latitude
admin_unit_id
status_observed_at
source_system
source_record_id
```

Production matching additionally requires explicit entity identifiers or an approved crosswalk between licence and place records. Names, addresses, centroids or proximity cannot create an authoritative match by themselves.

Licence channels:

```text
entity_registry
business_licence_registry
licence_status_history
licensed_activity_taxonomy
branch_relationships
registered_operating_address_crosswalk
inspection_and_enforcement_records
```

Initial status is `unavailable`, value is null.

## 5. Lifecycle Evidence Contract

Required events:

```text
incorporation_event
licence_issue_event
licence_renewal_event
licence_suspension_event
licence_revocation_event
closure_event
relocation_event
branch_opening_or_closure_event
activity_observation
employment_or_transaction_observation
```

Each event requires entity ID, event type, timestamp, source, scope and status provenance.

## 6. Business Lifecycle UWM Gate

Future state/action/transition contract:

```text
entity_state
licence_event
opening_event
closure_event
relocation_event
activity_state
employment_or_transaction_state
policy_or_incentive_action
lifecycle_transition
uncertainty
held_out_lifecycle_evaluation
```

Initial mechanism states:

```text
active_operation_inference=closed
opening_closure_prediction=closed
relocation_expansion_prediction=closed
employment_output_prediction=closed
licence_policy_response=closed
business_survival_estimation=closed
investment_intervention_effect=closed
```

## 7. Administrative Evidence Readiness

District rows may report:

- business POI count;
- category counts;
- category diversity;
- source-dataset count;
- licence-channel readiness;
- lifecycle-channel readiness;
- relative evidence-readiness rank;
- data-acquisition priorities.

The rank is not economic performance, business health or investment priority.

## 8. Forbidden Metrics and Claims

```text
valid_licence_business_count
unlicensed_business_count
business_opening_rate
business_exit_rate
business_survival_rate
employment_count
revenue
turnover
tax_contribution
economic_contribution
business_health_score
investment_attractiveness_score
investment_priority
policy_effect
```

Missing licence data does not imply an unlicensed business.

## 9. Product Contract

Schema:

```text
uwm.business_licence_activity_readiness.v1
```

Immutable bundle:

```text
overview.json
business_places.json
admin_units.json
licence_channels.json
data_contracts.json
uwm_gate.json
map.json
```

## 10. API and UI

Authenticated endpoints:

```text
/api/uwm/business-licence/overview
/api/uwm/business-licence/places
/api/uwm/business-licence/admin-units
/api/uwm/business-licence/licence-channels
/api/uwm/business-licence/data-contracts
/api/uwm/business-licence/uwm-gate
/api/uwm/business-licence/map
```

Independent tab: `企业执照与经济活动证据`.

The UI displays POI category evidence, district distribution, licence and lifecycle readiness, data contracts, closed UWM mechanisms and claim boundaries.

## 11. Verification

Independent verification rejects:

- bundle mismatch;
- legal entity or valid licence claims derived from POI;
- fuzzy or proximity entity matches;
- non-null unavailable licence values;
- operating, employment, revenue or tax values;
- open lifecycle mechanisms without authoritative event time series;
- economic or investment scores;
- fabricated values above zero.

## 12. Maximum Claim and Ledger

Maximum claim:

```text
business_poi_spatial_evidence_and_authoritative_licence_lifecycle_readiness
```

Demand 20 target:

```text
implementation_status=implemented_evidence_bounded
```

This product is not a DED licence register, active-business register or economic-performance analysis.

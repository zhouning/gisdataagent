# Development Control Rules and Planning Conditions Demand 22 Design

**Date:** 2026-07-12  
**Branch:** `feat/development-control-demand22`  
**Product:** 开发控制规则与规划条件证据就绪度（需求22）

## 1. Objective

Implement demand 22 as a planning-rule asset catalog and site-specific DCR execution-readiness product. The product inventories source-backed standards and rule capabilities, defines authoritative development-control channels and fails closed for site compliance or approval claims.

It does not convert reference standards, land-use classes, example thresholds or static screening distances into legal planning conditions.

## 2. Rule Asset Classes

```text
reference_standard
technical_data_standard
quality_or_validation_rule
planning_rule_contract
approved_site_specific_dcr
```

Only `approved_site_specific_dcr` may contain executable legal development-control values, and only when all authority and applicability gates pass.

Each asset includes:

```text
rule_asset_id
title
rule_asset_class
standard_or_document_id
version
source_path
issuing_authority
effective_from
effective_to
spatial_scope
object_scope
citation_reference
execution_status
max_claim_level
limitations
```

## 3. DCR Channels

```text
approved_land_use
floor_area_ratio
building_density
building_height
green_space_ratio
setback
building_spacing
parking_requirement
public_service_requirement
land_use_compatibility
special_control_zone
approval_document
rule_priority
effective_period
```

Initial values are null unless a registered authoritative site-specific planning condition supports them.

## 4. Executability Gate

A rule is `executable` only when all are present:

```text
authoritative_source
approved_or_published_identifier
version
effective_period
spatial_applicability
object_type
parameter_definition
unit_and_calculation_method
conflict_priority
citation_reference
```

Other statuses:

```text
reference_only
data_contract_ready
unavailable
```

A generic standard cannot be upgraded to executable based on semantic similarity or LLM extraction.

## 5. DCR+ Reasoning Gate

Future DCR+ capabilities may include:

- multi-rule applicability;
- conflict-resolution precedence;
- project-parameter compliance checks;
- constraint propagation;
- version-change impact;
- evidence-linked modification options.

Initial mechanisms:

```text
site_rule_applicability=closed
legal_parameter_extraction=closed
rule_conflict_resolution=closed
project_compliance_decision=closed
constraint_propagation=closed
automatic_scheme_modification=closed
```

## 6. Mandatory Boundaries

```text
reference_standard_not_site_specific_dcr=true
rule_text_not_approved_planning_condition=true
static_screening_distance_not_legal_setback=true
land_use_class_not_development_permission=true
rule_match_not_project_approval=true
missing_rule_not_unrestricted_development=true
```

Forbidden fields and claims:

```text
legal_floor_area_ratio
legal_building_density
legal_building_height
legal_green_space_ratio
legal_setback
legal_building_spacing
required_parking_count
required_public_service_quantity
buildable_floor_area
development_scale
construction_permitted
project_approved
compliance_decision
automatic_scheme_modification
```

## 7. Product Contract

Schema:

```text
uwm.development_control_rule_readiness.v1
```

Immutable bundle:

```text
overview.json
rule_assets.json
dcr_channels.json
data_contracts.json
execution_gate.json
map.json
```

The initial map is empty because no authoritative parcel-rule applicability product is registered.

## 8. API and UI

Authenticated endpoints:

```text
/api/uwm/development-control/overview
/api/uwm/development-control/rule-assets
/api/uwm/development-control/dcr-channels
/api/uwm/development-control/data-contracts
/api/uwm/development-control/execution-gate
/api/uwm/development-control/map
```

Independent tab: `开发控制规则与规划条件`.

The UI displays rule assets, authority classes, versions, evidence paths, DCR channel status, required contracts, execution gate and explicit prohibited claims.

## 9. Verification

Independent verification rejects:

- bundle mismatch;
- reference standards marked executable;
- executable rules missing authority/applicability fields;
- non-null unavailable DCR values;
- a screening distance labelled legal setback;
- land-use classification labelled permission;
- approval or compliance claims without authoritative project conditions;
- open DCR+ mechanisms without verified site rules;
- fabricated values above zero.

## 10. Maximum Claim and Ledger

Maximum claim:

```text
planning_rule_asset_catalog_and_site_specific_dcr_execution_readiness
```

Demand 22 target:

```text
implementation_status=implemented_evidence_bounded
```

This product is not a statutory planning-condition query or an automated project approval system.

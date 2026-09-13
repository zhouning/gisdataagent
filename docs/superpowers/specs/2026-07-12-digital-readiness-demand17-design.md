# Digital Assets and Smart District Readiness Demand 17 Design

**Date:** 2026-07-12  
**Branch:** `feat/digital-readiness-demand17`  
**Product:** 数字资产与智慧片区证据就绪度（需求17）

## 1. Objective

Implement demand 17 as two strictly separated evidence views:

```text
platform_digital_capability
smart_district_infrastructure_readiness
```

The first view inventories real GIS Data Agent platform assets, products, APIs, lineage, verification, observability and UWM readiness. The second view defines the authoritative data contracts required for district smart-infrastructure assessment and reports current evidence availability without fabricating asset coverage or digital maturity.

## 2. Platform Digital Capability

The product may inventory only repository- or product-supported capabilities:

- registered and verified traditional GIS products;
- registered and verified UWM products;
- closed UWM gates;
- immutable product bundles;
- authenticated product APIs;
- map payloads;
- verification reports;
- source lineage and evidence artifacts;
- data catalog, metadata, standards and classification capabilities;
- quality, observability, tracing and alert capabilities;
- implementation ledger, cross-domain dependency and roadmap products.

Each capability record includes:

```text
capability_id
capability_type
status
product_schema
bundle_id
api_prefix
evidence_artifacts
verification_status
technology_route
max_claim_level
production_blockers
source_trace
```

A registered route without a verified product is not counted as a verified capability.

## 3. Smart-District Infrastructure Readiness

Required infrastructure channels:

```text
iot_sensor_inventory
camera_inventory_and_online_state
smart_lighting_assets
public_wifi_assets
mobile_network_base_stations
edge_and_data_center_assets
smart_parking_devices
environment_monitoring_terminals
urban_operations_center_integrations
device_fault_and_maintenance_history
network_service_availability
service_usage_and_request_timeseries
```

Each channel has:

```text
status
value
required_fields
required_spatial_grain
required_temporal_grain
authoritative_source_requirement
quality_requirements
production_blockers
```

Initial statuses are `unavailable` unless an authoritative infrastructure asset and operation source is explicitly registered. Missing values remain null.

## 4. Required Asset Contract

A production smart-infrastructure asset record requires:

```text
asset_id
asset_type
operator_or_owner_reference
longitude
latitude
admin_unit_id
installation_or_commission_date
operational_status
status_observed_at
source_system
source_record_id
quality_status
```

Operational analysis additionally requires uptime, outage, fault, maintenance, replacement and service-use observations. Asset presence alone does not establish service availability, quality or use.

## 5. Evidence and Claim Boundaries

Mandatory flags:

```text
platform_capability_not_district_infrastructure_coverage=true
registered_api_not_observed_service_use=true
asset_presence_not_operational_availability=true
poi_or_facility_not_iot_asset=true
missing_inventory_not_zero_coverage=true
readiness_not_digital_maturity=true
closed_digital_uwm_gate_not_failure_prediction=true
```

Forbidden fields and claims:

```text
smart_city_score
digital_maturity_score
iot_coverage_rate
camera_coverage_rate
wifi_coverage_rate
five_g_coverage_rate
device_online_rate
digital_service_usage_rate
smart_district_rank
digital_investment_return
smart_policy_effect
```

## 6. UWM Readiness Gate

A future digital-infrastructure UWM requires:

```text
digital_asset_state
failure_event
maintenance_action
service_dependency_graph
service_interruption_propagation
recovery_transition
usage_demand_state
held_out_failure_and_recovery_evaluation
```

Initial gate states:

```text
asset_state_transition=closed
failure_propagation=closed
maintenance_response=closed
service_recovery=closed
counterfactual_maintenance=closed
```

The platform may expose the gate and required evidence, but it cannot generate device failures, downtime, recovery time or maintenance benefit.

## 7. Product Contract

Schema:

```text
uwm.digital_asset_smart_district_readiness.v1
```

Immutable bundle:

```text
overview.json
platform_capabilities.json
infrastructure_channels.json
data_contracts.json
uwm_gate.json
map.json
```

The map is empty or evidence-only until authoritative asset coordinates are registered.

## 8. API and UI

Authenticated endpoints:

```text
/api/uwm/digital-readiness/overview
/api/uwm/digital-readiness/platform-capabilities
/api/uwm/digital-readiness/infrastructure-channels
/api/uwm/digital-readiness/data-contracts
/api/uwm/digital-readiness/uwm-gate
/api/uwm/digital-readiness/map
```

Independent tab: `数字资产与智慧片区`.

The UI clearly separates platform capabilities from district infrastructure evidence. It displays verified products and APIs, technology routes, bundle lineage, missing asset channels, required data contracts and closed digital-infrastructure UWM mechanisms.

## 9. Verification

Independent verification rejects:

- bundle mismatch;
- capability records without evidence artifacts;
- routes counted as verified products without product evidence;
- non-null unavailable infrastructure values;
- inferred district coverage;
- smart-city, digital-maturity or coverage scores;
- open UWM mechanisms without operational time series and calibration;
- fabricated values above zero.

## 10. Maximum Claim and Ledger

Maximum claim:

```text
platform_digital_capability_and_district_smart_infrastructure_evidence_readiness
```

Demand 17 target:

```text
implementation_status=implemented_evidence_bounded
```

This product does not claim that Chongqing districts have been assessed for smart-infrastructure coverage or digital maturity.

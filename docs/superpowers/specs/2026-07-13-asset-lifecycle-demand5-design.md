# Asset Lifecycle Demand 5 Design

## Objective

Implement a cross-product asset catalog and lifecycle/UWM readiness product without fabricating a deduplicated enterprise asset register, ownership, condition, value, maintenance history or lifecycle transitions.

## Method Ownership

- Traditional asset management/GIS owns authoritative asset identity, entity resolution, type taxonomy, location, ownership, condition, valuation, maintenance, inspection and lifecycle reporting.
- UWM consumes verified asset state sequences, dependencies, interventions, failures, degradation and recovery labels.
- Product counts from buildings, facilities, POIs and cultural-place products must not be summed into a unique asset count without entity-resolution evidence.

## Source Product Classes

- visible buildings and infrastructure inventory
- social/public-service facilities
- public spaces
- cultural places and heritage candidates
- business/activity POIs
- digital platform capability catalog

Each source is registered as a product reference with its own semantic scope, bundle identity and overlap limitations.

## Lifecycle Channels

- authoritative asset identifier
- asset type taxonomy
- geometry/location
- ownership/custodian/operator
- commissioning/acquisition date
- lifecycle status
- observed condition
- inspection records
- maintenance work orders
- failure events
- repair/replacement events
- capacity/service role
- valuation/cost basis
- dependency relationships
- decommission/disposal
- successor asset

All lifecycle channels remain unavailable until authoritative records are connected.

## UWM Gate

Close entity resolution, state materialization, degradation modelling, failure transition learning, maintenance response, dependency propagation, replacement planning, recovery modelling and future rollout.

## Claim Boundary

Maximum claim: `cross_product_asset_catalog_lifecycle_contract_and_uwm_asset_state_readiness`.

Mandatory exclusions:

- source record count is not unique asset count
- POI is not authoritative asset
- building footprint is not ownership or condition
- facility category is not service capacity
- cultural candidate is not registered heritage asset
- missing maintenance is not good condition
- catalog presence is not lifecycle observation
- lifecycle contract is not degradation calibration

## Publication

Publish six files: `overview.json`, `source_products.json`, `lifecycle_channels.json`, `data_contracts.json`, `lifecycle_gate.json`, and `map.json`; expose authenticated APIs and an `资产与生命周期` tab.

# Infrastructure Network Demand 4 Design

## Objective

Implement visible-infrastructure inventory and municipal-network/UWM cascade readiness without fabricating underground utility assets, capacity, ownership, operational state, failures or recovery.

## Method Ownership

- Traditional GIS owns road/building/network inventory, topology construction, service areas, capacity diagnostics and observed condition summaries.
- UWM consumes verified infrastructure state nodes, dependency edges, load/capacity observations, failure events, interventions and recovery labels.
- Generic roads, buildings, commuting records and field standards must not be reinterpreted as water, drainage, power, gas or telecom networks.

## Current Evidence

- Chongqing OSM roads 2021 audit: 50,366 LineString features with road class, direction and speed-related fields.
- Central Chongqing building footprints 2021 audit: 107,452 Polygon features with ID and floor fields.
- China Unicom commuting table 2023: 2,120 OD rows, but grid geometry dictionary and semantic details are unresolved; it is an activity proxy, not telecom infrastructure.
- Repository one-map standards contain utility-related field definitions but not customer utility observations.

## Infrastructure Channels

- road network
- buildings and visible structures
- water supply network
- drainage/sewer network
- electricity network
- gas network
- telecom/fibre network
- district energy network
- utility nodes and facilities
- network topology
- capacity and design rating
- ownership/operator
- observed load/pressure/flow
- condition and maintenance
- outage/failure events
- restoration and recovery
- cross-network dependencies

Only roads/buildings may be marked as audited visible assets. Utility observation channels remain unavailable.

## UWM Kernel Gate

Close infrastructure state materialization, utility topology, capacity stress, failure propagation, cross-network cascade, intervention response, repair scheduling, recovery dynamics and future rollout. Road graph use for accessibility does not open utility cascade mechanisms.

## Claim Boundary

Maximum claim: `visible_infrastructure_inventory_utility_data_contract_and_cascade_kernel_readiness`.

Mandatory exclusions:

- road line is not utility pipe/cable
- building footprint is not asset condition
- commuting OD is not telecom network
- field standard is not observed infrastructure
- asset count is not service capacity
- missing outage is not reliable operation
- topology availability is not failure propagation calibration

## Publication

Publish six files: `overview.json`, `infrastructure_assets.json`, `utility_channels.json`, `data_contracts.json`, `kernel_gate.json`, and `map.json`; expose authenticated APIs and an `基础设施与市政管网` tab.

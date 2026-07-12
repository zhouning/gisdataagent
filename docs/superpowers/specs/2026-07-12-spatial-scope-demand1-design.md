# Spatial Scope Demand 1 Design

## Objective

Implement a verified spatial-scope and administrative-unit registry for demand 1, using the existing Chongqing township geometry while preserving its fragile evidence boundary.

## Method Ownership

- Traditional GIS owns geometry inventory, CRS inspection, hierarchy extraction, extent calculation, identity keys, topology/validity diagnostics and product-scope registration.
- UWM renderer and kernel consume immutable spatial identities, geometries and graph references.
- The registry does not predict boundaries, population, land use or policy outcomes.

## Source Boundary

The current source contains 1,017 township/street features across 38 county-level names in EPSG:4326. Its local source licence, official vintage and topology are not verified, and historical county names exist. The original source bounds recorded in the manifest span beyond Chongqing and must not be used as the derived dataset boundary.

## Registry Contract

Each spatial unit includes:

- stable derived unit identifier
- province, city, county and township names
- hierarchy level and parent identifier
- geometry type
- CRS
- source dataset and source feature index
- geometry bounds
- evidence status and limitations

Identity is derived from normalized hierarchy plus source feature index because authoritative administrative codes are absent.

## Diagnostics

Publish counts for missing names, duplicate hierarchy labels, empty geometries, unsupported geometry types, invalid coordinate ranges and historical county-name warnings. Do not silently repair or rename official units.

## Scope Registry

Register the source dataset, derived township scope, county-name aggregation scope, map layer role and downstream compatibility. A dataset extent is descriptive and is not a legal administrative boundary.

## UWM Boundary

The product may support renderer alignment, graph node identity, evidence joins and kernel state indexing. Kernel propagation must continue to use independently verified adjacency and may not infer connectivity from bounding-box overlap.

## Claim Boundary

Maximum claim: `fragile_spatial_scope_admin_unit_registry_and_uwm_identity_readiness`.

Mandatory exclusions:

- local geometry is not verified current legal boundary
- derived identity is not authoritative administrative code
- extent is not jurisdiction
- county-name aggregation is not dissolved official county geometry
- geometry presence is not topology validity
- registry compatibility is not downstream empirical validity

## Publication

Publish six files: `overview.json`, `spatial_units.json`, `scope_registry.json`, `diagnostics.json`, `data_contracts.json`, and `map.json`; expose authenticated APIs and an independent `空间范围注册` tab.

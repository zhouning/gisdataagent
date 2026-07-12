# Planning and Parcel Version Demand 2 Design

## Objective

Implement a planning and parcel-version asset registry from the existing local planning ZIP audit without claiming that profiled sample/demo assets form an authoritative current planning or cadastral version history.

## Method Ownership

- Traditional GIS/data governance owns asset profiling, version metadata, temporal validity, source lineage, spatial scope and comparability checks.
- UWM consumes approved temporal baselines and successor relationships for state initialization and transition evaluation.
- UWM must not infer plan approval, effective dates or parcel history from filenames, folder names or audit creation dates.

## Asset Classes

- current land-use parcel layer
- village planning database collection
- land-development/approval ledger
- administrative/cadastral reference layer
- planning database structure standard

## Version Contract

An authoritative planning/parcel version requires source authority, approval/publication identifier, version identifier, effective start/end, spatial applicability, object type, CRS, schema, immutable source hash, predecessor/successor relationship, change reason and citation.

## Current Evidence

The local audit profiles a Bishan DLTB layer with 101,657 features, a Fulu village-planning collection with 8,050 features across 28 layers, a 2019 Bishan development ledger with 1,438 rows, and administrative/cadastral reference layers. These are useful inventory evidence but source licence, approval status, effective periods and supersession chains remain unresolved.

## Temporal Gate

The following remain closed:

- authoritative baseline selection
- current-version resolution
- predecessor/successor traversal
- parcel history reconstruction
- plan amendment comparison
- temporal join to observed outcomes
- UWM state initialization from approved plan
- UWM transition attribution to planning change

## Claim Boundary

Maximum claim: `planning_parcel_asset_inventory_version_contract_and_temporal_baseline_readiness`.

Mandatory exclusions:

- audit creation time is not plan effective date
- folder year is not authoritative version
- sample/demo asset is not approved planning database
- DLTB feature is not legal parcel title
- ledger row is not spatial parcel history
- asset inventory is not version lineage
- missing successor is not current status

## Publication

Publish six files: `overview.json`, `version_assets.json`, `version_channels.json`, `data_contracts.json`, `temporal_gate.json`, and `map.json`; expose authenticated APIs and a `规划与地块版本` tab.

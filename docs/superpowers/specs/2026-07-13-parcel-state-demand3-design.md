# Parcel State Demand 3 Design

## Objective

Implement a parcel/land-use state evidence and UWM state-input readiness product from the verified audit metadata, without fabricating feature-level land-use distributions, legal parcel status, planning conflicts or temporal transitions.

## Method Ownership

- Traditional GIS owns feature ingestion, land-use code validation, current/planned overlay, area aggregation, geometry diagnostics, status classification and descriptive conflict screening.
- UWM consumes a versioned `t0` parcel state, feasible action objects, observed `t1` labels and transition evidence.
- UWM must not create current land-use observations or transition labels from metadata-only audits.

## Current Evidence

The Bishan DLTB audit reports 101,657 MultiPolygon features in EPSG:4610 with fields `BSM`, `YSDM`, `DLBM`, `DLMC`, ownership/location names, `TBMJ`, length and area. The source layer itself is not materialized in the repository worktree and its planning version/effective period remain unverified.

## State Channels

- source feature geometry
- stable parcel/feature identifier
- current land-use code and name
- planned land-use code and name
- observed area
- administrative join
- ownership/right-holder context
- development/approval status
- current-versus-planned relation
- observed baseline timestamp/version
- observed successor state
- transition label
- action/intervention linkage

All channels remain unavailable until authoritative feature rows are materialized and pass the demand-2 version gate.

## UWM State Contract

Required fields include state node ID, source feature ID, geometry reference, current state code, state taxonomy version, observation time, source version bundle, quality flags, action eligibility, successor observation and provenance.

## Gates

Close current-state materialization, code-domain validation, area aggregation, current/planned overlay, legal-status classification, conflict screening, UWM `t0` initialization, transition-label construction, action-conditioned learning and future rollout.

## Claim Boundary

Maximum claim: `parcel_land_use_schema_audit_state_contract_and_uwm_transition_readiness`.

Mandatory exclusions:

- audited feature count is not current land-use distribution
- DLTB identifier is not legal parcel title
- land-use class is not development permission
- folder/profile metadata is not observed parcel state
- missing planned use is not no conflict
- missing successor is not persistence
- schema readiness is not transition calibration

## Publication

Publish six files: `overview.json`, `source_assets.json`, `state_channels.json`, `data_contracts.json`, `state_gate.json`, and `map.json`; expose authenticated APIs and a `用地与地块状态` tab.

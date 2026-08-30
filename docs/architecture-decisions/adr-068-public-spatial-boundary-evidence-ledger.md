# ADR-068: Admit public spatial snapshots without admitting boundary hydrographs

## Status

Accepted

## Context

Stage 26 advanced manufactured local perturbations around 20 observed hydraulic
states, but it intentionally lacked observed neighboring states and real reach
boundaries. The next requirement was to search public data for spatially distinct
observations around NHDPlus COMID `18421703`. Repeated observations at the
existing Stonewall gauge could not be relabeled as neighboring cells.

The search had to work without user-provided data and remain reproducible,
bounded, topology first, and fail closed. A negative result would have required
an executable boundary-data refusal. A positive result still required a separate
decision about the level of evidence actually supported.

## Decision drivers

- Candidate sites must be discovered through NLDI navigation from COMID
  `18421703`, not selected after looking at favorable values.
- Every candidate must retain topology direction, COMID, coordinates, distance,
  parameter, unit, temporal support, source hash, license, and request limits.
- A spatial match must contain observations from two distinct sites.
- A discrete candidate observation may match a continuous anchor only when real
  anchor values bracket its time; interpolation must not create a value.
- Provisional USGS status must remain visible.
- Snapshot evidence, continuous boundary conditions, travel-time calibration,
  observed rollout, and runtime admission must be separate decisions.

## Public search boundary

The acquisition used three NLDI navigations:

| Direction | Distance bound |
|---|---:|
| Upstream tributaries | 10 km |
| Upstream main | 50 km |
| Downstream main | 50 km |

It allowed at most 12 discovered candidates, four matched-value windows, 43
requests, and 34 MB. The actual run made 38 requests, downloaded `986,047`
bytes, and returned 11 sites: ten spatially distinct candidates plus the anchor.
Six spatial candidates share the anchor's GeoConnex Caney Fork mainstem.

Only the NLDI-returned identifiers were sent to the USGS monitoring-location,
time-series-metadata, and field-measurement collections. The source is USGS
public-domain data. No workspace or private data was sent.

## Evidence found

The same-mainstem upstream site `USGS-03424010`, bound to COMID `18421761`, is
`12,018.661 m` from the Stonewall anchor by WGS84-coordinate great-circle
distance. NLDI identifies it as upstream main; the API did not return an exact
route distance.

The site has no continuous discharge series in the queried USGS time-series
catalog, but it has two public field discharge measurements inside the anchor's
continuous discharge coverage. Bounded anchor-value queries produced:

| Candidate time | Upstream field Q | Anchor bracket | Nearest offset | Ratio to anchor bracket mean |
|---|---:|---:|---:|---:|
| 2024-05-16 14:40:55Z | 22,700 ft3/s | 22,400 ft3/s at 14:30 and 15:00 | 655 s | 1.0134 |
| 2026-02-10 16:49:30Z | 274 ft3/s | 602 ft3/s at 16:30 and 17:00 | 630 s | 0.4551 |

Both candidate measurements are provisional. All four bracketing anchor values
are approved. Each candidate time lies inside a 1,800-second real observation
bracket and within 900 seconds of the nearest anchor value. No interpolation was
performed.

The large difference in the second pair is evidence against treating a
near-synchronous pair as an instantaneous conservation identity. The sites are
about 12 km apart on a dam-controlled river. Propagation delay, storage, lateral
inflow, operational releases, and measurement revision remain unresolved.

## Considered options

### Option 1: Reject all spatial evidence

This would be correct if no second observation existed, but it would discard two
real, topology-bound snapshot pairs found by the bounded search.

### Option 2: Admit the snapshots as boundary hydrographs

This would enable a spatial rollout immediately, but two provisional field
measurements do not define a continuous upstream process. Bracketing downstream
values also do not identify travel time or lateral inflow.

### Option 3: Admit snapshot evidence and keep runtime boundaries closed

This preserves the new spatial information while preventing it from silently
becoming a time series, calibrated transport relation, or complete reach state.

## Decision

Adopt Option 3.

Add `public_spatial_boundary_evidence.py` as a typed evidence ledger. A snapshot
is admitted only when:

- the candidate was returned by bounded NLDI navigation;
- it is spatially distinct from `USGS-03424860`;
- candidate and anchor parameter codes and units agree;
- approved anchor observations occur before and after the candidate time;
- the bracket is at most 1,800 seconds;
- the nearest anchor observation is at most 900 seconds away; and
- no interpolated value is presented as observed.

The ledger returns the two synchronized snapshots. It raises typed errors for
continuous boundary hydrographs, fully approved spatial snapshots, observed
spatial rollout, and substitution of anchor history for a neighbor.

## Consequences

### Positive

- The kernel now contains real two-location hydraulic evidence rather than only
  temporal anchors or manufactured spatial perturbations.
- Topology, spatial support, time support, units, approval state, and claim level
  are executable together.
- The result distinguishes an evidence admission from an operator admission.

### Negative

- Only two snapshot pairs are available.
- The candidate observations are provisional.
- No continuous upstream hydrograph or downstream stage boundary was found.
- The observations do not identify propagation delay or close a reach ledger.

### Risks and mitigations

- A consumer could compare the two values as if simultaneous at one state.
  Mitigation: the ledger records distance, bracket offsets, no interpolation,
  and refuses travel-time and rollout claims.
- USGS may revise provisional field values. Mitigation: approval status is
  preserved and fully approved admission fails closed.
- Straight-line distance could be mistaken for channel distance. Mitigation:
  the distance method explicitly records that NLDI route distance was not
  returned.

## Meaning for the Geospatial Kernel

A traditional GIS workflow can join two station tables to a stream layer and
calculate their distance. The Geospatial Kernel adds a different contract: the
network direction and support determine whether observations can be related;
parameter and unit identity determine whether they can be compared; time support
determines whether they form a snapshot; and evidence status determines which
physical operators may consume them. A valid spatial join is therefore necessary
but not sufficient for a world-model transition.

## Evidence

All 21 Stage 27 gates pass:

- all seven Stage 26 artifacts retain their frozen hashes;
- 38 source artifacts are hash verified;
- 11 NLDI sites and ten spatial candidates are bound;
- topology, COMID, coordinates, distance, parameters, units, and time support
  remain explicit;
- both spatial snapshots satisfy the real bracketing and timing contract;
- provisional and approved statuses remain distinct; and
- continuous-boundary, fully-approved, rollout, and same-site-substitution
  claims fail closed.

## Next work

Stage 28 should search for public Center Hill operational release or tailwater
time series that can turn the two snapshots into a travel-time-aware diagnostic.
Any such source must be bound to the same physical outlet and units before it is
used. Until a continuous upstream series and a defensible propagation contract
exist, no reach boundary-conditioned rollout is admitted.

## Artifacts

- Acquisition:
  `scripts/acquire_geotransport_stage27_public_spatial_boundary_evidence.py`
- Kernel ledger:
  `data_agent/uwm/geospatial_kernel_v2/public_spatial_boundary_evidence.py`
- Tests:
  `data_agent/test_acquire_geotransport_stage27_public_spatial_boundary_evidence.py`
  and `data_agent/test_geospatial_kernel_public_spatial_boundary_evidence.py`
- Evidence ledger:
  `data/geotransport_v0_1/stage27_center_hill_spatial_boundary_evidence/spatial_boundary_evidence_ledger.json`
- Gate report:
  `benchmarks/geotransport_v0_1/stage27_public_spatial_boundary_gates.json`

## Related decisions

- ADR-062: Bounded public confluence spatial fixture
- ADR-064: Public reach observed hydraulic state binding
- ADR-067: Observed-anchor local perturbation transition

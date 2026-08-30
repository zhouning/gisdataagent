# ADR-069: Admit bounded operational boundaries without admitting travel time

## Status

Accepted

## Context

Stage 27 found two real spatial discharge snapshots between the Center Hill
tailwater area and the downstream Stonewall gauge. Those snapshots established
that spatially distinct observations exist, but two provisional field
measurements could not provide a continuous upstream boundary or identify a
transport delay.

The next task was to find public operational data without requiring any
user-provided dataset. The repository already named the USACE CWMS series
`CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev`, but earlier use of that name
was not sufficient evidence that it represented the same sensor or measurement
process as USGS `03424010`. Stage 28 therefore had to establish the source
identity and spatial role again, preserve its time-support semantics, and test
transferability before admitting any travel-time or rollout claim.

## Decision drivers

- Lag candidates must be fixed before value access.
- Requests must be public, bounded, hash verified, and private-data free.
- A CWMS location can be bound to a physical site zone by metadata and
  coordinate proximity without being declared identical to a USGS sensor.
- An hourly average release timestamp represents the end of a one-hour support,
  not an instantaneous state.
- USGS half-hour instantaneous samples may be summarized by hour only from real
  samples; missing samples must not be filled.
- Development and transfer evidence must remain distinct.
- A lag cannot be identified from a constant input series.
- A diagnostic lag is not automatically a travel-time parameter or rollout
  operator.

## Public acquisition boundary

Before reading values, the acquisition plan fixed:

- two 72-hour windows, `2024-05-15` through `2024-05-18` and `2026-02-09`
  through `2026-02-12`;
- integer lag candidates from 0 through 12 hours;
- the 2024 window as development and the 2026 window as transfer;
- a maximum of six requests and 5 MB; and
- a no-fill hourly aggregation policy.

The run made six requests and downloaded `253,150` bytes. It acquired one CWMS
location object, one exact CWMS catalog object, two CWMS value objects, and two
USGS continuous-value objects. No workspace or private data was sent.

The local proxy returned CWMS TLS connection failures. The bounded fallback
used `curl --resolve` with IP `3.30.180.152`. The request URL, TLS server name,
and certificate hostname verification remained
`cwms-data.usace.army.mil`; neither `--insecure` nor a disabled certificate
check was used. Failed proxy attempts remain in the acquisition manifest.

## Spatial and source evidence

The official CWMS location response identifies:

| Field | Value |
|---|---|
| Name | `CETT1-CENTER_HILL` |
| Public name | Center Hill Dam Tailwater |
| Location type | Tailwater |
| Coordinate | `(-85.8261235, 36.0975966)` |
| Horizontal datum | NAD83 |
| Office | LRN |
| Active | true |

The Stage 27 upstream site `USGS-03424010` is at
`(-85.8272071200994, 36.0978377798611)` in WGS84. Direct coordinate proximity
is `100.986 m`, inside the predeclared 250 m upstream-site zone. No NAD83 to
WGS84 datum transformation was applied, so this supports a physical tailwater
zone binding rather than exact point identity.

The exact CWMS catalog result reports:

- office `LRN`;
- unit `cms`;
- interval `1Hour` with zero offset;
- coverage from `1987-05-20T05:00:00Z` through
  `2026-07-28T05:00:00Z`; and
- aliases including `Outflow` and `Total Flow`.

These fields admit the series as public operational release evidence. They do
not prove that CWMS and USGS use the same instrument, revision workflow, or
sampling process. CWMS quality code `0` is retained but is not relabeled as the
USGS approval state `Approved`.

## Time-support compilation

Each source query is inclusive at both ends. A 72-hour CWMS query therefore
returns 73 hourly values. Because each value is a one-hour average timestamped
at its support end, the value at the query start summarizes an hour outside the
window and is excluded. The remaining 72 values represent supports `(t-1h,t]`.

Each USGS query returns 145 half-hour instantaneous samples. For every target
hour, the compiler uses exactly the samples at `t-30m` and `t`, converts
`ft3/s` to `m3/s` with factor `0.028316846592`, and takes their arithmetic mean.
Both events yield 72 complete hours, all USGS samples are `Approved`, and no
missing value is filled.

For lag `L`, release support ending at `t` is compared with downstream hourly
support ending at `t+L`. Pair counts therefore decrease from 72 at lag 0 to 60
at lag 12. Metrics include bias, MAE, RMSE, Pearson correlation, and both series'
standard deviations.

## Evidence found

The 2024 development release varies over `157.80978606 m3/s`. Among the
predeclared candidates, lag 6 hours has the highest Pearson correlation:

| Metric | Value |
|---|---:|
| Pair count | 66 |
| Pearson r | 0.9537370044 |
| RMSE | 21.59562436 m3/s |
| Mean downstream-minus-release bias | -2.77333479 m3/s |

This is admitted as a development correlation diagnostic only. The metric does
not separate channel travel, dam reporting semantics, storage, lateral inflow,
or downstream measurement response.

The 2026 transfer release is exactly `7.07921165 m3/s` for all 72 in-window
supports. Every lag candidate therefore has zero release standard deviation and
undefined Pearson correlation. The transfer lag is unidentifiable, so the 6-hour
development result cannot pass a cross-event stability test.

The two Stage 27 provisional field measurements fall inside real CWMS hourly
supports:

| Event | Field Q | CWMS release | Field/CWMS ratio |
|---|---:|---:|---:|
| 2024 | 642.792418 m3/s | 640.753605 m3/s | 1.003182 |
| 2026 | 7.758816 m3/s | 7.079212 m3/s | 1.096000 |

The proximity is useful cross-source consistency evidence. It does not validate
exact sensor identity because the field measurements are provisional and the
measurement support and revision processes differ.

## Considered options

### Option 1: Reject CWMS because exact sensor identity is unproven

This would preserve a strict identity standard but discard an official,
location-bound operational release series whose spatial role and support are
independently explicit.

### Option 2: Treat the 2024 six-hour result as calibrated travel time

This would immediately enable a shifted boundary rollout, but it would use the
same event for selection and justification and ignore the zero-information
transfer event. Correlation alone also cannot close the reach mass balance.

### Option 3: Admit operational windows and a development diagnostic only

This preserves the newly verified boundary process while keeping sensor
identity, transferable travel time, observed rollout, and runtime admission
closed until independent evidence exists.

## Decision

Adopt Option 3.

Add `public_operational_boundary_evidence.py` as a typed evidence ledger. It
admits both bounded operational release windows, the tailwater site-zone
binding, the real-sample downstream hourly aggregation, and the 2024 six-hour
development diagnostic.

The ledger raises typed errors for exact sensor crosswalk, transfer-identified
lag, stable travel time, boundary-conditioned rollout, and promotion of the lag
to a runtime operator. The 2026 zero-variance result is a first-class refusal,
not a missing implementation detail.

## Consequences

### Positive

- The Geospatial Kernel now has a real public operational boundary process,
  independently acquired without user data.
- Spatial zone, source identity, units, temporal support, aggregation, quality,
  and admissible claims are compiled together.
- The same kernel that finds a strong development correlation also detects when
  a transfer event cannot identify a lag.

### Negative

- Only one event contains useful release variation.
- The 6-hour result is not independently transferable.
- Lateral inflow and storage are not included in this diagnostic.
- No observed boundary-conditioned spatial state rollout has been executed.

### Risks and mitigations

- Coordinate proximity could be mistaken for exact station identity.
  Mitigation: the binding is explicitly zone-level and records both datums.
- CWMS quality code `0` could be mistaken for USGS approval. Mitigation: the
  code is preserved without interpretation and approval vocabularies remain
  separate.
- A high correlation could be promoted directly into physics. Mitigation: the
  transfer event must identify a consistent lag before travel-time admission.
- Event selection could become post hoc. Mitigation: windows, roles, lag set,
  and selection metric are frozen in a hashed plan before acquisition.

## Meaning for the Geospatial Kernel

A traditional GIS package can calculate the 101 m coordinate distance, join the
two site records, resample time series, and compute lagged correlation. Those
operators usually return a result whenever their input tables are syntactically
compatible.

The Geospatial Kernel adds executable semantic conditions around those same
computations: coordinate proximity creates only a site-zone relation; temporal
support determines legal aggregation; unit conversion precedes comparison;
source quality vocabularies cannot be conflated; zero input variance blocks lag
identification; and development evidence cannot silently become a transferable
transition operator. The kernel is therefore not a replacement implementation
of GIS resampling or distance. Its distinctive role is to constrain when a
geospatial relation is meaningful enough to enter world-model state evolution.

## Evidence

All 25 Stage 28 gates pass:

- all nine Stage 27 artifacts retain frozen hashes;
- all six Stage 28 source objects are hash verified;
- the acquisition plan hash proves that both windows and all 13 lag candidates
  were declared before value access;
- tailwater zone, catalog, aliases, units, and time support are explicit;
- 144 release hours and 144 downstream aggregate hours contain no filled data;
- the 2024 development diagnostic is reproducible;
- the 2026 zero-variance transfer refusal is executable; and
- sensor identity, travel time, rollout, and runtime claims fail closed.

## Next work

Stage 29 should independently search the public CWMS history for at least two
additional release-transition events. Event eligibility must be frozen from
release-side criteria such as minimum range, step magnitude, completeness, and
separation before downstream values are inspected. One event may extend
development, but at least one untouched event must remain for transfer. The next
diagnostic should also add public lateral-inflow or tributary evidence before a
boundary-conditioned rollout is considered.

## Artifacts

- Acquisition:
  `scripts/acquire_geotransport_stage28_public_operational_boundary_evidence.py`
- Kernel ledger:
  `data_agent/uwm/geospatial_kernel_v2/public_operational_boundary_evidence.py`
- Tests:
  `data_agent/test_acquire_geotransport_stage28_public_operational_boundary_evidence.py`
  and
  `data_agent/test_geospatial_kernel_public_operational_boundary_evidence.py`
- Evidence ledger:
  `data/geotransport_v0_1/stage28_center_hill_operational_boundary_evidence/operational_boundary_evidence_ledger.json`
- Gate report:
  `benchmarks/geotransport_v0_1/stage28_public_operational_boundary_gates.json`

## Related decisions

- ADR-064: Public reach observed hydraulic state binding
- ADR-067: Observed-anchor local perturbation transition
- ADR-068: Public spatial-boundary evidence ledger

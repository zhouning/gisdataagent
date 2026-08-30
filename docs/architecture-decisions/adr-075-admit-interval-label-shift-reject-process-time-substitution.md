# ADR-075: Admit interval label shift, reject process-time substitution

## Status

Accepted

## Context

ADR-074 admitted the directed Center Hill tailwater-to-Stonewall path but found
no overlap between the Stage 32 empirical union `{5,6,7}h` and three same-path
physics time envelopes. That numerical result still left a more fundamental
question unresolved: were the four quantities measurements of the same event
functional in the first place?

They were not:

- the empirical lag is the peak of a windowed linear association between two
  hourly end-labelled series;
- gravity-wave time describes first hydraulic signal arrival;
- Manning kinematic time describes the centroid of a discharge perturbation;
  and
- NWM advective residence describes the exit centroid of water mass.

All are expressed in hours and all can be attached to one path. Neither fact
makes them substitutable.

Stage 34 therefore moves the Kernel below numerical interval comparison. It
types the observation supports, transport carriers, source event markers, and
target response functionals that give each time quantity its meaning.

## Decision drivers

- No new release or downstream outcome values may be requested.
- The CWMS series meaning must be supported by fixed-commit public
  documentation rather than inferred only from its name.
- Native source and target observations must retain different statistics.
- Missing Stage 32 target hours must remain missing.
- A useful label-alignment operation should be admitted where the evidence
  supports it.
- Matching time units, path identity, or numerical overlap must not erase
  process semantics.
- Release actuation instant and continuous target-hour mean must fail closed
  when the available observations do not identify them.
- Physical response and runtime promotion remain separate gates.

## Public documentation acquisition

The `TemporalResponseSemantics` operator was frozen first with SHA-256
`8632158a2ecfe194f6419fc6ceab5f7eca7ef958cc694a8719742b97ffd90bdd`.
The acquisition plan was then frozen with SHA-256
`86b646f133e705a226afbc079bd1d4d02f814fc0f6b7f05be589c77413f8c043`.

The plan allowed one request to a fixed USACE `cwms-data-api` commit and a
maximum of 500 KB. It sent no workspace or private data and requested no
release or downstream observations.

The request downloaded `11,453` bytes from commit
`beb8d507c9da8ec074d444117bda7d7daf69e5ee`. The document SHA-256 is
`997fd03b31e798d1f434c7e9d5b56a4a2c9c8d578c2432c3c8ed07019f778f70`.
The fixed document states that:

- duration `0` is instantaneous and not a composite over time;
- duration `1Hour` is a composite of input data over a one-hour window;
- USACE stores composite samples at end of period by default; and
- stored CWMS data use UTC.

These findings independently support the existing
`CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev` interpretation.

## Observation semantics

The source and target fields are compiled separately:

| Field | Native statistic | Compiled support | Label |
|---|---|---|---|
| CWMS release | authoritative interval average | 3600 s interval mean | end |
| USGS Stonewall | instantaneous points, statistic `00011` | derived mean of two 30-minute samples | end |

The USGS primary discharge series is independently identified as
`1eed13fd6d90461fa6a04892af197e6d`, parameter `00060`, computation period
`Points`, and computation `Instantaneous`.

Every compiled Stage 32 target hour uses the real samples at `t-30m` and `t`.
Complete-hour counts remain `84/84/77/84`; the seven missing third-event hours
are not filled. All samples used by compiled hours retain `Approved` status.

Both fields therefore support a 3600-second interval-end label grid for lagged
association. They do not have physical observation equivalence:

- an hourly composite release cannot identify when an actuator moved within
  its support interval; and
- the arithmetic mean of two instantaneous target samples is not a continuous
  integral mean over the hour.

## Process-time semantics

The operator represents each time quantity by four linked identities:

| Quantity | Carrier | Source marker | Target functional |
|---|---|---|---|
| Empirical lag | discharge series | interval-end label step | association peak |
| Gravity-wave time | hydraulic disturbance | physical boundary perturbation | first signal arrival |
| Manning centroid time | discharge perturbation | physical boundary perturbation | response centroid |
| Advective residence | water mass | material injection | material-exit centroid |

For every physics candidate, Stage 34 records five independent rejection
reasons:

1. transport carrier mismatch;
2. source event marker mismatch;
3. target response functional mismatch;
4. candidate physical-response admission is absent; and
5. numerical supports are disjoint.

This separation matters even in a hypothetical case where the intervals
overlap. Numerical overlap would remove only reason 5; it would not change the
carrier or event functional.

## Decision

Admit the public temporal-semantics evidence and the `3600s` interval-end
label-shift grid for empirical association diagnostics.

Reject release actuation instant, target continuous-hour average, physical
observation equivalence, physical response-time substitution, and runtime
transition promotion.

The admitted label shift remains useful evidence about how two published
series co-vary. It is not a hydraulic edge delay.

## Kernel versus traditional GIS implementation

Traditional GIS and time-series systems can attach both stations to a network,
resample both tables by hour, shift one timestamp column, calculate a
correlation, and join any travel-time attribute expressed in hours. Those are
valid component operations.

The Geospatial Kernel adds a law above those operations:

- temporal support and timestamp label are separate objects;
- interval averages and sample means remain different statistics;
- a published interval-end label is not silently converted to a physical event
  instant;
- time dimension, path identity, carrier, source marker, and target functional
  are checked independently;
- removing one rejection reason does not erase the others; and
- only explicitly admitted consumers can use the result.

Thus the difference is not a new implementation of temporal join or lagged
correlation. It is an executable semantic type system governing when those
results may enter world-model state and transition logic.

## Consequences

### Positive

- Stage 34 admits a concrete temporal reasoning primitive instead of returning
  an undifferentiated rejection.
- Existing empirical results retain their correct diagnostic use.
- Observation aggregation, physical propagation, and material transport can no
  longer be conflated by unit equality.
- The result uses independently acquired public documentation and existing
  public observations only.
- Every refusal is executable and machine-readable.

### Negative

- The source data still do not locate the physical actuation within an hour.
- The target aggregation remains a two-point approximation.
- No current time quantity can drive a runtime propagation edge.
- The new type system may reject workflows that ordinary GIS software would
  execute syntactically.

### Follow-up

Stage 35 should make event-time uncertainty set-valued. The one-hour source
support and half-hour target sampling support can be propagated as temporal
sets before comparing them with physical envelopes. This can test whether
measurement-support uncertainty is large enough to explain any discrepancy
without moving observed values or tuning a hydraulic parameter. An exact
actuation claim still requires independently sourced subhourly operational
evidence.

## Evidence

All 34 Stage 34 gates pass. They verify that:

- all 13 Stage 33 controlled artifacts retain frozen hashes;
- the operator, acquisition order, fixed document commit, hash, and TLS
  verification remain intact;
- source and target temporal supports reproduce from public evidence;
- the admitted label grid is exactly `3600s`;
- all Stage 32 real-hour, missing-hour, and approval semantics are preserved;
- all four process-time identities remain distinct; and
- physical observation, physical response, and runtime access fail closed.

The reconciliation ledger SHA-256 is
`45b5a51d4ec0500e9288dd97b1a41a9632c9c95d45c7a959a65ffc4cab8a101c`.
The gate status is
`interval_label_shift_admitted_physical_response_semantics_rejected`.

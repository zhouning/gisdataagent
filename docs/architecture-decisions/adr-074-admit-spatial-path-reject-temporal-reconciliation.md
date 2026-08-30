# ADR-074: Admit the spatial path, reject temporal reconciliation

## Status

Accepted

## Context

ADR-073 admitted event-local `EmpiricalLagSupport` but rejected a common
Center Hill-to-Stonewall support set. The four frozen Stage 32 event sets were
`{5,6,7}`, `{6,7}`, `{7}`, and empty. Their union is `{5,6,7}`, while their
intersection is empty.

That result did not end the Geospatial Kernel mission. It exposed the next
kernel question: can an empirical response-lag support be reconciled with an
independently located source-target path and with physical temporal quantities
defined on that path?

These propositions must remain separate:

1. the operational source and observed target lie on one directed flow path;
2. a physics calculation produces a typed time support on that path;
3. empirical and physical supports overlap numerically;
4. the physical quantity is admissible as downstream response lag;
5. all blind events have common empirical support; and
6. the reconciled support may drive a runtime world-model transition.

Stage 33 evaluates these propositions without acquiring another outcome
window. The remaining 2021-2025 release candidates, after the frozen Stage
28-32 exclusion neighborhoods, do not provide another independent four-event
holdout with the required excitation support. Reusing outcomes or weakening
the protocol would create a posthoc positive result rather than new evidence.

## Decision drivers

- No private or user-supplied data may be required.
- A public source-target path must be acquired independently of release and
  downstream outcome values.
- The source zone, target snap tolerance, direction, and maximum request count
  must be frozen before path values are acquired.
- Empirical response lag, gravity-wave time, kinematic centroid time, and
  advective residence time must remain distinct physical quantities.
- Numerical overlap is necessary but not sufficient for physical validation.
- Common empirical support across every blind event is required for admission.
- A failed reconciliation must preserve valid spatial knowledge and reject only
  the unsupported temporal and runtime promotions.
- All Stage 32 protocol and refusal artifacts must remain hash frozen.

## Typed reconciliation operator

`DiscreteTemporalSupport` represents the observation-derived empirical union.
It requires a located relation, sorted discrete hours, provenance, and the
explicit fact that the values are outcome derived. It always reports that
physical time is unadmitted.

`ContinuousTemporalSupport` represents a physics candidate with:

- a path identity;
- one admitted quantity name;
- lower, central, and upper times;
- provenance and state-dependence flags;
- whether outcome calibration was used; and
- whether the evidence admits the value as physical response time.

`TemporalSupportCompatibility` computes discrete hours inside a continuous
interval and the minimum separation when there is no overlap. Physical
consistency requires the same spatial path, an admitted physical quantity, and
numerical overlap.

`GeospatialTemporalSupportReconciliation` adds the cross-event requirement.
Even a same-path numerical overlap cannot pass unless all frozen blind events
share empirical support. Runtime promotion remains a separate fail-closed
method.

The operator was frozen before NLDI path acquisition with SHA-256
`62bda56dedfb65995556aa4964ea220c4ea8a9976738694f2e784cd664b360d1`.

## Public path acquisition

The acquisition plan SHA-256 is
`55f2618d7d6508a0b6e0ef4556d934514f8f42ea20a208e4272d53e27d0f76b8`.
It allowed one public USGS NLDI downstream-main request from source COMID
`18421761`, bounded to 50 km and 2 MB. It requested no release or downstream
outcome values and sent no workspace or private data.

The request downloaded `12,096` bytes. The raw response SHA-256 is
`80658a566575b65a89961ecb6d9ce28b8266028bd47863d6a2127753c2fac215`.
The source-to-target prefix contains 24 unique flowlines and excludes 13
features returned after target COMID `18421703`.

Linear referencing against the operational boundary and Stonewall gauge gives:

| Measure | Value |
|---|---:|
| Full NLDI geometry | 25,351.899 m |
| Source-to-target effective path | 25,144.550 m |
| Source snap | 16.743 m |
| Target snap | 54.384 m |
| Maximum connection gap | 0 m |
| Difference from prior physics path | 28.210 m |

The path is a suffix of both prior physics paths, both snaps pass their frozen
tolerances, and the length difference is below 250 m. Stage 33 therefore
admits the directed spatial path.

## Temporal reconciliation result

The Stage 32 event-local empirical union is retained as `{5,6,7}` hours only
for compatibility diagnosis. It is not relabelled common support.

Three independently compiled same-path physics candidates are:

| Quantity | Support interval | Central time | Gap from empirical union |
|---|---:|---:|---:|
| Gravity-wave time | 1.164-1.243 h | 1.202 h | 3.757 h |
| Manning kinematic centroid time | 15.583-16.802 h | 16.145 h | 8.583 h |
| NWM advective residence time | 18.330-24.171 h | 22.908 h | 11.330 h |

None overlaps `{5,6,7}`. In addition, the Stage 32 all-event common support is
empty and none of these quantities is admitted as observed response lag.

## Decision

Admit `PublicTemporalPathBinding` for the Center Hill operational tailwater to
Stonewall directed NLDI path.

Admit the three continuous time supports as typed, state-dependent physics
candidates with preserved provenance. Do not admit them as downstream response
lag.

Reject empirical-physics temporal consistency and reject runtime transition
promotion. Preserve the numerical discrepancies as evidence; do not tune the
path, thresholds, or physical intervals toward the observed `{5,6,7}` union.

## Kernel versus traditional GIS implementation

Traditional GIS software can perform the component geometry work: network
navigation, point-to-line snapping, path extraction, line length, and joins to
reach attributes. Hydrologic and time-series software can calculate wave
celerity, Manning travel-time summaries, advective residence time, lagged
correlations, interval overlap, and distance between intervals.

The Geospatial Kernel operator uses those same numerical primitives, but its
output contract is different:

- operands carry spatial role, direction, path identity, physical quantity,
  temporal support, and provenance;
- empirical response lag cannot be substituted for hydraulic travel time just
  because both use hours;
- a path admission survives a temporal rejection instead of collapsing into
  one undifferentiated pass/fail result;
- cross-event transfer is checked separately from event-local compatibility;
- outcome-derived, state-derived, and outcome-calibrated evidence remain
  distinguishable; and
- runtime consumers receive a typed refusal unless every required promotion
  condition is satisfied.

The Kernel is therefore not a replacement implementation of `shortest_path`,
`snap`, or `correlate`. Its core is the executable law that controls which
geographic facts and physical meanings may become world-model state and
transition semantics.

## Consequences

### Positive

- A real, independently acquired directed spatial relation is now admitted.
- Physical and empirical time supports share a typed comparison surface without
  losing their different meanings.
- A negative temporal result no longer implies that the Geospatial Kernel or
  its geographic core has failed.
- The discrepancy is quantitative and reproducible rather than interpretive.
- Runtime propagation remains protected from an unsupported lag substitution.

### Negative

- Stage 33 does not provide a deployable Center Hill-to-Stonewall delay law.
- The empirical union cannot be treated as transferable support.
- The available physical candidates describe materially different time scales.
- Another downstream holdout cannot be manufactured from the exhausted frozen
  candidate pool.

### Follow-up

The next kernel stage should explain the observation operator rather than tune
one of these times. It should distinguish release actuation timing, local wave
arrival, hydrograph-shape response, gauge observation support, and routed mass
residence on the admitted path. Any new response claim requires a new public
time range or a different public system and a protocol frozen before outcomes.

## Evidence

All 33 Stage 33 gates pass. Gate success certifies:

- all 15 Stage 32 controlled artifacts retain their frozen hashes;
- the operator and outcome-free one-request acquisition order is intact;
- the public path, snaps, continuity, suffix identity, and length equivalence
  reproduce;
- Stage 32 local sets and common-support refusal are unchanged;
- the three typed physics intervals and minimum separations reproduce; and
- spatial access succeeds while physical-consistency and runtime-transition
  access fail closed.

The reconciliation ledger SHA-256 is
`7e69e9dc4eaa027ae23503cf6fb121035030f953260a989df29c9515fcf9b7df`.
The gate report status is
`spatial_path_admitted_temporal_reconciliation_rejected`. Passing the gates
does not admit temporal consistency or a runtime transition.

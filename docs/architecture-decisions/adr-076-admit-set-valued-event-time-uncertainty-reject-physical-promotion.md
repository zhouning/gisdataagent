# ADR-076: Admit set-valued event-time uncertainty, reject physical promotion

## Status

Accepted

## Context

ADR-075 admitted one-hour interval-end label shifts for empirical association,
while rejecting the substitution of those labels for physical event or process
time. The available source and target observations still leave event time
uncertain within their published supports:

- the CWMS release value is an end-labelled one-hour interval average; and
- the USGS target value is an end-labelled mean of two instantaneous samples
  at `t-30m` and `t`.

Stage 33 compared the discrete empirical union `{5,6,7}h` directly with three
same-path physics intervals and found no overlap. That point-set comparison did
not answer whether the observation supports themselves were wide enough to
explain the separation.

Stage 35 propagates only this already documented support uncertainty. It does
not request new values, move an observation, tune a hydraulic parameter, or
reinterpret the Stage 34 process semantics.

## Decision drivers

- Preserve every Stage 32 event, including the fourth event with empty lag
  support.
- Represent uncertainty as sets of closed intervals rather than a scalar lag.
- Keep disconnected lag components disconnected unless support dilation makes
  them touch or overlap.
- Use a conservative closure of the open-left observation supports.
- Freeze the operator, Stage 34 ledger, Stage 34 gates, event identities, lag
  sets, and formulas before compiling Stage 35 evidence.
- Do not acquire public or private data and do not calibrate after Stage 34.
- Do not allow numerical overlap to override carrier, source-marker, or target
  functional mismatches.

## Considered options

### Option 1: Retain point-valued lag comparison

This is simple and preserves the Stage 33 calculation, but it ignores known
within-hour event-time uncertainty. It would overstate temporal precision.

### Option 2: Replace all lags with one broad fitted interval

This could make comparison convenient, but it would erase disconnected support
components and could fill an event whose empirical support is empty. It would
also invite posthoc selection of interval width.

### Option 3: Propagate each discrete support set through fixed observation
supports

This preserves event identity, empty sets, and interval components. It can
quantify the maximum support-compatible separation without claiming that the
result is an observed or physical delay.

### Option 4: Admit physical response time whenever intervals overlap

This confuses a necessary numerical condition with semantic equivalence. A
gravity-wave arrival, discharge-response centroid, material residence time,
and empirical association peak remain different quantities even if their
numerical intervals happen to intersect.

## Decision

Adopt Option 3.

For end-labelled source and target supports, define event offsets as:

```text
source offset = [-source_duration, 0]
target offset = [-target_duration, 0]
```

For a nonnegative integer label shift `L`, use the conservative relative-delay
outer bound:

```text
lower = max(0, L - target_duration)
upper = L + source_duration
```

With one-hour supports, `L -> [L-1,L+1]`. Dilation is applied to each discrete
lag first; only touching or overlapping closed intervals are merged. Empty
support remains empty.

The resulting uncertainty envelope is admitted only for support-aware temporal
reasoning. It is not admitted as physical event delay, physical response time,
hydraulic edge time, or runtime transition.

## Frozen protocol and evidence boundary

The Stage 35 operator SHA-256 is
`660d596341eea9a54c96332834e58d1418953cc4838589ac4826aba35ce4600d`.
The no-network protocol SHA-256 is
`e3a226937ffb0a15298d2f55d02c8e465fd71a2e6bd1453f9c3c3f7be1963f25`.

The protocol binds the Stage 34 semantic ledger and gate report and freezes all
four Stage 32 event identities and selection ranks. It explicitly forbids:

- network requests;
- new public data;
- private or workspace data;
- release or downstream outcome acquisition; and
- post-Stage 34 calibration.

The gate compiler additionally verifies that all 13 controlled Stage 34
artifacts retain their frozen hashes.

## Results

The event-local lag sets propagate as follows:

| Event rank | Label-shift support | Relative-delay envelope |
|---:|---:|---:|
| 1 | `{5,6,7}` | `[4,8]h` |
| 2 | `{6,7}` | `[5,8]h` |
| 3 | `{7}` | `[6,8]h` |
| 4 | empty | empty |

The maximum empirical union becomes `[4,8]h`. The fourth event remains empty,
so the all-event uncertainty intersection is empty.

Comparison with the three same-path physics intervals gives:

| Quantity | Physics interval | Minimum post-dilation separation |
|---|---:|---:|
| gravity-wave arrival | `[1.164,1.243]h` | `2.756515h` |
| Manning response centroid | `[15.583,16.802]h` | `7.582960h` |
| NWM advective residence | `[18.330,24.171]h` | `10.329537h` |

No numerical overlap is created. More importantly, all Stage 34 semantic
refusals remain in force even under a hypothetical overlap.

## Kernel versus traditional GIS implementation

A conventional GIS or time-series workflow can buffer timestamp uncertainty,
expand lag values, union intervals, and compute interval intersections. Those
component operations are sufficient for the arithmetic.

The Geospatial Kernel adds executable rules above them:

- support dilation is typed separately from physical propagation;
- discrete lag topology is preserved before interval merging;
- empty evidence cannot become nonempty through uncertainty handling;
- spatial-path identity and numerical overlap remain separate from process
  semantics; and
- admitted diagnostic consumers are distinct from physical and runtime
  consumers.

The architectural value is therefore not a novel interval algorithm. It is a
fail-closed type and evidence boundary for how interval results may enter a
world model.

## Consequences

### Positive

- Stage 33 no longer relies on an unrealistically precise point comparison.
- Observation-support uncertainty is reproducible, set-valued, and auditable.
- The negative physical result survives the maximum frozen uncertainty bound.
- Empty and disconnected empirical supports cannot be silently filled.
- No new data or posthoc parameter choice was required.

### Negative

- Conservative closure can retain boundary points that the original open-left
  supports do not literally observe.
- The outer bounds do not identify the actual release actuation time.
- An empty fourth event still blocks any all-event common delay.
- The current evidence cannot promote any candidate to runtime use.

### Risks and mitigations

- A wider ad hoc uncertainty band could manufacture overlap. Mitigation: the
  durations and formulas are protocol-frozen and hash-bound to Stage 34.
- Future users could interpret an outer envelope as a probability interval.
  Mitigation: the contract exposes no probability mass and physical-delay
  access fails closed.
- Numerical overlap in later data could be overclaimed. Mitigation: semantic
  equivalence remains an independent mandatory gate.

## Follow-up

The next meaningful evidence is not a wider interval. It is independently
sourced subhourly operational timing or a controlled boundary perturbation
with a separately defined physical response functional. Any follow-up must
freeze event selection, timestamp semantics, physical quantity, and admission
rule before acquiring outcomes.

## Evidence

All 35 Stage 35 gates pass with status
`event_time_uncertainty_propagated_physical_response_rejected`.

- uncertainty ledger SHA-256:
  `2d66862d4b746885d24fb8e52eff4d80c88a93cd1357e9e774077942a6daf3e2`;
- gate report SHA-256:
  `8a20e41c14ca5015452eb3b8c83ba39c942f5c6d019ec106a8ce791b26b7e1ad`.

## Related decisions

- ADR-073 admits event-local discrete empirical lag support and rejects common
  support.
- ADR-074 admits the independently acquired spatial path and rejects temporal
  reconciliation.
- ADR-075 admits interval-end label shifts and rejects process-time
  substitution.

# ADR-078: Attribute hydraulic-boundary falsification, reject posthoc rescue

## Status

Accepted

## Context

ADR-077 froze four source-only tailwater-elevation events and a downstream
persistent-departure functional before requesting USGS outcomes. Stage 36
returned a strict negative result. One 2023 event lacked the frozen half-hour
baseline support, while none of the three assessable events crossed its frozen
robust threshold.

That result must be retained, but it leaves two different failure mechanisms:
measurement support can make the functional unassessable, and a fully observed
event can remain below the frozen gate. Before defining another experiment, the
Kernel needs an executable attribution that distinguishes those mechanisms
without creating a replacement detector from observed outcomes.

## Decision drivers

- Recompute Stage 36 evidence and verify its exact ledger and gate hashes.
- Preserve the original 97-position half-hour grid and all missing values.
- Reuse the frozen baseline, threshold formula, search support, and
  three-sample persistence requirement.
- Quantify margin to the frozen gate without proposing a lower threshold.
- Separate amplitude failure from persistence-only failure.
- Compare observed direction only as a diagnostic, not a causal relation.
- Reject alternative-detector, causal, physical-time, and runtime promotion.
- Perform no network request and consume no new data.

## Diagnostic operator

`PersistentDepartureFalsificationAttribution` first invokes the unchanged
Stage 36 `FirstPersistentDownstreamDeparture` operator. On the same `+0.5h`
through `+12h` search support it then finds:

- the dominant component of the frozen threshold;
- the maximum single-sample absolute departure;
- the strongest complete, same-direction three-sample run;
- that run's start offset, direction, magnitude, threshold ratio, and
  shortfall; and
- whether a single sample crossed the threshold but persistence alone caused
  rejection.

These are post-outcome diagnostics. They do not define an admissible detector,
lag, causal response, physical response time, or runtime transition.

## Results

The 2023 event remains an observation-support failure: its hourly response
provides 48 of 97 half-hour grid positions and only 18 of the required 30
baseline samples. It receives no reconstructed values and no threshold-margin
attribution.

For the three assessable events, the robust-MAD component dominates the frozen
threshold. Their strongest same-direction runs are:

| Event rank | Start offset | Direction | Persistent/threshold | Single/threshold | Shortfall |
|---:|---:|---|---:|---:|---:|
| 2 | `210m` | decrease | `0.142883` | `0.151288` | `231.017103m3/s` |
| 3 | `180m` | decrease | `0.722669` | `0.739875` | `68.461300m3/s` |
| 4 | `240m` | decrease | `0.188826` | `0.191352` | `354.718387m3/s` |

No single sample crosses the frozen threshold, so persistence is not the
decisive failure in any event. All selected source perturbations are rises,
while every strongest downstream run is a decrease. Directional concordance is
therefore `0/3`, but this does not establish an inverse causal effect: the
source remains an observed local boundary state that may include backwater.

## Considered options

### Option 1: Lower the MAD multiplier until Stage 36 detects departures

This fits a target gate after viewing the outcomes and invalidates the blind
result.

### Option 2: Drop the hourly 2023 event and claim three complete tests

The observation frequency is part of the public evidence. Removing the failed
support case would conceal a real deployment constraint.

### Option 3: Treat the three downstream decreases as inverse causal responses

Direction alone cannot distinguish reservoir operation, downstream state,
backwater, common forcing, or unrelated variability. The source is not an
identified action or discharge flux.

### Option 4: Admit only frozen-gate failure attribution

This preserves Stage 36, explains why it failed, and narrows the next source
requirement without manufacturing a positive transition rule.

## Decision

Adopt Option 4.

Admit Stage 37 only as post-outcome falsification attribution. Classify one
event as observation-support insufficient and three as below the frozen
persistent-departure gate. Reject the claim that persistence alone caused the
failures. Reject directional-response, alternative-detector, causal,
physical-time, and runtime admission.

Do not continue the tailwater-elevation marker as a candidate action or flux
source. A later blind experiment must first bind a directionally meaningful
action or discharge-flux identity independently of the downstream outcome.

## Kernel versus traditional GIS implementation

A conventional time-series script can calculate maximum deviations and ratios.
The Geospatial Kernel responsibility is the executable claim boundary: Stage
37 cannot change Stage 36 eligibility, fill an unsupported grid, redefine a
threshold, or convert diagnostic direction into a causal edge. Hash-bound
reproduction and typed refusal methods make those restrictions enforceable.

## Consequences

### Positive

- The negative result is split into measurement and threshold failure without
  discarding either.
- The robust-MAD term, not the three-sample requirement, is identified as the
  active numerical boundary for all assessable events.
- The absence of direction concordance is retained without causal promotion.
- No new data, external request, or parameter choice is introduced.

### Negative

- Stage 37 admits no response model or predictive increment.
- The closest event reaches only `0.722669` of its frozen persistent threshold.
- A directionally meaningful public action/flux source remains unresolved.
- The Center Hill result does not establish transfer to another project.

## Evidence

The Stage 37 attribution ledger SHA-256 is
`2bad541ec95387ca57bdf63a916b72c95a50db346befa96de77f56f0d1a7a989`.
All 31 gates pass with status
`stage36_falsification_attributed_no_alternative_admitted`. The gate report
SHA-256 is
`f1326a8b2ae2e766b71556697849fe5ea84daa4b706337be1b2f08c0aa81e71d`.
Thirteen focused Stage 37 operator and public-evidence tests pass.

## Related decisions

- ADR-073 preserves event-local empirical support and a failed blind event.
- ADR-075 separates observation labels from physical process time.
- ADR-076 rejects physical promotion after uncertainty propagation.
- ADR-077 freezes the hydraulic-boundary experiment and its negative result.

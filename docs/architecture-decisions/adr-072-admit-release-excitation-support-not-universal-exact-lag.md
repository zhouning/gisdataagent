# ADR-072: Admit release excitation support, not a universal exact lag

## Status

Accepted

## Context

ADR-071 rejected a single antecedent-flow threshold as the explanation for
Center Hill's observed `5-6h` empirical response variation. Its strongest
counterexample was a high-flow increase event selected from a `205.750 m3/s`
one-hour step. Release-only inspection showed that the step merely restored
flow after a one-hour drop. The downstream best correlation was only
`0.481394`.

The failure exposed a missing Geospatial Kernel responsibility. Before learning
or testing a propagation relation, the Kernel needs to decide whether the
source time series supplies a transport-resolvable excitation. A large adjacent
step is not sufficient. Short anomalies may be attenuated, a nearly constant
window cannot distinguish delays, and highly collinear lag columns cannot
support an exact-hour claim.

Stage 31 therefore separates three propositions:

1. release input has enough support for a blind response experiment;
2. a downstream response is empirically detectable; and
3. the response peak resolves one exact hour.

None of these propositions alone identifies physical travel time.

## Decision drivers

- Event eligibility must use release values only.
- Operator code and numerical thresholds must be hash frozen before Stage 31
  release acquisition.
- The operator must reject Stage 30's one-hour rebound without using its
  downstream outcome during Stage 31 selection.
- Excitation duration and volume must be distinct from lag-column geometry.
- New validation events must cover high/low antecedent flow and
  increase/decrease directions.
- Stage 28 through Stage 30 event neighborhoods must be excluded.
- All lag candidates must use equal real pair counts.
- Response detectability and exact-hour resolution must have separate gates.
- Exact empirical lag must not be relabelled physical propagation time.
- Smith Fork values must retain the Stage 30 graph-state support contract.

## Release-only operator

`ReleaseExcitationIdentifiability` consumes exactly 73 inclusive hourly release
values: 24 before the selected step, the step hour, and 48 after. It compiles:

- a reference release as the median from offsets `-24` through `-7h`;
- onset versus recovery according to which side of the selected step is farther
  from that reference;
- excitation sign independently of the selected step sign;
- consecutive excursion support, capped at 12 hours, above 25% of the primary
  step magnitude;
- excitation volume normalized by the primary step, in step-hours;
- standard deviation of the 72-hour diagnostic release series;
- maximum absolute release autocorrelation over lags 1 through 12; and
- condition number of the standardized 13-column lag design.

The frozen input gate requires:

| Measure | Requirement |
|---|---:|
| Excursion support | at least 3 h |
| Normalized excitation volume | at least 3 step-hours |
| Release standard deviation | at least 30 m3/s |
| Maximum absolute lag autocorrelation | at most 0.97 |
| Lag-design condition number | at most 50 |

The operator file SHA-256 is
`6dd4266e60c569bb19f7b79387d2d6cf9da06ee81c68d886e74cc0d6564226eb`.
It is embedded in the frozen selection plan. Any later code change invalidates
the acquisition protocol.

On the seven consumed Stage 29 and Stage 30 events, the operator rejects the
one-hour rebound with `1.0234` normalized step-hours and admits the other six.
One admitted Stage 29 event has best correlation `0.799624`, just below the new
`0.8` response threshold; the development result was retained rather than
rounded upward.

## Frozen blind protocol

The Stage 31 selection plan was frozen before CWMS values with SHA-256
`0ebb39f688776b64458283d1b39ad67312381bbf9acf8bdd7f9ee864f37e53f7`.
It fixed:

- the operator artifact and thresholds above;
- minimum step `50 m3/s` and event range `100 m3/s`;
- four strata: high/increase, high/decrease, low/increase, low/decrease;
- 90-day exclusion around all Stage 28 through Stage 30 windows;
- 180-day separation among selected events; and
- deterministic ranking by excursion duration, normalized volume, lag-design
  condition, primary-step magnitude, and time.

Response is detectable only when best correlation is at least `0.8`, the best
lag is not the 0- or 12-hour search boundary, and at least 60 real pairs exist.
Exact-hour resolution additionally requires a best-minus-second-best
correlation margin of at least `0.02`.

The event manifest SHA-256 is
`d03f6a8de7511c77105ba1a051f7b57292c43c48d7081256aecdf9db13b1bf3d`.
The observation plan SHA-256 is
`34169db80643a05a51c8579811c7c99320ba594734871c63cc70fc8ac8464e35`.

## Public-data acquisition

No private or user-supplied data was used. One CWMS request downloaded
`1,244,077` bytes and reproduced `43,825` hourly values. After frozen exclusions
and the release-support gate, `1,812` candidates remained.

Only after operator, events, and observation URLs were hash frozen did eight
USGS requests download `1,137,147` bytes of Stonewall and Smith Fork values.
All nine source objects retain SHA-256 identity and TLS hostname verification.

The selected inputs are:

| Stratum | Step time | Mode | Support | Volume | Condition |
|---|---|---|---:|---:|---:|
| high/increase | 2025-06-06 16:00Z | recovery | 12 h | 23.543 | 22.267 |
| high/decrease | 2021-03-22 12:00Z | onset | 12 h | 36.516 | 28.929 |
| low/increase | 2022-06-13 13:00Z | onset | 12 h | 26.731 | 12.312 |
| low/decrease | 2024-02-03 13:00Z | onset | 12 h | 17.423 | 5.768 |

Here volume is normalized excitation volume in step-hours and condition is the
lag-design condition number.

## Blind results

| Stratum | Best lag | Best r | Second lag | Peak margin | Detectable | Exact hour |
|---|---:|---:|---:|---:|---|---|
| high/increase | 6 h | 0.941048 | 5 h | 0.016312 | yes | no |
| high/decrease | 6 h | 0.936895 | 5 h | 0.017948 | yes | no |
| low/increase | 6 h | 0.919997 | 5 h | 0.023221 | yes | yes |
| low/decrease | 6 h | 0.831027 | 5 h | 0.010555 | yes | no |

All four release-supported blind events produce a detectable downstream
response, and every best lag is 6 hours. This validates the input support gate
for its declared purpose.

Only one event separates 6 hours from its second-best 5-hour result by the
frozen `0.02` margin. Universal exact-hour admission therefore fails. The
result supports a narrow empirical response neighborhood, not a point-valued
physical travel time.

## Graph observations

Stage 31 reuses the admitted Stage 30 value-level graph contract. Smith Fork
observations remain states at station `USGS-03424730`, COMID `18421273`, with
two native half-hour samples per compiled hour.

The four windows retain `84`, `81`, `84`, and `84` complete approved hours.
Three missing hours remain absent. Graph observations are not tributary-mouth
fluxes and cannot close the reach-wide conservation ledger.

## Considered options

### Option 1: Keep ranking events by the largest adjacent step

This repeats the Stage 30 failure mode because a large recovery after a short
anomaly may provide little transported volume.

### Option 2: Select events by downstream correlation

This guarantees favorable outcomes and invalidates the blind experiment.

### Option 3: Treat all four best 6-hour results as exact identification

Three events have a best-versus-second peak margin below the frozen resolution
threshold. A shared argmax is not equivalent to a resolved point estimate.

### Option 4: Admit the input support gate and retain interval uncertainty

This keeps the positive blind response result while preserving the unresolved
5-versus-6-hour distinction and physical-time boundary.

## Decision

Adopt Option 4.

Admit `ReleaseExcitationIdentifiability` as a Geospatial Kernel experimental
support operator. It may decide whether a release event enters a blind
transport-response experiment. It is not a response model, lag estimator,
hydraulic routing operator, or physical travel-time operator.

Admit that all four Stage 31 events have detectable empirical response. Do not
admit a universal exact-hour lag, physical travel time, or runtime propagation
operator. Continue to admit Smith Fork only as a support-aware graph node
state.

## Consequences

### Positive

- The Kernel now rejects large but transport-poor one-hour rebound events.
- Experimental eligibility is causal, reproducible, and independent of target
  observations.
- Four new public events validate the operator across direction and flow state.
- Detectable response and exact-hour resolution are no longer conflated.
- The input operator, evidence compiler, and typed refusals are executable.

### Negative

- The numerical thresholds are supported by a small single-project history.
- Exact-hour lag remains unresolved in three of four events.
- The operator does not model channel storage, lateral inflow, or gauge
  response.
- It is not yet validated outside Center Hill and Stonewall.

### Risks and mitigations

- Ranking by maximum 12-hour support may favor long operational episodes.
  Mitigation: preserve all five input diagnostics and validate on other dams
  before generalizing thresholds.
- The operator name may be mistaken for proof of lag identifiability.
  Mitigation: its admitted method is explicitly blind-response-test support;
  exact lag and physical time have separate refusing methods.
- A 6-hour argmax may be promoted despite a broad peak. Mitigation: retain the
  second-best lag and peak margin on every event.
- Graph observations may be consumed as fluxes. Mitigation: reuse Stage 30's
  typed graph-state consumer boundary and no-fill semantics.

## Meaning for the Geospatial Kernel

Traditional GIS and time-series software supplies the component calculations:
median, standard deviation, autocorrelation, matrix condition number, temporal
windowing, station-to-COMID binding, and lagged correlation.

The Kernel contribution is the lawful order and typed meaning of those
calculations. It determines whether a geographically located action has enough
temporal support to teach a propagation relation, freezes that decision before
the target is observed, and prevents input sufficiency from becoming a claim
about response, exact delay, or physical time. This is an epistemic operator
inside the world-model framework: it governs which evidence may update the
model and what that update is allowed to mean.

The next Kernel step should represent empirical delay as a support set rather
than a scalar. A frozen `EmpiricalLagSupport` can retain every lag whose
correlation is both above the response threshold and within a predeclared
margin of the best value. That support can be attached to the Center
Hill-to-Stonewall graph relation with explicit temporal and provenance bounds.
It must remain separate from a hydraulic travel-time distribution until
geometry, lateral inputs, and independent spatial observations support that
promotion.

## Evidence

All 29 Stage 31 gates pass:

- all 13 Stage 30 artifacts and the Stage 31 operator retain frozen hashes;
- one CWMS and eight USGS requests are public, bounded, and TLS verified;
- operator, events, and observation URLs preserve the two-phase order;
- all four events pass the frozen input support gate and have equal real lag
  pairs;
- all four responses exceed the predeclared detectability threshold at 6 h;
- only one exact-hour result is admitted and universal exact-hour is refused;
- Smith Fork graph support, approval, and missing hours remain executable; and
- physical time, mouth flux, universal exact lag, and runtime promotion fail
  closed.

## Artifacts

- Release support operator:
  `data_agent/uwm/geospatial_kernel_v2/release_excitation_identifiability.py`
- Acquisition:
  `scripts/acquire_geotransport_stage31_identifiable_response_events.py`
- Evidence ledger:
  `data_agent/uwm/geospatial_kernel_v2/public_identifiable_response_evidence.py`
- Gate report:
  `benchmarks/geotransport_v0_1/stage31_identifiable_response_gates.json`
- Data directory:
  `data/geotransport_v0_1/stage31_center_hill_identifiable_response_events/`

## Related decisions

- ADR-071: Reject the single-threshold lag rule and admit graph state
- ADR-070: Release-selected blind transfer and observed tributary state
- ADR-023: Geospatial Kernel branching network and tributary boundary

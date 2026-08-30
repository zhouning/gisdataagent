# ADR-071: Reject the single-threshold lag rule and admit a graph-state contract

## Status

Accepted

## Context

ADR-070 admitted three release-selected blind events. Their best empirical
release-response lags were 5, 6, and 6 hours. The only 5-hour event had a
24-hour antecedent release mean of `308.571 m3/s`; the two 6-hour events had
antecedent means of `56.813` and `131.371 m3/s`. This suggested a small,
testable development hypothesis: high antecedent release predicts 5 hours and
low antecedent release predicts 6 hours.

That pattern was based on only three development events. It could not be
promoted by inspection. Stage 30 therefore had to freeze a simple rule, select
new events from release values alone, and retain any counterexample.

ADR-070 also admitted Smith Fork as an observed tributary state, but did not
yet define the value-level graph contract that a Kernel consumer may use. A
station observation needs explicit geographic and temporal support before it
can participate in state analysis.

## Decision drivers

- The rule must be derived only from Stage 29 development evidence.
- The threshold and predicted lags must be frozen before Stage 30 outcomes.
- Validation must cover release increase and decrease in both flow regimes.
- Step magnitude must remain explicit even when it is not a rule input.
- Stage 28 and Stage 29 event neighborhoods must be excluded.
- Selected validation events must be mutually separated.
- Every lag must use equal real pair counts.
- A failed stratum must reject the complete rule without threshold tuning.
- Smith Fork values must be typed as observations at COMID `18421273`.
- A node state must not be silently promoted to a tributary-mouth flux,
  reach-wide lateral input, or conservation oracle.

## Frozen protocol

The selection plan was hash frozen before the five-year CWMS values were
requested. It fixed:

- a 24-hour antecedent mean using real release hours strictly before the step;
- high flow as antecedent mean greater than or equal to `200 m3/s`;
- predicted lag `5 h` for high flow and `6 h` for low flow;
- four validation strata in fixed order: high/increase, high/decrease,
  low/increase, and low/decrease;
- large steps as at least `150 m3/s`, otherwise moderate from `50 m3/s`;
- minimum release step `50 m3/s` and event range `100 m3/s`;
- a 90-day exclusion radius around Stage 29 events and the Stage 28 window;
- 180-day separation among Stage 30 events;
- release-only ranking within each stratum; and
- no retuning after observation acquisition.

The rule-support criteria were also fixed. An event passes only when its best
lag is within one hour of the prediction, correlation at the predicted lag is
at least `0.8`, the best-minus-predicted correlation is at most `0.05`, and at
least 60 real pairs exist. Admission requires all four strata to pass.

The selection plan SHA-256 is
`dfea2f8c9abf9ba0044dd8c55027087d00e7c3221fbd9696fa44524015c38175`.
The release-only event manifest SHA-256 is
`63ab64c6e6cbb9d4372d58e28d52d005a499b31ff6d5526a1aa9b7a7429364b6`.
The observation plan SHA-256 is
`51dfcb8ae9daa797fd4fead0629bfb9651fbcb4cd3bfecfea85ce6a8e9c32a6a`.

## Public-data acquisition

No user or private data was used. One CWMS request downloaded `1,244,077`
bytes and reproduced all `43,825` hourly values for 2021 through 2025. After
the frozen exclusions, `4,873` release steps were eligible.

Only after the event manifest and observation plan existed did eight USGS
requests download `1,132,504` bytes of Stonewall and Smith Fork observations.
Every source object is hash verified and retained TLS hostname verification.

The selected events are:

| Stratum | Step time | Antecedent mean | Direction | Magnitude | Predicted lag |
|---|---|---:|---|---|---:|
| high/increase | 2021-09-25 19:00Z | 231.946 m3/s | increase | large | 5 h |
| high/decrease | 2025-12-15 17:00Z | 340.134 m3/s | decrease | moderate | 5 h |
| low/increase | 2024-08-21 20:00Z | 65.116 m3/s | increase | large | 6 h |
| low/decrease | 2023-06-13 00:00Z | 59.928 m3/s | decrease | moderate | 6 h |

## Blind results

| Stratum | Best lag | Predicted-lag r | Fixed-6-hour r | Rule passes |
|---|---:|---:|---:|---|
| high/increase | 4 h | 0.425413 | 0.337321 | no |
| high/decrease | 6 h | 0.932414 | 0.949968 | yes |
| low/increase | 6 h | 0.899034 | 0.899034 | yes |
| low/decrease | 6 h | 0.854651 | 0.854651 | yes |

The high/increase stratum is a decisive counterexample. Its best lag is within
one hour of the prediction, but correlation at 5 hours is below `0.8` and the
best-minus-predicted loss exceeds `0.05`. The high/decrease event passes the
tolerance at 5 hours but actually prefers 6 hours. Antecedent flow alone is
therefore insufficient to explain the observed response-lag variation.

This rejects the frozen two-state threshold rule. It does not reject the
existence of geographically structured dynamics, the Geospatial Kernel, or
the broader Geospatial World Model. It narrows what the Kernel may claim.

## Graph-state contract

Each complete Smith Fork hour is compiled as `ObservedGraphState` with:

- station `USGS-03424730`;
- COMID `18421273`;
- variable `discharge` and unit `m3/s`;
- an open-closed hourly support interval;
- the two native half-hour sample times;
- both source approval states; and
- a source artifact identifier.

The four windows contain `84`, `80`, `82`, and `84` complete graph-state
hours. All compiled hours are `Approved`. The missing `0`, `4`, `2`, and `0`
hours remain absent and are never filled.

The admitted consumers are support-aware graph-state analysis and diagnostics.
Typed methods reject conversion to tributary-mouth flux or a conservation
oracle. The containing series separately rejects interpretation as total
lateral inflow.

## Considered options

### Option 1: Move the threshold until all four events pass

This uses validation outcomes to fit the rule and destroys the blind test.

### Option 2: Admit the rule because three of four strata pass

This violates the predeclared all-strata requirement and hides the one event
that most strongly tests the proposed high-flow explanation.

### Option 3: Reject the rule and discard Smith Fork

The transfer hypothesis and graph observation contract answer different
questions. A failed lag rule does not invalidate a correctly supported node
observation.

### Option 4: Reject the rule and admit only the typed graph state

This preserves the negative transfer result while advancing the spatial-state
foundation under explicit consumption boundaries.

## Decision

Adopt Option 4.

Reject the single-threshold regime-conditioned empirical lag. Do not admit it
as physical travel time or as a runtime transition operator. Admit the
support-aware Smith Fork graph-state contract at COMID `18421273`, with all
mouth-flux, lateral-total, and conservation-oracle promotions closed.

## Consequences

### Positive

- A plausible but underspecified regime explanation has been falsified using
  untouched public events.
- Release direction and magnitude remain visible instead of being averaged
  out of the evidence ledger.
- The graph now has value-level observed states with geographic and temporal
  support.
- Missing values and permitted consumers are executable rather than prose
  conventions.
- No user-supplied data is required to reproduce the evidence.

### Negative

- No stable conditional lag is admitted.
- One high-flow event has weak correlation under every nearby lag.
- The graph observation still cannot supply a tributary-mouth boundary.
- No runtime rollout or closed mass balance follows from this stage.

### Risks and mitigations

- The threshold may be rejected because some release windows are not
  identifiable as single-delay events. Mitigation: the next protocol must
  define release-only excitation and isolation diagnostics before outcomes.
- The 5-6-hour correlations may conflate operational averaging and channel
  response. Mitigation: retain the empirical-response label and refuse physical
  travel-time conversion.
- Graph-state consumers may ignore missing supports. Mitigation: values exist
  only for complete two-sample hours and no-fill counts are gated.
- COMID binding may be mistaken for a mouth observation. Mitigation: spatial
  role and forbidden consumers are present on every typed value.

## Meaning for the Geospatial Kernel

Traditional GIS and time-series software can perform the component
calculations: classify values, create time windows, resample observations,
trace an NHDPlus path, join a station to a COMID, and calculate correlations.
Those numerical operators remain ordinary GIS/statistical implementations.

The Geospatial Kernel adds the model semantics that ordinary operator output
does not guarantee: which time was available at selection, what spatial object
a value describes, which support interval it represents, whether missing
evidence may be filled, and which transition equations may consume it. Stage
30 demonstrates this distinction directly. The correlation operator rejects a
rule, while the graph-support operator admits a node state; neither result is
allowed to change the other's claim boundary.

The Kernel's next scientific target is not a more convenient lag threshold. It
is a release-only identifiability operator. Before acquiring outcomes, that
operator should quantify whether a window contains an isolated excitation,
how many reversals and competing steps occur, plateau duration, autocorrelation,
and whether a single-delay response is mathematically distinguishable. Only
events that pass a frozen identifiability contract should enter another blind
transfer experiment. Direction, antecedent state, and magnitude should remain
covariates rather than be promoted prematurely to transition laws.

## Evidence

All 27 Stage 30 gates pass:

- all 13 Stage 29 protocol and evidence artifacts retain frozen hashes;
- one release request and eight observation requests are public, bounded,
  hash verified, and TLS verified;
- rule, event, and observation plans preserve the two-phase causal order;
- four strata, 180-day separation, 72 release hours, and 13 equal-pair lags
  are reproducible;
- the three supports and high/increase rejection are retained together;
- graph binding, complete-hour counts, approval, and gaps are executable; and
- rule, physical time, mouth flux, lateral total, conservation oracle, and
  runtime promotions fail closed.

## Artifacts

- Acquisition:
  `scripts/acquire_geotransport_stage30_regime_validation_events.py`
- Kernel ledger:
  `data_agent/uwm/geospatial_kernel_v2/public_regime_transfer_evidence.py`
- Tests:
  `data_agent/test_acquire_geotransport_stage30_regime_validation_events.py`
  and
  `data_agent/test_geospatial_kernel_public_regime_transfer_evidence.py`
- Evidence ledger:
  `data/geotransport_v0_1/stage30_center_hill_regime_validation_events/regime_transfer_evidence_ledger.json`
- Gate report:
  `benchmarks/geotransport_v0_1/stage30_regime_validation_gates.json`

## Related decisions

- ADR-070: Release-selected blind transfer and observed tributary state
- ADR-069: Public operational-boundary lag diagnostic
- ADR-023: Geospatial Kernel branching network and tributary boundary

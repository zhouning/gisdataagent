# ADR-070: Admit release-selected blind transfer and one observed tributary state

## Status

Accepted

## Context

ADR-069 admitted two bounded Center Hill operational release windows and a
6-hour development correlation diagnostic. Its 2026 transfer event had constant
release, so lag was mathematically unidentifiable. The next requirement was to
find independent public events with sufficient release variation, without user
data and without selecting events from favorable downstream outcomes.

ADR-069 also left lateral inflow unresolved. Stage 27's closest Hickman Creek
sites did not have modern continuous discharge. Existing D4 work provided 19
NWM modeled tributary-mouth series, but those are modeled inputs rather than
observed ground truth. A public observation search identified Smith Fork at
Temperance Hall as the only continuous tributary discharge series already bound
to the frozen Center Hill subnetwork.

## Decision drivers

- Event eligibility and ranking must use CWMS release values only.
- Selected events and their blind-transfer roles must be hash frozen before
  Stonewall or Smith Fork event values are requested.
- Events must have a large one-hour release step, a large 72-hour range,
  complete release support, and temporal separation.
- All lag candidates must have equal potential pair counts.
- The Stage 28 6-hour lag must be evaluated as fixed prior knowledge rather than
  retuned on each event.
- Missing tributary observations must remain missing.
- An upstream tributary gauge may be an observed state anchor without being a
  tributary-mouth boundary flux.
- A single gauged branch cannot close the reach-wide lateral-inflow ledger.

## Predeclared protocol

The selection plan was frozen before five-year value acquisition. It specified:

- CWMS series `CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev`;
- candidate pool `2021-01-01T00:00:00Z` through
  `2026-01-01T00:00:00Z`;
- a 72-hour event with 24 hours before and 48 hours after the step;
- minimum absolute one-hour step `50 m3/s`;
- minimum event-window range `100 m3/s`;
- 180-day minimum separation between selected events;
- 90-day exclusion around the Stage 28 development window;
- descending absolute step, descending window range, and ascending time as the
  deterministic ranking; and
- exactly three selected events, all with role `blind_transfer`.

The transfer diagnostic retained lag candidates 0 through 12 hours and the
Stage 28 fixed lag of 6 hours. Observation queries extend 12 hours beyond each
release window, so every lag candidate has 72 potential real pairs.

An event supports the fixed lag only when:

- its best lag lies within 2 hours of 6;
- correlation at 6 hours is at least 0.8;
- best-lag correlation exceeds fixed-lag correlation by at most 0.05; and
- at least 60 real pairs exist.

Stable empirical lag admission requires all three blind events to pass.

## Two-phase isolation

The release phase exposes no continuous-observation request URL. It acquired
only:

- the five-year CWMS release candidate pool;
- Smith Fork site and time-series metadata; and
- Smith Fork NLDI site and downstream-path metadata.

This phase made five requests and downloaded `1,273,397` bytes. The complete,
unpaginated CWMS response contains `43,825` inclusive hourly values. It produced
`7,266` eligible candidates and froze three selected events in an event manifest
with SHA-256
`480734abcdb2a535e7a2bc794dbf2a5d7e708d3d6faac7becbdea9429d05c91b`.

Only after that hash existed did the observation plan generate six USGS value
requests: Stonewall and Smith Fork for each selected event. The observation
phase downloaded `826,840` bytes. No workspace or private data was sent.

## Selected events

| Rank | Step time | Direction | Absolute step | Window range |
|---:|---|---|---:|---:|
| 1 | 2022-12-23 19:00Z | increase | 342.690477 m3/s | 373.074454 m3/s |
| 2 | 2025-09-10 14:00Z | increase | 292.428075 m3/s | 417.333685 m3/s |
| 3 | 2025-03-03 16:00Z | decrease | 244.487653 m3/s | 360.869893 m3/s |

Each release window has 73 inclusive CWMS values. The first value summarizes
the hour preceding the window and is excluded, leaving 72 one-hour supports.
All selected release values have CWMS quality code `0`; that code is retained
without interpreting it as USGS `Approved`.

Stonewall has 169 approved half-hour samples in every 84-hour observation
window. The compiler forms each hourly observation only from the two real
samples at `t-30m` and `t`. Every lag from 0 through 12 hours therefore has 72
real release-outcome pairs.

## Blind-transfer results

| Event | Best lag | Best r | r at fixed 6 h | Fixed 6 h passes |
|---|---:|---:|---:|---|
| 2022-12-23 | 5 h | 0.799624 | 0.727040 | no |
| 2025-09-10 | 6 h | 0.831066 | 0.831066 | yes |
| 2025-03-03 | 6 h | 0.817760 | 0.817760 | yes |

The two 2025 blind events independently support Stage 28's 6-hour diagnostic.
The 2022 event is an informative counterexample: its best lag is 5 hours, and
the fixed-lag correlation misses both the absolute-correlation and correlation-
loss thresholds.

The evidence therefore narrows the observed response to a 5-6-hour empirical
range across these events, but it does not satisfy the predeclared unanimous
criterion for a stable 6-hour lag. It also does not identify a physical travel
time because release averaging, channel storage, lateral inflow, and gauge
response remain conflated.

## Observed tributary evidence

Official USGS metadata identifies `USGS-03424730` as Smith Fork at Temperance
Hall, a stream site with `214 mi2` drainage area and continuous discharge series
`c59c7559af4f4a0ebef64eb811803ea0`. NLDI binds it to COMID `18421273`; its
downstream path contains mainstem COMID `18421743` and Stonewall outlet COMID
`18421703`.

Smith Fork event observations are:

| Event | Raw half-hours | Complete hours | Coverage | Mean Q | Maximum Q |
|---|---:|---:|---:|---:|---:|
| 2022-12-23 | 141 | 61 | 0.7262 | 1.9836 m3/s | 2.2059 m3/s |
| 2025-09-10 | 169 | 84 | 1.0000 | 1.2922 m3/s | 1.9171 m3/s |
| 2025-03-03 | 163 | 79 | 0.9405 | 3.1226 m3/s | 3.7661 m3/s |

Every compiled Smith Fork hour is approved. The 23 and 5 incomplete hours stay
missing. These data admit an observed tributary state at the gauge. They do not
measure flow at the tributary mouth, do not account for travel from the gauge to
the confluence, and do not represent the other 18 modeled tributary mouths.

## Considered options

### Option 1: Select events by highest downstream correlation

This would maximize apparent transfer success but make the evaluation post hoc.
It would not test the Stage 28 lag independently.

### Option 2: Admit 6 hours because two of three events support it

The majority result is useful evidence, but it violates the predeclared
unanimous criterion and discards the 2022 counterexample.

### Option 3: Reject all lag and tributary evidence

This preserves a strict binary standard but loses two independent lag supports,
the common 5-6-hour range, and a real observed tributary state.

### Option 4: Admit blind evidence and tributary state, keep operators closed

This records every positive result while preserving the failed stability test
and the distinction between gauge state, mouth flux, and lateral-inflow total.

## Decision

Adopt Option 4.

Add `public_blind_transfer_evidence.py` as a typed evidence ledger. Admit the
three release-selected blind events and Smith Fork as one observed tributary
state anchor. Record that two events support the fixed 6-hour lag and that all
three best lags lie in the 5-6-hour range.

Do not admit a stable single empirical lag, physical travel time, Smith Fork
mouth flux, complete lateral inflow, observed spatial rollout, or runtime
operator. Each unsupported claim has an executable typed refusal.

## Consequences

### Positive

- Stage 28's single-event lag now has independent evidence and a real
  counterexample.
- Release-side selection prevents downstream-value cherry-picking.
- Equal observation extension removes lag-dependent pair-count differences.
- The kernel gains a public observed state on a real tributary branch.
- Missing observations and source approval states remain explicit.

### Negative

- The unanimous fixed-lag criterion fails.
- Smith Fork coverage is incomplete in two events.
- Only one of 19 tributary paths has an observed discharge state.
- No branch-mouth travel relation or reach-wide mass balance is identified.

### Risks and mitigations

- Thousands of eligible release steps may represent repeated operational
  patterns rather than independent physics. Mitigation: deterministic ranking
  and 180-day separation are frozen before outcome access.
- The 5-6-hour range could be mistaken for physical travel time. Mitigation:
  the ledger calls it empirical release response and refuses physical-time use.
- Smith Fork could be injected as a mouth flux. Mitigation: its admitted role is
  gauge state only, and mouth-flux conversion raises a typed error.
- Missing tributary values could be silently interpolated. Mitigation: each hour
  requires both observed half-hour samples and the no-fill count is gated.

## Meaning for the Geospatial Kernel

A traditional GIS and time-series workflow can locate Smith Fork, trace its
downstream path, resample discharge, rank release steps, and calculate lagged
correlations. Those operations remain necessary and are implemented with
ordinary distance, topology, time-window, aggregation, and statistical
calculations.

The Geospatial Kernel adds the world-model contract around them: event selection
cannot depend on future observation values; a release average and an
instantaneous gauge sample retain different supports; every lag uses comparable
real evidence; a station on a tributary is a state at its COMID rather than a
flux at another COMID; and partial spatial observation cannot become a closed
transition ledger. The kernel's distinctive content is therefore the typed
relationship between geographic support, temporal support, evidence lineage,
and which state-transition operators may consume the result.

## Evidence

All 27 Stage 29 gates pass:

- all 11 Stage 28 artifacts retain frozen hashes;
- all 11 Stage 29 public source objects are hash and TLS verified;
- selection plan, event manifest, and observation plan preserve phase order;
- three release-only events and 13 equal-pair lag candidates are reproducible;
- two fixed-lag supports and one rejection are preserved together;
- Smith Fork topology, series identity, coverage, approval, and gaps are
  executable; and
- stable lag, physical time, mouth flux, lateral total, rollout, and runtime
  claims fail closed.

## Next work

Stage 30 should test a regime-conditioned response kernel instead of searching
for events until a universal 6-hour value passes. The protocol should predeclare
release magnitude, step direction, and antecedent-flow strata; freeze a larger
event set; fit only on designated development strata; and evaluate untouched
events. Smith Fork should enter as a support-aware graph observation or nudging
candidate at COMID `18421273`, never as an observed confluence flux. Remaining
tributaries may use NWM only with their modeled, non-ground-truth role intact.

## Artifacts

- Acquisition:
  `scripts/acquire_geotransport_stage29_blind_transfer_events.py`
- Kernel ledger:
  `data_agent/uwm/geospatial_kernel_v2/public_blind_transfer_evidence.py`
- Tests:
  `data_agent/test_acquire_geotransport_stage29_blind_transfer_events.py` and
  `data_agent/test_geospatial_kernel_public_blind_transfer_evidence.py`
- Evidence ledger:
  `data/geotransport_v0_1/stage29_center_hill_blind_transfer_events/blind_transfer_evidence_ledger.json`
- Gate report:
  `benchmarks/geotransport_v0_1/stage29_blind_transfer_gates.json`

## Related decisions

- ADR-068: Public spatial-boundary evidence ledger
- ADR-069: Public operational-boundary lag diagnostic
- ADR-023: Geospatial Kernel branching network and tributary boundary

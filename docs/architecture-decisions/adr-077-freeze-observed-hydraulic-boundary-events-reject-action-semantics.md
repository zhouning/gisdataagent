# ADR-077: Freeze observed hydraulic-boundary events, reject action semantics

## Status

Accepted

## Context

ADR-076 showed that observation-support uncertainty cannot reconcile the
Stage 32 empirical lag sets with independently defined physical timing. The
largest empirical delay envelope remains separated from gravity-wave arrival,
Manning response centroid, and advective residence time. More interval dilation
would not supply the missing process event.

The public CWMS catalog exposes a different Center Hill signal:

```text
CETT1-CENTER_HILL.Elev-Tail.Inst.30Minutes.0.dcp-rev
```

Unlike the one-hour average release series, this is an instantaneous tailwater
elevation sampled every 30 minutes. It can locate an observed hydraulic
boundary-state perturbation more narrowly. It still does not identify a gate or
turbine command, release discharge, or a disturbance free of downstream
backwater effects.

A user-approved 72-hour development probe returned 145 complete values. At the
predeclared marker the elevation rose `0.329184m`; the response remained beyond
one quarter of that change for all 24 diagnostic intervals. The probe contains
no newly requested downstream outcome.

## Decision drivers

- Replace an interval-average release label with an observed subhourly
  hydraulic-state marker without changing its process meaning.
- Freeze source event selection and the downstream target functional before
  any new outcome values are available.
- Exclude all events whose downstream values were already examined in Stages
  28-32.
- Preserve missing samples and ambiguous quality semantics rather than filling
  or asserting approval.
- Keep statistical departure, causal response, physical first arrival, and
  travel time as distinct types of claim.
- Bound every future public request by host, date, count, attempts, and bytes.

## Considered options

### Option 1: Continue widening Stage 35 event-time intervals

This would increase numerical overlap but would not create a physical source
marker or resolve carrier and target-functional mismatches.

### Option 2: Treat tailwater elevation as the release action

The higher temporal resolution is attractive, but the series observes water
surface elevation. Local hydraulics and backwater may contribute, and no
operational command or component discharge is encoded in the value.

### Option 3: Use tailwater elevation only to select blind hydraulic-boundary
events

This admits the signal for source-side experimental support while retaining
explicit refusals for release action, release discharge, downstream response,
physical travel time, and runtime use.

### Option 4: Read downstream values first and tune a change detector

This would optimize the event and target definitions against the result being
tested. It cannot support a blind Kernel admission decision.

## Decision

Adopt Option 3.

The source event marker is the timestamp of the second sample in a primary
half-hour elevation change. Since the change occurs between samples, its event
support is `(t-30m,t]`. A candidate requires:

- an absolute primary change of at least `0.25m`;
- at least six consecutive half-hour excursion intervals;
- normalized excursion area of at least six primary-change intervals;
- at least `0.10m` standard deviation in the frozen diagnostic window;
- a complete 145-sample window and quality code `0` throughout.

Code `0` is used only as a reproducible filter. The protocol does not interpret
it as an approval status.

Four events will be selected from the 2021-2026 tailwater series. Ranking is by
descending change magnitude, support, normalized excursion, then ascending
time, with 180-day separation. Previously observed events receive a 14-day
exclusion and the development event receives a 90-day exclusion.

The target functional is also frozen now. It detects the first three-sample
persistent departure of downstream USGS discharge from a robust antecedent
baseline. Its threshold is:

```text
max(4 * 1.4826 * MAD, 0.05 * abs(baseline median), 1.0 m3/s)
```

Missing samples break persistence and are never filled. Detection is admitted
only as a statistical target functional. It is not automatically a causal
release response or a physical first arrival.

## Frozen protocol and data boundary

The operator SHA-256 is
`ae3b8e856301d3a0dd2afdf3dc1d03aa4080c66ec2cbe7455243bce6bff13b3f`.
The protocol SHA-256 is
`b0be7dedec2b7dfd933f2c81ea16a2b6bf853a3acafa499fd9beef84f7551ff7`.
It binds the development response and both Stage 35 decision artifacts.

The frozen selection plan partitions the candidate pool into five exact annual
requests. It permits only `cwms-data.usace.army.mil`, five successful requests,
three attempts per request, `1MB` per response, and `5MB` persisted in total.
It sends no workspace or private data and requests no release or downstream
values.

The separately approved source-only acquisition is complete. The five annual
responses contain 87,653 rows and 87,649 unique half-hour positions after four
identical shared year-boundary samples are deduplicated. The payloads preserve
144 explicit null values without filling. Their quality-code counts are
87,190 for code `0`, 197 for `-2147480957`, 163 for `-2147478653`, and 103 for
`-2147474557`. Complete candidate windows with any null or nonzero quality code
remain ineligible.

An interrupted first run is bound by
`interrupted_acquisition_attempt_audit.json` SHA-256
`6a0d372a39eb5bfefd77e5e4fe1961d1cb2c6986cf44df3d9394107ac18c18cb`.
The resumed acquisition preserved five logical requests, seven total attempts,
`2,535,193` persisted bytes, and zero release, downstream, or tributary
requests. Local replay produces 7,370 eligible source-only candidates and the
same four frozen events:

| Rank | Marker UTC | Direction | Primary change |
|---:|---|---|---:|
| 1 | `2023-10-04T17:30:00Z` | rise | `+1.383792m` |
| 2 | `2021-09-01T15:30:00Z` | rise | `+1.350264m` |
| 3 | `2021-03-03T23:30:00Z` | rise | `+1.344168m` |
| 4 | `2022-09-03T16:30:00Z` | rise | `+1.301496m` |

The event-selection manifest SHA-256 is
`532a94a860b65d46f2361703c6acd6c1dafa2a4ab5860b801aebe339960a7540`.
The next observation plan is frozen at SHA-256
`6402bbe5ef8fabca8090590b97379cc422bfbc557df53829f23cbfd5869e4f6f`.
It permits four exact USGS-03424860 discharge windows, one per event and each
marker plus or minus 24 hours, with no release or tributary values. The
separately approved acquisition completed in four requests and four attempts,
persisting `292,009` bytes. All returned values have approval status
`Approved`. The acquisition manifest SHA-256 is
`88c88416741287984ab5091e3d6e4a6d95384dad14a545832e76c50bf784a269`.

The first event's 2023 response contains 48 hourly samples rather than the
frozen 97-point half-hour grid. Alignment preserves 49 missing positions; only
18 real baseline samples remain, below the frozen minimum of 30. The event is
therefore unassessable without interpolation or post-outcome protocol change.
The other three windows each contain 97 approved half-hour samples and 36 real
baseline samples. Their frozen departure thresholds and results are:

| Rank | Baseline median | Baseline MAD | Threshold | Departure detected |
|---:|---:|---:|---:|---|
| 1 | unavailable | unavailable | unavailable | unassessable |
| 2 | `111.568376m3/s` | `45.448539m3/s` | `269.528014m3/s` | no |
| 3 | `259.948652m3/s` | `41.625764m3/s` | `246.857434m3/s` | no |
| 4 | `99.533716m3/s` | `73.737069m3/s` | `437.290311m3/s` | no |

No assessable event crosses the predeclared persistent-departure threshold.
The evidence ledger SHA-256 is
`81d981243976d147c2a6b2fba78bef2f478095c21fde118d24f57eab88250689`.
All 32 outcome gates pass with status
`blind_hydraulic_boundary_departure_support_rejected`; the gate report
SHA-256 is
`a48cdfbe0d808dd1e409c4676f75caf92665cef3d7a037c89bde611d8f752e58`.

## Kernel versus traditional GIS implementation

A conventional time-series workflow can difference elevations, rank changes,
and detect a downstream threshold crossing. The Geospatial Kernel contribution
is the executable evidence boundary around those calculations:

- observed boundary state is typed separately from human action and flux;
- event selection cannot see release or downstream outcome values;
- previously observed outcomes are excluded from the blind pool;
- the target functional is frozen before target data;
- statistical departure cannot be consumed as physical travel time; and
- later acquisition must match a hash-bound plan.

The individual algorithms are intentionally simple. The architectural result
is that their outputs cannot silently acquire stronger semantics downstream.

## Consequences

### Positive

- The source marker has half the grid spacing of the prior release label.
- The next events can be selected without downstream outcome leakage.
- Missingness, quality interpretation, and event-time support are explicit.
- The response functional cannot be tuned after looking at new target values.

### Negative

- Tailwater elevation may include backwater and other local hydraulic effects.
- The 30-minute grid still does not expose exact actuation or disturbance time.
- A robust statistical departure can lag or precede physical first arrival.
- Excluding prior events reduces the available candidate pool.
- The frozen blind test does not support an all-event statistical departure,
  so it cannot provide a response-timing primitive for the Kernel.

### Risks and mitigations

- Multiple changes in one operational episode could create duplicate
  candidates. Mitigation: deterministic ranking and 180-day event separation.
- Quality code `0` could be overinterpreted. Mitigation: the contract states
  that it is a filter and not an approval claim.
- A target threshold could turn into a physical-arrival claim. Mitigation:
  typed refusal methods reject causal, physical-first-arrival, and travel-time
  promotion.
- Existing downstream files could leak into event selection. Mitigation: the
  selector accepts only CWMS elevation tuples and excludes all known outcome
  events.

## Follow-up

Do not fill the 2023 half-hour gaps, lower the frozen robust threshold, or
replace the target functional within Stage 36. Any alternative observation
frequency or detector is a new pre-registered experiment and must preserve the
Stage 36 negative result.

## Evidence

At this checkpoint, 40 focused Stage 36 operator, protocol, acquisition, local
reproduction, observation-plan, and public-evidence tests pass. Downstream
evidence compilation is admitted, but all-event statistical departure support
is rejected. No causal response, physical timing, or runtime evidence is
admitted.

## Related decisions

- ADR-069 binds the prior hourly release series to the operational tailwater
  zone without equating sensors.
- ADR-073 admits event-local empirical lag support but rejects common support.
- ADR-075 distinguishes interval labels from physical process time.
- ADR-076 admits set-valued event-time uncertainty and rejects physical
  promotion.

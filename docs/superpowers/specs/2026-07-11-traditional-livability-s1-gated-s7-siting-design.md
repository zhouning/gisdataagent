# Traditional Livability S1-Gated S7 Siting Design

## Purpose

Connect LIV 2.0 S1 facility-gap assessment to S7 facility siting without turning a conditional GIS ranking into an unsupported facility recommendation. S7 may produce an authoritative primary/backup site recommendation only after a compatible, authoritative S1 assessment proves a positive facility need for the same class, geography, facility snapshot and metric profile. When need is unresolved, S7 may still expose a conditional spatial ranking, but every output must state that the ranking assumes a new facility is required and is not a site recommendation.

The first executable case remains primary-school siting for the Heping Village and Banzhu Village planning samples in Fulu Town, Bishan District.

## Problem Being Corrected

The current S7 product ranks candidate parcels using residential-land-area demand proxies and projected straight-line distance. That algorithm is useful for conditional location-allocation, but it does not establish that a new primary school is needed.

Current real Fulu data cannot establish authoritative school need because:

- the S1 product has no authoritative FP/FPP standards;
- primary-school supply rows are `not_assessed`;
- Fulu village population, school-age population and demand units are unavailable;
- school capacity, seat count and operating status are unavailable;
- the facility inventory is sampled.

Therefore the existing S7 result must be relabelled as a conditional ranking until an authoritative S1 gate is satisfied.

## Method Ownership

| Component | Method owner | Method |
|---|---|---|
| Need determination | S1 | authoritative FP/FPP assessment and positive gap |
| Need gate | S1→S7 orchestration | deterministic versioned contract validation |
| Candidate eligibility | S7 | planning and land-use rule filters |
| Candidate ranking | S7 | deterministic greedy location-allocation using declared proxy geometry and distance |
| Temporal demand or staged strategy | Not in this feature | future UWM planner only |

The complete feature remains traditional static analysis. It does not model future population, school demand, induced travel, neighbourhood adaptation or policy outcomes.

## Demand Gate Contract

Create schema:

`uwm.traditional_livability.s7_demand_gate.v1`

Required inputs:

- gate ID and creation time;
- facility standard class ID;
- target S1 administrative geography;
- target S7 planning-area IDs;
- S1 assessment ID and content digest;
- facility product ID, bundle ID and snapshot timestamp;
- metric profile ID, version and content digest;
- synthesis matrix ID and content digest when both FP and FPP apply;
- FP result, FPP result and combined result;
- gap type, observed value, threshold, comparator, gap value and unit;
- data completeness and uncertainty;
- S7 planning product ID, bundle ID and planning-area crosswalk version.

The contract is immutable and canonical-digest bound. Any change to class, geography, source snapshot, profile, matrix, gap or S7 planning product requires a new gate.

## Gate States

### `authoritative_need_confirmed`

All conditions must hold:

1. S1 profile and, where applicable, synthesis matrix are authoritative and valid;
2. S1 class matches the S7 requested facility class;
3. S1 geography maps to all requested S7 planning areas through a versioned crosswalk;
4. S1 facility bundle matches the facility bundle used by S7;
5. S1 assessment is not older than the facility snapshot represented by S7;
6. the applicable dimension or synthesis status is `does_not_meet`;
7. an explicitly positive quantity, area or capacity gap is available;
8. inventory completeness satisfies the profile's claim requirements.

Only this state permits S7 authoritative recommendation mode.

### `authoritative_need_not_confirmed`

The S1 assessment is authoritative and compatible but shows no positive need. Examples:

- applicable status is `meets`;
- quantity, area or capacity gap is zero or negative;
- the S1 standard explicitly states no additional site is required.

S7 must return `no_siting_required` and must not rank or recommend new sites unless the user starts a separate exploratory conditional analysis.

### `need_unresolved`

Any required authority, field, crosswalk, completeness or version condition is missing or inconsistent. The result lists exact blockers. S7 may run only in explicit conditional ranking mode.

## Gap Semantics

The gate supports these gap types:

- `facility_count_gap`;
- `facility_area_gap_m2`;
- `facility_capacity_gap`.

For a positive facility-count gap:

`required_site_count = ceil(gap_value)`

S7 may select no more than `required_site_count`, subject to candidate availability and positive marginal coverage.

For area or capacity gaps, S7 may claim a gap contribution only when each proposed facility option includes authoritative or approved area/capacity assumptions. Without those values, S7 may rank locations but must keep `gap_closure_assessed=false`.

Negative or zero gaps never become positive demand through absolute-value conversion or rounding.

## Geography and Version Binding

Add a versioned crosswalk product:

`uwm.traditional_livability.s1_s7_geography_crosswalk.v1`

Each row contains:

- S1 administrative geography ID and name;
- S7 planning-area ID and name;
- relationship type;
- geometry/source references;
- effective date and version;
- content digest.

The gate fails closed if:

- any requested S7 area lacks a crosswalk;
- class IDs differ;
- facility bundle IDs differ;
- S1 profile or matrix versions differ from the expected gate inputs;
- assessment time precedes an incompatible newer facility snapshot;
- crosswalk or product digests do not validate.

## S7 Run Modes

### Authoritative Recommendation Mode

Allowed only for `authoritative_need_confirmed`.

Outputs:

- `recommendation_status=authoritative_site_recommendation_available`;
- primary selected site and ordered backup sites;
- gate ID and positive-gap evidence;
- required site count and selected site count;
- unserved static demand proxy after selection;
- remaining count, area or capacity gap only when computable;
- candidate exclusions and spatial evidence;
- maximum claim level `authoritative_need_gated_static_siting`.

The UI may use “主选” and “备选” only in this mode.

### Conditional Ranking Mode

Allowed for `need_unresolved` only when explicitly requested.

Outputs:

- `recommendation_status=conditional_candidate_ranking_available`;
- ordered candidates and selection rounds from the existing algorithm;
- `not_a_site_recommendation=true` on every candidate and selected row;
- all need-gate blockers;
- current demand proxy and distance assumptions;
- maximum claim level `conditional_static_candidate_ranking`.

The UI wording is:

“假设需要新增该设施时的空间候选排序，不构成选址建议。”

The following wording is prohibited:

- 主选;
- 备选;
- 新增需求已确认;
- 建成后达标;
- 消除缺口;
- 推荐建设.

### No-Siting Mode

For `authoritative_need_not_confirmed`:

- `recommendation_status=no_siting_required`;
- no candidate ranking is executed by default;
- outputs preserve the authoritative S1 evidence explaining why no new site is required.

## S7 Engine Changes

Retain the existing projected-distance greedy location-allocation algorithm. Add a gate-aware orchestrator rather than embedding S1 authority logic into geometry scoring.

The orchestrator:

1. validates the demand gate;
2. selects the run mode;
3. limits `max_sites` by positive count gap in authoritative mode;
4. calls the existing S7 engine only when ranking is permitted;
5. relabels every output according to the active mode;
6. attaches S1 evidence, blockers and claim boundaries;
7. keeps all engine input objects detached.

The existing engine remains independently testable as a conditional geometry-ranking primitive.

## Real Fulu Product

Build a bundle containing:

- current real Fulu S7 planning and candidate product;
- current S1 product reference;
- facility product reference;
- geography crosswalk;
- demand gate;
- gated S7 result.

Under current data, the real gate must be:

`need_unresolved`

with blockers including:

- `authoritative_s1_metric_profile_missing`;
- `authoritative_synthesis_matrix_missing` where applicable;
- `fulu_village_population_or_demand_missing`;
- `school_capacity_and_operating_status_missing`;
- `facility_inventory_incomplete`.

The real S7 result may expose conditional ranking, but all rows must contain `not_a_site_recommendation=true`. The build must record zero fabricated population, capacity, school-seat, service-radius or gap values.

## API Design

Extend the traditional livability API:

- `GET /api/uwm/traditional-livability/s7/demand-gate`
  - returns the current gate, S1 evidence and blockers.

- `POST /api/uwm/traditional-livability/s7/run`
  - accepts requested mode: `authoritative` or `conditional`;
  - authoritative mode returns HTTP 409 unless gate state is `authoritative_need_confirmed`;
  - conditional mode requires explicit acknowledgement of `not_a_site_recommendation`;
  - returns the gated S7 payload.

The existing `GET /api/uwm/traditional-livability/s7` may remain for compatibility but must expose the new gate state and conditional wording. It must not preserve an unsupported recommendation label.

## Frontend Design

Update `TraditionalLivabilityS7Panel.tsx` with three sections.

### Need Evidence

Display:

- demand gate state;
- S1 FP/FPP and combined states;
- gap value and unit when available;
- class, geography, bundle and profile references;
- blockers and inventory completeness.

### Run Mode

- authoritative recommendation button enabled only when need is confirmed;
- conditional ranking button available for unresolved need after an explicit acknowledgement;
- no-siting state displays S1 evidence and disables ranking by default.

### Candidate Result

- authoritative mode: primary/backup terminology is permitted;
- conditional mode: display only candidate rank and the warning that it is not a recommendation;
- backend-provided map layers retain demand proxies, candidates, exclusions and distance coverage;
- React does not recompute need, gaps or spatial ranking.

For current Fulu data, the default panel message is:

“小学新增需求尚未被权威 S1 指标证明。以下结果仅表示假设需要新增小学情况下，基于住宅用地面积和投影直线距离代理的候选地块排序，不构成选址建议。”

## Error Handling

- invalid gate or crosswalk contract: evidence-bounded `need_unresolved` payload;
- authoritative run without confirmed need: HTTP 409;
- conditional run without explicit acknowledgement: HTTP 400;
- product or bundle mismatch: HTTP 409;
- missing gated product: HTTP 503;
- malformed request: HTTP 400;
- internal failure: HTTP 500 with stable error code and no fabricated fallback.

## Testing

Backend tests cover:

- authoritative positive count gap confirms need and caps selected sites;
- authoritative zero/negative gap returns no-siting state;
- missing profile, matrix, population, capacity or complete inventory returns unresolved;
- class, geography, bundle, timestamp and digest mismatches fail closed;
- area/capacity gap without proposed attributes cannot claim closure;
- conditional mode requires explicit acknowledgement;
- every conditional candidate contains `not_a_site_recommendation=true`;
- prohibited recommendation wording is absent from conditional payloads;
- existing S7 scoring order remains unchanged for the same geometry inputs;
- current Fulu product yields unresolved gate and conditional ranking only;
- zero fabricated need, population, capacity or gap values.

Frontend contract tests cover gate labels, separate run modes, conditional warning, disabled authoritative action and removal of unsupported primary/backup wording from current Fulu output.

## Acceptance Criteria

The feature is complete when:

1. S7 cannot emit an authoritative recommendation without a compatible positive S1 need;
2. zero or negative authoritative need prevents default siting;
3. unresolved need is visibly separated from conditional ranking;
4. current Fulu data produces conditional ranking only;
5. count gaps cap the number of selected sites;
6. area/capacity closure is reported only with source-backed proposal attributes;
7. S1 and S7 class, geography, bundle and version bindings are enforced;
8. frontend and API wording never turns conditional ranking into a recommendation;
9. real verification records all blockers and zero fabricated values;
10. focused S1, S7 and frontend regression tests plus production build pass.

# Traditional Livability S7 Fulu Primary School Siting Design

## Purpose

Implement LIV 2.0 S7 as a deterministic traditional GIS location-allocation product for primary-school siting in the two local planning sample areas of Fulu Town, Bishan District: Heping Village and Banzhu Village. The product must use real planning parcels and must not be represented as a Chongqing-wide result, a walking-network service-area result, a school-capacity conclusion, or a UWM future-policy prediction.

## Ownership and Boundary

| Item | Decision |
|---|---|
| Requirement owner | Traditional livability, LIV 2.0 S7 |
| Executed geography | Heping Village and Banzhu Village, Fulu Town, Bishan District, Chongqing sample data |
| Facility type | Primary school (`education.primary_school`) |
| Method | Deterministic parcel filtering plus greedy location-allocation |
| Accessibility model | Projected-coordinate straight-line distance proxy |
| Explicitly excluded | Walking minutes, true network service areas, capacity compliance, financial feasibility, observed intervention outcome, future policy benefit, UWM superiority |

## Data Contract

### Planning areas and parcels

Use each village planning database independently, then concatenate results with a stable `planning_area_id`:

- Heping: `.../和平村.../310基础要素/GHFW.shp`, `JQDLTB.shp`, and `320规划要素/TDGHDL.shp`;
- Banzhu: `.../斑竹村.../310基础要素/GHFW.shp`, `JQDLTB.shp`, and `320规划要素/TDGHDL.shp`.

All parcel operations must execute in the source projected CRS (EPSG:4523 for Banzhu; the equivalent CGCS2000 3-degree zone projection for Heping). The output may publish WGS84 centroids only for map display, while all reported distance values retain metres and document the CRS used.

### Demand proxy

Demand objects are `JQDLTB` parcels whose current land-use class denotes village residential/house-site use:

- Heping: `JQDLDM == "2121"` or `JQDLMC == "宅基地（村居住用地）"`;
- Banzhu: `JQDLDM == "2121"` or `JQDLMC == "村居住用地"`.

The parcel centroid is the demand location. Its positive parcel area is the demand weight. This is a **residential-land-area proxy**, not a student count, school-age population, enrolment demand, household count or capacity requirement.

### Existing supply

Existing supply comes from the Phase 1A facility product where `canonical_class == "education.primary_school"`. Only school points inside a planning-area boundary are classified as locally verified current supply. Schools outside the boundary can be returned as reference supply if a configurable reference radius is used, but must be labelled `outside_planning_area_reference` and do not establish complete supply coverage.

### Candidate parcels

Candidate geometry and planned land-use labels come from `TDGHDL`. A parcel is eligible only when its planned/current planned class is one of:

- `2123` / `村公共服务用地`;
- `2124` / `村混合用地`;
- `214` / `其他独立建设用地`.

All other parcels are excluded. In particular, the engine must explicitly report exclusions for cultivated land, gardens, forest, water, roads, mining land, facilities agriculture land, and natural reservation land. It must never auto-relax the candidate policy because the eligible count is small or zero.

Candidate suitability is an explainable ordinal score: public-service land = 3, mixed land = 2, other independent construction land = 1. A candidate with non-positive/unknown planned area is excluded with `invalid_area`.

## Distance Proxy and Allocation

The provider contract is `distance_cost_provider="projected_straight_line_distance_proxy"`. Distance is computed between projected centroids in metres. It is not a road route, travel time, walking time or network service area.

`coverage_distance_m` is caller-configurable and must be written into all outputs. The initial UI default is 1,500 m, an analytical distance threshold only, not a 15-minute walking claim.

The baseline coverage set is demand parcels within `coverage_distance_m` of locally verified existing schools. For each allocation round, evaluate every unselected candidate:

1. identify demand parcels within the threshold;
2. calculate newly covered demand weight not already covered by baseline or prior selections;
3. calculate repeated covered demand weight already covered;
4. rank by descending new coverage, ascending repeated coverage, descending suitability, descending candidate area, then stable parcel ID;
5. select the highest-ranked candidate; repeat until `max_sites` is reached or no candidate has positive new coverage.

This is greedy location-allocation, not a global mathematical optimum. Outputs must name the algorithm and tie-break order.

## Output Contract

`uwm.traditional_livability.s7_siting.v1` contains:

- `executed_geography`, planning-area IDs and source manifest references;
- `assumptions` including distance proxy, coverage threshold, demand proxy and algorithm;
- `candidate_filter_funnel`, input/eligible/excluded counts and reason counts;
- `demand_summary`, total proxy area, baseline-covered/uncovered proxy area and demand parcel count;
- `ranked_candidates`, with suitability, new/repeated coverage proxy area, coverage count, rank and selection round;
- `selected_sites`, aggregate proxy coverage results and unserved proxy area;
- `geometry_payload` containing display centroids and circles only when explicitly requested;
- `data_support`, source completeness, planning-area scope and sampling state;
- `production_blockers` and `claim_boundary`.

The engine must return `candidate_policy_no_eligible_parcels` rather than a fabricated recommendation when filtering yields no candidates. Missing planning inputs must return a fail-closed readiness payload rather than substitute arbitrary candidate points.

## UI and Map Interaction

Use the selected analysis-led two-column layout:

- left: task configuration, scope, proxy wording, filter funnel, ranking table, selected sites, blockers and claim boundary;
- right: planning boundary, residential-demand centroids, eligible candidates, excluded parcels by reason, selected candidates and distance-proxy coverage circles;
- map action: queue only the output geometry actually generated by the S7 engine and label the layer `距离代理覆盖范围`, never `步行服务区`.

The UI must show `采样库存` when upstream facility inventory is sampled and `完整库存` only when the source manifest explicitly says so.

## Production Blockers

The output must surface, where applicable:

- authoritative LIV 2.0 43-class dictionary missing;
- FP/FPP standards missing;
- school capacity, enrolment and operating status missing;
- student/school-age population missing;
- complete village pedestrian/road network missing;
- authoritative parcel ownership, acquisition, DCR, BOQ and finance inputs missing;
- local planning data limited to the two sample villages.

## Acceptance Criteria

1. A fixture with eligible public-service/mixed/construction parcels ranks candidates deterministically by the stated rule.
2. Agricultural, forest, water, road and natural-reservation parcels are excluded with exact reasons.
3. The product reports proxy area, not student counts; it never returns walking minutes.
4. No eligible candidate produces a no-recommendation result with the policy reason.
5. The adapter handles both village CRS sources and records their projected distance CRS.
6. API and UI fail closed when the offline S7 snapshot is unavailable.
7. Real-data validation identifies that the result covers only the two village planning samples and reports actual eligible-candidate count, demand proxy area and all blockers.

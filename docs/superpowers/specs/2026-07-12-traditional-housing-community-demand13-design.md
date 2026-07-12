# Traditional Housing and Community Evidence Demand 13 Design

Date: 2026-07-12

## 1. Purpose

This design implements an evidence-bounded subset of customer demand 13, housing and community composition, inside `城市宜居性分析（传统方法）`.

The product is named `住房与社区构成证据（需求13）`. It exposes building-morphology context, district population statistics, downscaled population proxies, service-neighbourhood context and housing-data readiness. It does not estimate housing units, residential floor area, affordability, tenure, household composition, crowding or housing shortage.

## 2. Source Requirement

Demand 13 requests:

- housing types;
- affordability indicators;
- family suitability;
- worker accommodation;
- density;
- household size;
- ownership/rental tenure;
- mixed-use balance;
- proximity between housing, jobs and services;
- analysis of whether housing composition supports population profile, daily needs, service demand and quality-of-life goals;
- housing profile, community-composition assessment, housing-service proximity and housing-gap recommendations.

The current evidence supports only built-form and population context plus selected service-proximity proxies.

## 3. Technical Ownership

Primary route: `traditional_livability`.

Supported methods:

- building-floor morphology inventory;
- building-assignment coverage audit;
- district population statistics;
- fitted township population proxy;
- exact administrative-ID evidence joins;
- service-neighbourhood context;
- spatial-grain and source-quality audit;
- relative housing/community evidence-gap ranking;
- data-acquisition priorities.

UWM is not used for the first release because there is no calibrated housing-stock transition, household migration, affordability response, tenure transition, development intervention or counterfactual housing outcome model.

## 4. Existing Evidence Foundation

### 4.1 Building Morphology

Verified artifact observations:

- source building records: 107,452;
- parsed geometries: 107,452;
- assigned buildings: 44,887;
- unassigned buildings: 62,565;
- administrative units: 36;
- total floor-count proxy: 322,665;
- maximum observed floor count: 66;
- building count, total floors, average floors, maximum floors and bounding-box area per supported administrative unit.

Assignment uses building bounding-box centre inside administrative bounding boxes. It is not an authoritative cadastral or polygon-overlay housing inventory.

### 4.2 District Population Statistics

Verified 2021 district-level statistics:

- 39 district rows;
- registered households;
- registered population;
- registered urban/rural population;
- resident population;
- resident urban population;
- urbanization rate.

These fields support district population context, not household microstructure.

### 4.3 Downscaled Population Proxy

Verified fitted proxy observations:

- 852 administrative rows;
- district totals allocated by GHSL population or built-surface proxy weights;
- explicit synthetic status and allocation basis;
- district-total consistency checks.

Mandatory interpretation:

```text
downscaled_population_not_census_microdata=true
allocation_weight_not_observed_household_distribution=true
```

## 5. Product Views

One bundle exposes three independent evidence views:

```text
building_morphology_context
population_context
housing_evidence_readiness
```

No view may be labelled housing stock, housing supply or household composition.

## 6. Building-Morphology Contract

Supported fields:

```text
admin_unit_id
county
township
building_count
floor_count_sum
average_floor
max_floor
assignment_rule
bbox_area_degrees2
service_point_count
essential_service_count
ghsl_population_proxy_sum
ghsl_built_surface_proxy_sum
```

Mandatory interpretation:

```text
building_count_not_housing_unit_count=true
floor_count_not_residential_floor_area=true
building_morphology_not_housing_type=true
building_assignment_not_cadastral_inventory=true
```

No conversion factor from buildings/floors to dwellings is permitted.

## 7. Population Contract

### 7.1 District Statistics

District statistics remain at district level unless an explicit administrative-code relationship is used.

Supported fields may include:

```text
admin_code
district_name
year
registered_households_10k
registered_population_10k
registered_urban_population_10k
registered_rural_population_10k
resident_population_10k
resident_urban_population_10k
urbanization_rate_percent
```

Registered household count is not household size. Household size requires a valid numerator/denominator definition and still does not establish family composition.

### 7.2 Downscaled Proxy

Supported fields:

```text
admin_unit_id
admin_code
county
township
district_resident_population
downscaled_population
allocation_weight
allocation_basis
synthetic_status
```

Mandatory interpretation:

```text
population_proxy_not_observed_household_count=true
population_density_not_housing_crowding=true
population_proxy_not_service_demand_observation=true
```

## 8. Exact Join Contract

Join statuses:

```text
exact_supported
aggregate_supported
reference_only
incompatible
```

Rules:

- building morphology and downscaled population may join only by identical `admin_unit_id`;
- district population may attach through explicit `admin_code` or a documented district parent code;
- names, centroids, row order and approximate spatial proximity cannot create joins;
- unmatched evidence remains in separate views;
- missing values remain null;
- no interpolation or imputation is performed.

## 9. Product Contract

Schema: `traditional_livability.housing_community_evidence.v1`.

The immutable bundle contains:

```text
overview.json
admin_units.json
channel_readiness.json
evidence_sources.json
map.json
```

Each supported administrative row includes:

```text
admin_unit_id
county
township
building_morphology_context
population_proxy_context
district_population_context
service_neighbourhood_context
evidence_coverage
relative_housing_community_evidence_gap_rank
evidence_gap_reasons
field_collection_priorities
source_trace
limitations
```

Forbidden fields include:

```text
housing_unit_count
residential_floor_area
housing_supply
housing_shortage
affordability_score
crowding_score
family_suitability_score
mixed_use_balance_score
```

## 10. Channel Readiness

Statuses:

```text
implemented
proxy_only
unavailable
```

### 10.1 Implemented

- building morphology context;
- building-assignment coverage;
- district population statistics;
- downscaled population proxy;
- service-neighbourhood context where present;
- exact-ID join audit;
- evidence coverage and missingness;
- relative evidence-gap ranking;
- field-data acquisition priorities.

### 10.2 Proxy Only

- built-form intensity represented by building/floor morphology;
- small-area population represented by fitted downscaling;
- population/building context represented by exact-ID co-availability;
- service proximity represented by observed service-point/essential-service context;
- relative housing/community evidence gap.

Every proxy output carries:

```text
building_count_not_housing_unit_count=true
floor_count_not_residential_floor_area=true
downscaled_population_not_census_microdata=true
population_density_not_housing_crowding=true
relative_gap_not_authoritative_housing_shortage=true
```

### 10.3 Unavailable

- building use and residential/non-residential classification;
- housing type;
- dwelling or housing-unit count;
- residential floor area;
- occupied/vacant units;
- housing price and rent;
- affordability;
- ownership/rental tenure;
- household size at supported small-area level;
- household and family composition;
- child, elderly and worker-household structure;
- worker accommodation;
- family suitability;
- housing crowding;
- observed housing-job proximity;
- observed commuting between home and work;
- mixed-use balance;
- housing stock condition and lifecycle;
- housing demand and shortage;
- housing development recommendations;
- causal policy/development effects;
- future household and housing demand.

Unavailable values remain null.

## 11. Relative Evidence-Gap Ranking

The product ranks housing/community evidence incompleteness, not housing need.

Ordering uses:

1. missing building-morphology context;
2. missing downscaled population proxy;
3. missing district population context;
4. missing service-neighbourhood context;
5. reference-only/incompatible source relationship;
6. low building-assignment coverage where available;
7. stable administrative identifier tie-breaker.

Rank name:

```text
relative_housing_community_evidence_gap
```

Forbidden interpretations:

- housing shortage;
- overcrowding;
- unaffordability;
- unsuitable family housing;
- worker-accommodation deficit;
- development priority.

## 12. Evidence-Acquisition Priorities

The product may generate data-collection priorities for:

- building-use classification;
- dwelling and housing-unit register;
- residential gross floor area;
- occupancy and vacancy;
- price, rent and affordability;
- tenure;
- household size and family composition;
- worker accommodation;
- home-work origin-destination and commuting;
- mixed-use land/building composition;
- housing condition, age and lifecycle;
- approved housing projects and pipeline.

These are evidence priorities, not housing recommendations.

## 13. Map Contract

Separate layers:

- building-morphology context;
- downscaled population proxy;
- district population reference;
- evidence-gap/data-collection priority.

The frontend must not produce a housing-shortage, affordability or overcrowding heatmap.

## 14. Evidence and Claim Gates

The builder and independent verifier reject:

- building count converted to housing units;
- floor count converted to residential floor area;
- downscaled population labelled census microdata;
- population density labelled crowding;
- district registered households interpreted as local household composition;
- names, centroids or row order used for joins;
- unavailable housing fields populated numerically;
- housing-shortage, affordability, family-suitability or mixed-use scores;
- development recommendation or causal-effect wording;
- bundle identifier mismatch;
- implementation status above `implemented_evidence_bounded`.

Claim boundary:

```text
max_claim_level=building_morphology_population_context_and_housing_evidence_readiness
housing_stock_claim=false
housing_unit_claim=false
housing_affordability_claim=false
household_composition_claim=false
housing_crowding_claim=false
housing_shortage_claim=false
causal_housing_policy_effect_claim=false
```

## 15. Service and API

Read-only endpoints:

```text
GET /api/uwm/traditional-livability/housing-community/overview
GET /api/uwm/traditional-livability/housing-community/admin-units
GET /api/uwm/traditional-livability/housing-community/admin-units/{admin_unit_id}
GET /api/uwm/traditional-livability/housing-community/evidence-sources
GET /api/uwm/traditional-livability/housing-community/map
```

The service loads a verified prebuilt bundle and performs no request-time joins or housing calculations.

## 16. Frontend

Add `住房与社区构成证据（需求13）` inside `城市宜居性分析（传统方法）`.

The panel displays:

- building-source and assignment coverage;
- building/floor morphology;
- district population context;
- fitted population proxy and its synthetic status;
- exact-ID join coverage;
- service-neighbourhood context;
- relative evidence-gap ranking;
- unavailable housing channels;
- data-acquisition priorities;
- separate map layers.

Prominent statements:

```text
建筑数量不等于住房套数
楼层数量不等于住宅面积
下推人口不等于人口普查微观数据
人口密度不等于住房拥挤
```

## 17. Ledger Status

After real product construction and independent verification, demand 13 becomes:

```text
implemented_evidence_bounded
```

Maximum supported claim:

```text
building_morphology_population_context_and_housing_evidence_readiness
```

The ledger retains housing-use, unit, affordability, tenure, household, crowding, commuting, mixed-use, demand and policy-effect blockers.

## 18. Acceptance Criteria

The implementation is accepted only when:

- all five files share one deterministic bundle ID;
- all source grains and join rules are explicit;
- building and population joins are exact-ID/code supported;
- no housing-unit or residential-area conversion occurs;
- fitted population remains labelled proxy;
- unavailable housing fields remain null;
- rankings measure evidence gaps only;
- independent verification passes against the real Chongqing bundle;
- API and frontend expose all boundaries;
- focused Python tests and frontend production build pass;
- protected Paper58/TWM files remain untouched;
- the ledger references real artifacts and preserves blockers.

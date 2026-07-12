# Traditional Safety and Comfort Evidence Demand 10 Design

Date: 2026-07-12

## 1. Purpose

This design implements an evidence-bounded subset of customer demand 10, safety, security and comfort, inside `城市宜居性分析（传统方法）`.

The product is named `安全与舒适证据诊断（需求10）`. It exposes road-network, service-accessibility and environmental context together with a complete readiness matrix. It does not estimate pedestrian risk, crash probability, crime risk, safe routes, thermal comfort, accessibility compliance or intervention effects.

The first release is an evidence diagnostic and data-acquisition prioritization product, not a safety assessment model.

## 2. Source Requirement

Demand 10 requests:

- traffic safety;
- pedestrian safety;
- lighting;
- emergency access;
- safe crossings;
- natural surveillance;
- thermal comfort;
- shaded travel corridors;
- accessibility for People of Determination;
- analysis of safety, security, comfort, universal accessibility and perceived convenience;
- identification of gaps limiting confident and comfortable use of services, public spaces and community facilities;
- safety and comfort assessment, pedestrian-risk map, lighting/shade gap analysis and prioritized safety interventions.

Most requested outcome channels currently lack authoritative observations. The product retains every channel in a readiness contract rather than fabricating a complete assessment.

## 3. Technical Ownership

Primary route: `traditional_livability`.

Supported methods:

- existing road-network and service-accessibility context;
- existing temperature, wind and PM2.5 environmental context;
- administrative evidence coverage audit;
- spatial-grain compatibility checks;
- deterministic missing-evidence diagnosis;
- field-data acquisition priority ranking;
- source and claim trace.

UWM is not used for the first release because there is no calibrated safety-state transition, intervention-response, propagation, recovery or counterfactual safety model. Static road and temperature fields must not be relabelled as a world model.

## 4. Existing Evidence Foundation

The product reuses verified artifacts without recomputation:

- demand-8 mobility and accessibility product:
  - 1,017 administrative units;
  - 50,332 road records;
  - 5,085 mobility-graph relationships;
  - network travel-time and service-accessibility proxies;
- demand-11 environmental evidence:
  - PM2.5 observed/calibrated temporal context;
  - environmental administrative observations;
- GEE/ERA5 environmental proxy products:
  - `temperature_2m_mean_c` where present;
  - `wind_speed_10m_ms` where present;
- the verified facility product:
  - only two records classified as `public_safety.facility`, both fire-service related.

The two public-safety facility records do not establish emergency-response coverage, response time, police coverage, crime conditions or public safety.

## 5. Evidence Channel Model

The product keeps independent evidence families:

```text
mobility_context
meteorology_context
air_quality_context
public_safety_facility_context
missing_authoritative_safety_evidence
```

Channels are never collapsed into a single safety or comfort score.

### 5.1 Mobility Context

Supported fields may include:

- road segment count;
- road-length proxy;
- mobility-graph connectivity context;
- nearest-service distance;
- network travel-time proxy;
- service-accessibility score;
- source quality and negative-control evidence.

Mandatory interpretation:

```text
network_context_not_road_safety=true
observed_crash_risk=false
observed_pedestrian_risk=false
safe_route_claim=false
```

### 5.2 Meteorology Context

Supported fields may include:

- mean 2-metre air temperature;
- mean 10-metre wind speed;
- observation time range;
- source coverage and missingness.

Mandatory interpretation:

```text
temperature_context_not_thermal_comfort=true
thermal_comfort_index_calculated=false
human_heat_stress_claim=false
shade_effect_claim=false
```

Temperature alone is not Universal Thermal Climate Index, Wet Bulb Globe Temperature, Physiological Equivalent Temperature or observed outdoor comfort.

### 5.3 Air-Quality Context

PM2.5 may be exposed only as environmental exposure context. The demand-11 temporal kernel remains the owner of PM2.5 dynamics.

Mandatory interpretation:

```text
air_quality_context_not_personal_safety=true
causal_health_effect_claim=false
safety_intervention_effect_claim=false
```

### 5.4 Public-Safety Facility Context

The two available fire-service POIs may be shown as observed inventory records only.

They must not produce:

- response-time estimates;
- service-area coverage;
- emergency-access compliance;
- emergency preparedness scores;
- police or crime coverage conclusions.

## 6. Spatial-Grain Contract

Every source carries:

```text
source_spatial_unit
source_spatial_unit_count
source_time_range
join_key
join_status
join_reason
```

Join status is one of:

```text
exact_supported
aggregate_supported
reference_only
incompatible
```

Rules:

- exact joins require an explicit common administrative identifier;
- aggregate joins require a documented parent-child crosswalk;
- names, centroids or row order cannot create a join;
- incompatible mobility and environmental rows remain separate evidence panels;
- missing matches remain null, never zero;
- no interpolation is performed in the first release.

## 7. Product Contract

Schema: `traditional_livability.safety_comfort_evidence.v1`.

The immutable bundle contains:

```text
overview.json
admin_units.json
channel_readiness.json
evidence_sources.json
map.json
```

Each administrative evidence row includes only supported fields:

```text
admin_unit_id
county
township
mobility_context
meteorology_context
air_quality_context
public_safety_facility_context
evidence_coverage
relative_safety_comfort_evidence_gap_rank
evidence_gap_reasons
field_collection_priorities
source_trace
limitations
```

No field named `safety_score`, `crime_score`, `pedestrian_risk_score`, `thermal_comfort_score` or `safe_route_score` is permitted.

## 8. Channel Readiness

Each source-requirement channel has one status:

```text
implemented
proxy_only
unavailable
```

### 8.1 Implemented

- mobility evidence context;
- meteorology evidence context where present;
- air-quality evidence context where present;
- source coverage and missingness audit;
- spatial-grain compatibility audit;
- field-data collection priority;
- source and claim trace;
- observed public-safety facility inventory.

### 8.2 Proxy Only

- service convenience context;
- road-network connectivity context;
- temperature exposure context;
- wind context;
- PM2.5 exposure context;
- relative evidence-gap ranking.

Proxy outputs must carry explicit non-outcome flags.

### 8.3 Unavailable

- traffic crashes and conflict observations;
- pedestrian incidents and near misses;
- pedestrian-risk model;
- crime and security incidents;
- perceived safety and comfort surveys;
- lighting inventory and illuminance;
- safe-crossing inventory;
- emergency-access routes and observed response times;
- natural-surveillance evidence;
- tree-canopy and shaded-corridor path evidence;
- ramps, kerbs, tactile paving and barrier inventory;
- universal-accessibility compliance;
- observed outdoor thermal comfort;
- UTCI, WBGT or PET calibration;
- safe-route analysis;
- authoritative safety intervention priorities;
- causal intervention effects.

Unavailable values remain null.

## 9. Relative Evidence-Gap Ranking

The product ranks evidence incompleteness, not danger.

The rank is named:

```text
relative_safety_comfort_evidence_gap
```

Ordering uses:

1. number of unavailable critical safety channels;
2. absence of mobility context;
3. absence of meteorology context;
4. absence of air-quality context;
5. incompatible or reference-only source joins;
6. stable administrative identifier tie-breaker.

Each row exposes its ranking reasons.

The following interpretations are forbidden:

- higher rank means more dangerous;
- higher rank means higher crime;
- higher rank means worse thermal comfort;
- higher rank is an engineering investment priority.

## 10. Field-Collection Priorities

The product may create deterministic evidence-acquisition priorities:

- crash and near-miss records;
- pedestrian counts and conflict observations;
- street-light assets and measured illuminance;
- crossings, signals and refuge islands;
- emergency-route and response-time records;
- tree canopy, shade duration and shaded-path evidence;
- ramps, kerbs, tactile paving, barriers and gradients;
- perceived safety and comfort surveys;
- calibrated outdoor thermal-comfort measurements.

These are data-collection priorities, not safety interventions.

## 11. Map Contract

Map layers remain separate:

- mobility/network context;
- meteorology context;
- air-quality context;
- observed fire-service facility points;
- evidence-gap and field-collection priority.

The frontend must not combine these layers into a red/amber/green safety map.

## 12. Evidence and Claim Gates

The builder and independent verifier reject:

- any numeric value in unavailable channels;
- temperature labelled as thermal comfort;
- network connectivity labelled as road or pedestrian safety;
- PM2.5 labelled as crime, security or personal safety;
- two fire-service POIs labelled as emergency coverage;
- inferred cross-source joins based on names or centroids;
- missing values converted to zero;
- composite safety, security or comfort scores;
- pedestrian-risk, safe-route or intervention-effect wording;
- bundle identifier mismatch;
- implementation status above `implemented_evidence_bounded`.

Claim boundary:

```text
max_claim_level=mobility_environment_context_and_evidence_readiness
observed_safety_outcome_claim=false
observed_crime_or_security_claim=false
thermal_comfort_claim=false
safe_route_claim=false
universal_accessibility_compliance_claim=false
causal_intervention_effect_claim=false
```

## 13. Service and API

Read-only endpoints:

```text
GET /api/uwm/traditional-livability/safety-comfort/overview
GET /api/uwm/traditional-livability/safety-comfort/admin-units
GET /api/uwm/traditional-livability/safety-comfort/admin-units/{admin_unit_id}
GET /api/uwm/traditional-livability/safety-comfort/evidence-sources
GET /api/uwm/traditional-livability/safety-comfort/map
```

The service loads a verified prebuilt bundle and performs no request-time source fusion or scoring.

## 14. Frontend

Add `安全与舒适证据诊断（需求10）` inside `城市宜居性分析（传统方法）`.

The panel displays:

- evidence-source coverage;
- mobility, temperature, wind and PM2.5 contexts as independent channels;
- spatial-grain and join status;
- unavailable safety/comfort channels;
- relative evidence-gap ranking;
- field-data collection priorities;
- separate map layers.

The panel prominently states:

```text
证据缺口排名不代表危险程度
温度上下文不等于热舒适
路网上下文不等于道路安全
```

## 15. Ledger Status

After real product construction and independent verification, demand 10 becomes:

```text
implemented_evidence_bounded
```

Maximum supported claim:

```text
mobility_environment_context_and_safety_comfort_evidence_readiness
```

The ledger retains all safety-outcome, crime, lighting, crossing, shade, accessibility, thermal-comfort and intervention-effect blockers.

## 16. Acceptance Criteria

The implementation is accepted only when:

- all five files share one deterministic bundle ID;
- source spatial grains and time ranges are explicit;
- joins are exact/crosswalk-supported or remain separate;
- no unavailable channel contains a numeric value;
- no composite safety or comfort score exists;
- rankings measure evidence gaps only;
- field priorities are labelled as data collection;
- independent verification passes against the real Chongqing bundle;
- API and frontend expose claim boundaries;
- focused Python tests and frontend production build pass;
- protected Paper58/TWM files remain untouched;
- the ledger references real artifacts and preserves all blockers.

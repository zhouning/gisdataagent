# Traditional Social Infrastructure and Public Service Demands 12/21 Design

Date: 2026-07-11

## 1. Purpose

This design implements customer demands 12 and 21 in `城市宜居性分析（传统方法）` through one shared, evidence-bounded facility/service foundation and two requirement-specific views. It does not duplicate the same calculation under traditional GIS and UWM labels.

Demand 12 receives a social-infrastructure and community-facility view. Demand 21 receives a government-institution and public-service view. Both diagnose the current available spatial evidence. Neither predicts action-conditioned future states, propagation, recovery or policy outcomes, so UWM is not the primary route for this release.

## 2. Source Requirements

### 2.1 Demand 12

The source requirement asks for schools, childcare, clinics, mosques, community centres, sports, parks, libraries, youth, elderly, cultural and family facilities; lifecycle and active/inactive composition; drawing verification; service areas; population demand; service capacity; accessibility; overload, missing facilities and future demand.

Expected outputs include a social-infrastructure inventory, service-area analysis, community-facility gap map and prioritized needs.

### 2.2 Demand 21

The source requirement asks for government institutions and public-service types, locations, availability, service areas, accessibility and matching with population, quality-of-life and livability needs.

Expected outputs include a public-service inventory, coverage, accessibility map, underserved-community diagnosis and service-improvement suggestions.

## 3. Technical Ownership

Primary route: `traditional_livability`.

Methods:

- deterministic facility classification;
- inventory and source trace;
- administrative aggregation;
- category diversity and presence/absence;
- nearest-service and existing accessibility proxies;
- relative evidence-gap ranking;
- map layers and manual-review candidates;
- explicit readiness and evidence gates.

UWM is reserved for a later product only when evidence supports temporal state transitions, interventions, spatial propagation, counterfactual comparison, recovery or policy planning. A static facility count must never be presented as a world model.

## 4. Shared Evidence Foundation

The product reuses rather than recomputes:

- the S1 facility inventory and service-area evidence;
- the S6 semantic facility dictionary and classification trace;
- the demand-8 administrative accessibility surface and road-network proxies;
- available Chongqing administrative geometry;
- available OSM/service POI evidence.

The shared foundation normalizes facility records into canonical categories, binds them to administrative units where supported, and exposes source coverage and missing-data reasons. Existing artifacts remain authoritative for their own calculated fields; this product is an orchestration and requirement-specific interpretation layer.

## 5. Product Structure

Schema: `traditional_livability.social_public_service.v1`.

One immutable bundle contains:

```text
overview.json
facilities.json
admin_units.json
channel_readiness.json
map.json
```

`overview.json` contains shared provenance, summary counts, blockers and separate demand-12 and demand-21 summaries.

`facilities.json` contains the canonical evidence inventory with view membership.

`admin_units.json` contains shared administrative evidence plus two independent view payloads.

`channel_readiness.json` prevents unavailable requirement channels from silently becoming zero scores.

`map.json` contains source-backed point and administrative features only.

## 6. Canonical Facility Contract

Each facility record includes only supported fields:

```text
facility_id
name
raw_category
canonical_category
view_membership
longitude
latitude
admin_unit_id
source_dataset
source_record_id
classification_method
classification_confidence
lifecycle_status
active_status
capacity
service_radius_m
source_trace
limitations
```

Unsupported lifecycle, activity, capacity and service-radius fields remain null. Null is not converted to zero, inactive, unknown capacity score or assumed planning standard.

## 7. Demand-12 View

The social-infrastructure view supports:

- source-backed facility inventory;
- canonical social/community category counts;
- category presence and diversity by administrative unit;
- nearest supported social facility evidence;
- reuse of supported accessibility proxies;
- relative evidence-gap ranking;
- human-review candidates for inventory enrichment or planning investigation.

The initial canonical category set covers only categories found in the evidence dictionary. Requested categories without a reliable mapping remain visible as unavailable or unmapped channels rather than being folded into unrelated POIs.

The view must label relative gaps as `relative_evidence_gap`, not capacity shortage, overload or future need.

## 8. Demand-21 View

The government/public-service view supports:

- source-backed government and public-service inventory;
- service-type counts and diversity by administrative unit;
- nearest supported public-service evidence;
- reuse of supported accessibility proxies;
- relative service-evidence gap ranking;
- manual-review candidates for service placement or data completion.

Suggestions are review priorities derived from transparent rules. They are not authoritative siting recommendations and not evidence of policy benefit.

## 9. Channel Readiness

Every requirement channel uses one status:

```text
implemented
proxy_only
unavailable
```

### 9.1 Implemented

- source-backed facility/service inventory;
- deterministic semantic classification;
- administrative counts and category diversity;
- source and classification trace;
- administrative relative-gap ranking;
- point and administrative map layers;
- explicit evidence blockers.

### 9.2 Proxy Only

- service coverage represented by inventory presence or existing accessibility fields;
- nearest-service accessibility where supported by existing products;
- community/service gap represented by relative evidence ranking;
- improvement priority represented by deterministic manual-review priority.

Every proxy result carries:

```text
relative_proxy_not_authoritative_standard=true
observed_capacity_match=false
policy_outcome_claim=false
```

### 9.3 Unavailable

- authoritative facility capacity;
- population-to-capacity matching;
- overload determination;
- authoritative lifecycle status;
- active/inactive internal composition;
- MEPS/BDMS drawing verification;
- approved service-radius standards where absent;
- authoritative service-area coverage where absent;
- observed service quality and availability;
- future population demand;
- future facility demand;
- causal service-improvement effects.

Unavailable numeric outputs remain null and are excluded from scores and rankings.

## 10. Relative Gap Logic

The product does not create a hidden composite livability score.

Demand-12 ordering uses, when present:

1. zero supported social/community facilities;
2. lower canonical-category diversity;
3. lower facility count;
4. weaker existing accessibility evidence;
5. stable administrative identifier tie-breaker.

Demand-21 ordering uses, when present:

1. zero supported government/public-service facilities;
2. lower service-type diversity;
3. lower service count;
4. weaker existing accessibility evidence;
5. stable administrative identifier tie-breaker.

Each rank exposes its reasons and missing evidence. Rankings compare records inside the bound product only and must not be interpreted as statutory service deficits.

## 11. Evidence and Claim Gates

The builder and independent verifier reject:

- numeric values in unavailable channels;
- assumed capacity, population, service radius or lifecycle values;
- facilities without source trace;
- bundle-file identifier mismatch;
- duplicate canonical facility identifiers;
- authoritative shortage, overload, need or policy-effect wording;
- a demand status above `implemented_evidence_bounded` while blockers remain.

The product claim boundary is:

```text
max_claim_level=observed_inventory_and_relative_proxy
authoritative_service_deficit_claim=false
authoritative_capacity_claim=false
future_demand_claim=false
causal_policy_effect_claim=false
```

## 12. Service and API

Read-only endpoints:

```text
GET /api/uwm/traditional-livability/social-public-service/overview
GET /api/uwm/traditional-livability/social-public-service/facilities
GET /api/uwm/traditional-livability/social-public-service/admin-units
GET /api/uwm/traditional-livability/social-public-service/admin-units/{admin_unit_id}
GET /api/uwm/traditional-livability/social-public-service/map
```

List endpoints accept a `view` filter with `social_infrastructure` or `government_public_service`. The service loads a prebuilt verified bundle and does not recompute evidence during requests.

## 13. Frontend

Add one section inside `城市宜居性分析（传统方法）` with two explicit subviews:

- `社会基础设施（需求12）`;
- `政府与公共服务（需求21）`.

The panel shows inventory counts, mapped categories, administrative relative-gap ranking, readiness, blockers and claim boundaries. Capacity, overload, lifecycle and future-demand cards show `数据未就绪`, never zero.

## 14. Ledger Status

After a real product is built and independently verified:

- demand 12 becomes `implemented_evidence_bounded`;
- demand 21 remains or becomes `implemented_evidence_bounded`;
- blockers retain unavailable capacity, lifecycle, population matching and authoritative service standards.

Registration, API presence or frontend rendering alone cannot upgrade the ledger.

## 15. Acceptance Criteria

The implementation is accepted only when:

- all five bundle files share one deterministic bundle ID;
- all facilities have traceable source and classification evidence;
- both views include every administrative unit supported by the shared foundation;
- unavailable channels contain no fabricated numeric values;
- rankings are deterministic and expose reasons;
- the independent verifier passes against a real Chongqing bundle;
- API and frontend expose both views and evidence boundaries;
- focused Python tests and frontend build pass;
- the ledger references real artifacts and accurately reports remaining blockers.


# Traditional Mobility and Accessibility Demand 8 Design

Date: 2026-07-11

## 1. Purpose

This design implements customer AI demand 8, mobility, walkability and accessibility, inside `城市宜居性分析（传统方法）`. It uses established GIS network, distance, inventory and gap-analysis methods. It is not a UWM scenario because the first product diagnoses the current observed/proxy network state and does not predict action-conditioned future states.

The product must preserve the full customer requirement while exposing which channels are currently implemented, proxy-only or unavailable. It must not compress missing transit, safety, shade and accessibility data into a fabricated composite walkability score.

## 2. Source Requirement

Demand 8 requests:

- walking networks and walking distance to services;
- cycling routes;
- public-transport accessibility;
- first/last-mile connections;
- shaded routes;
- universal accessibility;
- parking pressure;
- pedestrian crossings and road safety;
- identification of communities unable to reach daily services comfortably, safely and conveniently;
- mobility and walkability assessment, accessibility gap map, safe-route analysis, transit coverage and prioritized connectivity improvements.

The current Chongqing evidence does not support all these outputs. The product therefore uses explicit channel readiness rather than claiming complete fulfillment.

## 3. Technical Ownership

Primary route: `traditional_livability`.

Primary methods:

- facility and service inventory;
- road-network and distance proxies;
- nearest-service analysis;
- deterministic accessibility scoring;
- administrative aggregation;
- gap ranking;
- map visualization;
- data-readiness and evidence gates.

UWM must not be used merely to relabel these static calculations. Future intervention effects or long-term mobility evolution, if requested later, require a separate UWM specification.

## 4. Existing Evidence Foundation

The first release binds existing Chongqing artifacts:

- `full_admin_service_accessibility_surface_2026_07_08`;
- `full_admin_mobility_graph_2026_07_10`;
- `full_admin_service_surface_quality_audit_2026_07_08`;
- `osm_services_geometry_2026_07_05`;
- `osm_admin_mobility_crosswalk_2026_07_06`;
- available administrative boundary geometry.

Current evidence scale:

- 1,017 administrative units;
- 50,332 road records in the accessibility foundation;
- approximately 58,888 km road-length proxy;
- service POIs and essential-service categories;
- nearest-service distance and network travel-time proxies;
- quality-audit and negative-control artifacts.

These counts are product observations, not authoritative statements about the complete municipal road or service inventory.

## 5. Product Channels

Each required channel has one of three statuses:

```text
implemented
proxy_only
unavailable
```

### 5.1 Implemented Channels

- service facility inventory available in the bound artifacts;
- administrative service-accessibility surface;
- nearest essential-service distance where present;
- road and service coverage map layers;
- administrative accessibility-gap ranking;
- evidence and source trace;
- explicit production blockers.

### 5.2 Proxy-Only Channels

- road-network travel-time proxy;
- walking-time proxy derived from supported network fields;
- road-network density and connectivity context;
- first/last-mile distance proxy;
- service convenience/accessibility score;
- connectivity-improvement review priority.

Every proxy output must carry:

```text
network_proxy_not_observed_walk_time=true
observed_trip_time=false
policy_outcome_claim=false
```

### 5.3 Unavailable Channels

- authoritative pedestrian-only network;
- cycling network and routes;
- transit stops, routes, schedules and frequency;
- shaded-route and tree-canopy path analysis;
- universal-accessibility routes, ramps, kerbs and barriers;
- parking supply, occupancy and pressure;
- pedestrian crossing inventory;
- crash, conflict and road-safety observations;
- comfort or safety-adjusted observed travel time.

Unavailable channels remain null and expose missing data. They must not receive zero scores.

## 6. Administrative Accessibility Contract

The product schema is `traditional_livability.mobility_accessibility.v1`.

Each administrative row includes:

```text
admin_unit_id
county
township
centroid
service_point_count
essential_service_count
nearest_essential_service_distance_m
nearest_essential_service_travel_time_min_proxy
road_segment_count
road_length_km_proxy
mean_road_speed_kmh_proxy
service_accessibility_score
accessibility_gap_rank
channel_status
source_trace
limitations
```

Only source fields that exist in the real product are populated. Missing values remain null. Ranking excludes rows without the required score and reports the excluded count.

## 7. Gap and Review-Priority Logic

The first release uses transparent descriptive ranking, not a hidden model.

The primary gap ordering is:

1. low service-accessibility score;
2. long nearest essential-service distance/time proxy;
3. zero or low essential-service count;
4. limited road-network context;
5. missing evidence requiring data collection.

The product may expose `review_priority`, but it must not label this as an engineering investment priority. Review-priority reasons are retained per row.

No arbitrary threshold is called authoritative. Quantile or relative rankings must be identified as product-relative diagnostics.

## 8. Connectivity Improvement Candidates

The product may produce a review list such as:

- verify missing pedestrian entrances;
- validate disconnected road/service geometry;
- inspect areas with long nearest-service proxies;
- collect transit, crossing, shade or accessibility data;
- evaluate whether service supply or network connection is the dominant gap.

These are investigation candidates, not approved road projects. The product cannot prescribe new links, budgets or expected time savings without engineering evidence.

## 9. Quality and Evidence Gate

The gate checks:

- accessibility surface schema and validation;
- mobility graph schema and node coverage;
- bundle and geography consistency;
- quality-audit readiness;
- required field availability;
- negative controls;
- source licensing/redistribution flags;
- channel-specific data readiness.

A valid product may be evidence-bounded and contain unavailable channels. Product validity means the claims match the evidence, not that the full customer requirement is complete.

## 10. Product Files

The real product directory contains:

```text
overview.json
admin_units.json
channel_readiness.json
map.json
```

All files share a deterministic bundle ID.

`overview.json` summarizes evidence, counts, claim boundary and implementation coverage.

`admin_units.json` stores canonical rows and rankings.

`channel_readiness.json` enumerates all demand-8 channels with implemented/proxy/unavailable status, evidence and blockers.

`map.json` contains administrative points/polygons where geometry exists and visually distinguishes relative accessibility gaps without implying observed walking time.

## 11. API

Endpoints:

```text
GET /api/uwm/traditional-livability/mobility/overview
GET /api/uwm/traditional-livability/mobility/admin-units
GET /api/uwm/traditional-livability/mobility/admin-units/{admin_unit_id}
GET /api/uwm/traditional-livability/mobility/map
```

The service is read-only and product-backed. It returns deep copies and rejects bundle mismatches. No LLM recomputes scores in the API layer.

## 12. Frontend

Add `需求8 · 出行、步行性与可达性` to the existing traditional-livability tab.

The panel displays:

- real product coverage and source period;
- implemented/proxy/unavailable channel counts;
- administrative accessibility-gap ranking;
- nearest-service and network proxy fields;
- proxy badges and claim boundary;
- unavailable data requirements;
- connectivity review candidates;
- map output.

The panel must not display:

- observed walking time unless supplied;
- transit coverage percentage without transit data;
- safe-route claims without safety data;
- universal-accessibility compliance;
- a fabricated composite walkability score.

## 13. Implementation Ledger Update

After real-product verification, demand 8 may move from `data_query_only` to `implemented_evidence_bounded`.

It must not move to `production_verified` for the complete customer requirement because transit, safety, shade, accessibility, parking and cycling channels remain unavailable.

Maximum supported claim:

```text
administrative_service_accessibility_and_network_proxy_gap_diagnostic
```

## 14. Verification

Tests cover:

- source-product validation;
- deterministic bundle and row ordering;
- null preservation;
- ranking exclusions;
- channel readiness completeness;
- absence of numeric values for unavailable channels;
- proxy labels on travel-time fields;
- quality-audit and negative-control binding;
- service deep-copy and bundle isolation;
- API authentication and lookup behavior;
- frontend prohibited claims;
- real Chongqing build and independent verification;
- zero fabricated values.

## 15. Acceptance Criteria

The product is accepted only if:

1. it binds the real 1,017-unit accessibility foundation;
2. source counts and proxy limitations are preserved;
3. all demand-8 channels appear in readiness output;
4. unavailable channels remain unavailable rather than scored zero;
5. the administrative gap ranking is transparent and reproducible;
6. connectivity outputs are review candidates, not approved projects;
7. APIs and frontend expose the same immutable evidence bundle;
8. an independent verifier reports zero fabricated values;
9. the AI demand implementation ledger is updated conservatively.

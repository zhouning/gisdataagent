# Traditional Mobility and Accessibility Demand 8 Chongqing Verification

Date: 2026-07-11

## Product Identity

- Product directory: `/private/tmp/traditional_mobility_accessibility_chongqing_real`
- Bundle ID: `traditional-mobility-c5a899c8e2313f4a82f6`
- Independent verification digest: `sha256:dec4087d384c85680c846ebbff015d166337c4f2dbc9757ae73e82f29ac3871d`
- Fabricated value count: 0
- Unavailable-channel numeric violations: 0

## Bound Evidence

The product binds the existing Chongqing full-admin service-accessibility surface, full-admin mobility graph and service-surface quality audit.

Observed product counts:

- administrative units: 1,017;
- mobility graph nodes: 1,017;
- mobility graph edges: 5,085;
- road records in the bound accessibility foundation: 50,332;
- road-length proxy: 58,887.996598 km;
- ranked administrative units: 1,017;
- ranking exclusions: 0.

These are counts from the bound proxy products and are not claimed to be an authoritative complete municipal road or facility inventory.

## Demand-8 Channel Readiness

Implemented channels: 3

- service inventory in the bound artifacts;
- administrative accessibility surface;
- nearest-service distance.

Proxy-only channels: 4

- road-network travel time;
- walking time;
- first/last-mile distance;
- road connectivity.

Unavailable channels: 7

- cycling routes;
- public transport;
- shaded routes;
- universal accessibility;
- parking pressure;
- pedestrian crossings;
- road safety.

Unavailable channels contain no numeric value. No zero score is used to represent missing evidence.

## Ranking Method

All 1,017 units have a service-accessibility score in the bound surface. The relative diagnostic ordering uses:

1. service-accessibility score ascending;
2. nearest essential-service distance proxy descending;
3. stable administrative-unit ID ordering.

No authoritative threshold is used. The output is not an engineering investment priority.

The first five review-ranked units in this product are:

1. `巫溪县|红池坝经济开发区|876`;
2. `酉阳土家族苗族自治县|楠木乡|66`;
3. `巫溪县|中岗乡|543`;
4. `彭水苗族土家族自治县|岩东乡|999`;
5. `巫溪县|长桂乡|475`.

These rows are review candidates based on relative proxy gaps. They are not approved connectivity projects and do not imply authoritative service deficiency without local verification.

## Claim Boundary

- `network_proxy_not_observed_walk_time=true`
- `observed_trip_time=false`
- `policy_outcome_claim=false`
- `complete_demand8_fulfillment=false`
- maximum supported claim: `administrative_service_accessibility_and_network_proxy_gap_diagnostic`

The product does not claim safe routes, transit coverage, cycling accessibility, shade comfort, universal-accessibility compliance, parking pressure, observed time savings or road-safety improvement.

## Verification Conclusion

The demand-8 traditional GIS product is valid as an evidence-bounded administrative service-accessibility and road-network proxy diagnostic. It supports a real product page and map, but it does not fully satisfy the complete customer demand until transit, safety, shade, universal-accessibility, parking, cycling and crossing datasets are supplied and verified.

# UWM Environmental Dynamics Kernel Chongqing Verification

Date: 2026-07-11

## Product

- Product directory: `/private/tmp/uwm_environmental_kernel_chongqing_real`
- Bundle ID: `uwm-environmental-kernel-6904dcdeaa7bb8187e58`
- Scene period: 2024-07-01 to 2024-07-07
- State snapshot digest: `sha256:d9dcb7f99479e459157831011558242034c251961afae219adfa1ffd3e2c50bf`
- Independent verification digest: `sha256:bff156490755da8082f23814bfe7bb6c6dd6962d205c084de9ba83db25ab2053`

## Real Evidence Bound

The product binds the following existing Chongqing data identifiers:

- `chongqing_township_admin_units_local`
- `gee_cams_nrt_chongqing_proxy`
- `gee_era5_hourly_chongqing_proxy`
- `openaq_air_quality_station_observation_proxy`
- `openmeteo_air_quality_historical_point_proxy`
- `openmeteo_weather_historical_point_proxy`
- `tap_pm25_observed_gridded_chongqing_2018_2024`

The state contains 36 administrative environmental nodes and 96 verified administrative boundary-adjacency edges. All 36 nodes have a scene PM2.5 value and scene temperature value in the bound multisource scene. The product does not invent vegetation fraction, intervention area, action-effect coefficient or policy outcome.

## Kernel Readiness

- PM2.5 temporal dynamics: `observed_calibrated`
- PM2.5 temporal calibration artifact: `tap_pm25_external_dynamics_2026_07_06`
- Temperature temporal calibration: `unavailable`
- Vegetation temporal calibration: `unavailable`
- Green-action PM2.5 response: `unavailable`
- Green-action temperature response: `unavailable`
- Green-action vegetation response: `unavailable`
- PM2.5, temperature and vegetation spatial intervention propagation: `unavailable`

The TAP result supports an external PM2.5 temporal-dynamics claim only. Its spatial negative control did not pass, and it is not intervention-outcome evidence. It is therefore not promoted into a green-infrastructure action-response or spatial-policy-effect coefficient.

## Current Product Behavior

The product provides:

- a real versioned environmental state;
- a verified administrative spatial graph;
- an evidence gate separating temporal, direct-action and spatial mechanisms;
- a closed current intervention rollout;
- a map payload for the observed state;
- an immutable bundle ID and state digest.

The current rollout has:

- `intervention_status=action_response_closed`
- `not_a_causal_effect_estimate=true`
- `fabricated_value_count=0`

This is an intentional fail-closed production result. It is not a demo failure: the state and temporal PM2.5 evidence are real and executable, while unsupported green-action outcomes remain closed until intervention-response evidence is supplied.

## Production Blockers

- `pm25_action_response_unavailable`
- `pm25_spatial_propagation_unavailable`
- `temperature_action_response_unavailable`
- `temperature_spatial_propagation_unavailable`
- `temperature_temporal_calibration_unavailable`
- `vegetation_action_response_unavailable`
- `vegetation_spatial_propagation_unavailable`
- `vegetation_temporal_calibration_unavailable`

## Verification Conclusion

The real Chongqing product passed independent bundle, causal-boundary and fabricated-value checks. Its maximum current claim is `observed_environmental_state` plus separately identified calibrated PM2.5 external temporal dynamics. It does not claim that a green intervention lowers temperature, PM2.5, health risk or policy cost.

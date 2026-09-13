# UWM TAP External Dynamics Calibration Design

Date: 2026-07-06

## Purpose

Move UWM one step closer to a real world-model system by using local TAP gridded PM2.5 data as an external temporal dynamics holdout.

The previous TAP slice proved a bounded claim:

```text
tap_gridded_temporal_state_prediction_advantage_over_static_baseline
```

That was a real-data state-prediction benchmark, but it did not yet test whether UWM's spatial world-model structure adds value beyond a non-spatial online updater. This slice adds that missing proof.

## Non-Goals

This slice will not:

- claim real policy intervention outcome superiority;
- train or evaluate a planner on observed policy outcomes;
- infer causal effects of greening, traffic control, or service interventions from TAP;
- aggregate TAP to administrative polygons;
- redistribute raw TAP zip contents.

All outputs must keep:

```text
empirical_superiority_claim = false
observed_policy_outcome_superiority_claim = false
```

The strongest allowed claim is:

```text
tap_external_spatiotemporal_dynamics_advantage_over_static_and_non_spatial_baselines
```

only if the real-data holdout supports it.

## Data Inputs

Primary input:

```text
/Users/zhouning/Downloads/tap_uwm
```

Existing parsed artifacts:

```text
data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06/tap_pm25_proxy.json
data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06/tap_gridded_temporal_benchmark.json
data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06/snapshot_manifest.json
```

Relevant observed facts:

- 1 km TAP PM2.5 rows: 9,451,218.
- Valid 1 km TAP PM2.5 rows: 9,422,882.
- 10 km species rows: 23,746.
- Existing sampled temporal benchmark: 10,000 grid series / 40,000 holdout points.
- Existing best UWM dynamic updater MAE: 7.01169.
- Existing best static baseline MAE: 9.309192.
- Existing MAE reduction: 2.297502.

## World-Model Framing

UWM must keep the renderer / simulator / planner boundary intact:

```text
external observed gridded state
-> state encoder
-> action-free exogenous dynamics model for air pollution
-> external holdout evaluation
-> evidence gate
```

Because TAP contains observed gridded PM2.5 state but no intervention action labels, this module is an external dynamics validation module, not a policy simulator and not a planner evaluator.

The model is action-free:

```text
state_t -> state_t+1
```

It validates whether spatial context and temporal updating improve prediction of the next PM2.5 state compared with traditional baselines.

## Model Families

The benchmark will compare four families.

### Traditional Static Baselines

1. `static_train_mean`: each grid cell predicts its train-window mean.
2. `static_last_train_observation`: each grid cell predicts the last train observation for every holdout day.
3. `period_static_mean`: each holdout prediction uses the period-level train mean.
4. `tile_static_mean`: each grid cell uses its tile-level train mean.

These are traditional static state baselines.

### Non-Spatial Dynamic Baselines

1. `online_persistence_state_update`: predicts the next state from the prior observation of the same grid cell.
2. `adaptive_online_state_update`: exponential online update using only the same grid cell history.

These baselines are dynamic but not spatial. They are important because the previous TAP benchmark already showed dynamic online state update is strong. A spatial world model must beat this family or transparently say it does not.

### Spatial Message World Model

The UWM external dynamics model will use deterministic spatial message features:

- target grid previous PM2.5;
- target train mean;
- tile train mean;
- local neighbor mean from same-day previous observations;
- local neighbor median if enough neighbors exist;
- target-minus-neighbor contrast;
- tile/day anomaly;
- period/year indicator;
- day-of-window index.

The first implementation should use a small ridge model or closed-form linear model. This is intentional: the claim should come from spatial structure and strict holdout evaluation, not an opaque model.

### Negative Controls

The report must include at least:

1. `neighbor_shuffle_control`: keep target series fixed but assign neighbor messages from deterministic mismatched grid cells.
2. `temporal_order_rotation_control`: rotate holdout order to test dependence on temporal ordering.
3. `future_label_leakage_guard`: assert no feature for prediction at day t uses PM2.5 from day t or later for the same target.

If the spatial model beats baselines but also beats the negative controls only weakly, the claim must be downgraded.

## Sampling and Runtime

The TAP 1 km source is large, so the module should stream zip CSVs and build sampled series deterministically.

Default runtime sample:

```text
max_grid_series_per_period = 5000
neighbor_sample_radius_mode = tile_gridid_adjacency_proxy_v1
train_days = 3
```

The implementation can initially infer local neighbors within each TAP tile from sorted GridID order as a deterministic adjacency proxy. This is not a physical distance graph. It must be named as a proxy and reported as a limitation.

If lon/lat values are available from the tile lonlat joins, the implementation should prefer a bounded nearest-neighbor lookup within the sampled tile rows. The design allows the first implementation to use either:

- `lonlat_nearest_neighbors_v1`, preferred if runtime is acceptable;
- `tile_gridid_adjacency_proxy_v1`, acceptable with explicit limitation.

## Output Artifact

Create:

```text
data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/
  tap_external_dynamics_report.json
  snapshot_manifest.json
```

Expected schema:

```text
uwm.tap_external_spatiotemporal_dynamics_report.v1
```

Required top-level fields:

- `schema`
- `model_id`
- `created_at`
- `source_dataset_ids`
- `sampling_config`
- `feature_schema`
- `training_summary`
- `baseline_results`
- `spatial_world_model_results`
- `negative_control_results`
- `overall_results`
- `supported_claim`
- `claim_boundary`
- `limitations`
- `empirical_superiority_claim`
- `observed_policy_outcome_superiority_claim`

## Success Criteria

The module supports `tap_external_spatiotemporal_dynamics_advantage_over_static_and_non_spatial_baselines` only when all are true:

1. Spatial world model MAE is lower than every traditional static baseline MAE.
2. Spatial world model MAE is lower than every non-spatial dynamic baseline MAE.
3. Spatial model has positive paired win rate over the best non-spatial dynamic baseline.
4. The deterministic neighbor shuffle control is worse than the real spatial model.
5. The report explicitly sets policy outcome superiority claims to false.

If criteria 1-2 hold but 3-4 fail, downgrade to:

```text
tap_external_temporal_dynamics_advantage_without_spatial_claim
```

If criteria 1-2 fail, use:

```text
no_tap_external_dynamics_advantage_claim_supported
```

## Evidence Boundary

Allowed:

- real TAP gridded temporal state prediction advantage;
- bounded external dynamics validation;
- spatial message model advantage if holdout and negative controls support it;
- comparison against static and non-spatial dynamic baselines.

Not allowed:

- station-observed validation;
- policy intervention effect validation;
- real planner superiority;
- health outcome or livability outcome superiority.

## Test Strategy

Use TDD.

Initial tests should create tiny TAP-like zip fixtures with known spatial patterns:

1. A spatial diffusion fixture where neighbor messages improve next-day prediction over non-spatial online persistence.
2. A no-spatial-signal fixture where spatial claim is downgraded.
3. A claim-guard test ensuring both policy superiority flags remain false.
4. A leakage test ensuring holdout-day labels are not present in features.

Then run against real TAP data and verify:

```text
uv run python -m pytest data_agent/test_uwm_tap_external_dynamics.py -q
uv run python scripts/build_uwm_tap_external_dynamics.py --tap-root /Users/zhouning/Downloads/tap_uwm --output-dir data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06 --max-grid-series-per-period 5000
uv run python -m pytest data_agent/test_uwm_*.py -q
```

## Integration Points

New files:

- `data_agent/uwm/tap_external_dynamics.py`
- `data_agent/test_uwm_tap_external_dynamics.py`
- `scripts/build_uwm_tap_external_dynamics.py`

Report updates after artifact generation:

- `docs/reports/uwm_data_foundation_manifest.csv`
- `docs/reports/uwm_data_foundation_manifest.md`
- `docs/reports/uwm_data_foundation_coverage_audit.md`
- `docs/reports/uwm_data_foundation_summary_2026-07-05.md`
- `docs/reports/uwm_track2_research_log.md`

## Risks and Mitigations

Risk: spatial nearest-neighbor computation is too slow for full TAP rows.

Mitigation: deterministic sampling and tile-local neighbor indexing; stream CSVs; keep raw TAP out of git.

Risk: spatial model does not beat non-spatial dynamic baseline.

Mitigation: report the failure honestly and downgrade the claim. This is still useful evidence because it prevents overclaiming.

Risk: GridID adjacency proxy is not geographically exact.

Mitigation: prefer lon/lat nearest neighbors when feasible; otherwise name the proxy explicitly and keep claim bounded.

Risk: accidental policy-outcome overclaim.

Mitigation: hard-coded validation checks and tests for `empirical_superiority_claim=false`, `observed_policy_outcome_superiority_claim=false`, and `not_policy_intervention_outcome` limitation.


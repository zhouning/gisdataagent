# UWM TAP Observed Gridded Benchmark Design

Date: 2026-07-06

## Purpose

This design adds real TAP PM2.5 data to the UWM data foundation and uses it to create a reproducible temporal-state benchmark. The goal is to replace part of the current TAP-like semi-synthetic scaffold with an observed gridded air-pollution product and prove a bounded world-model claim:

```text
On TAP gridded daily PM2.5 time series, a UWM online temporal state update
beats traditional static baselines for temporal state prediction.
```

This design does not claim policy intervention superiority. TAP is a multisource gridded retrieval/fusion product, not a station-observed policy outcome holdout.

## Inputs

Primary local source:

```text
/Users/zhouning/Downloads/tap_uwm
```

The package contains:

- `chongqing_pm25_2024_07_01_07`: TAP 1 km daily PM2.5, 2024-07-01 to 2024-07-07, 6 tiles, 42 PM2.5 CSV zip files, 6 lon/lat tile CSV zip files.
- `chongqing_pm25_2018_10_17_23`: TAP 1 km daily PM2.5, 2018-10-17 to 2018-10-23, 6 tiles, 42 PM2.5 CSV zip files, 6 lon/lat tile CSV zip files.
- `d07f3d.zip`: TAP 10 km daily PM2.5 and species for 2024-07-01 to 2024-07-31, with `PM2.5`, `SO4`, `NO3`, `NH4`, `OM`, and `BC`.

Known parsed facts from the local package:

- The 1 km PM2.5 files join cleanly to tile lon/lat files by `GridID`.
- The 1 km extent is approximately `103.001-111.999E, 26.7042-32.6958N`.
- This extent fully covers the existing 1017 Chongqing township/street UWM admin units.
- 2024 1 km daily PM2.5 has about 4.71 million valid grid-day values and mean PM2.5 near `9.22 ug/m3`.
- 2018 1 km daily PM2.5 has about 4.71 million valid grid-day values and mean PM2.5 near `21.00 ug/m3`.
- The 10 km species package covers 2024-07 daily PM2.5 and composition fields.

## Architecture

The implementation will add a narrow TAP observed-data path that follows the existing UWM data discipline:

```text
TAP local zips
-> TAP proxy parser
-> normalized UWM TAP proxy snapshot
-> TAP temporal benchmark
-> manifest/report updates
-> evidence-gated claim boundary
```

This is deliberately separate from `tap_like_air_quality_scene.py`. The TAP-like module remains a semi-synthetic scaffold. The new TAP path represents real TAP gridded product data and must not inherit TAP-like synthetic flags.

## Components

### `data_agent/uwm/tap_pm25_proxy.py`

Responsibility:

- Parse TAP 1 km PM2.5 tile zips.
- Parse TAP tile lon/lat zips.
- Join PM2.5 rows to coordinates by `GridID`.
- Parse TAP 10 km PM2.5 species package.
- Produce compact summaries and benchmark-ready temporal series.
- Validate output schema and claim boundaries.

Primary public functions:

```python
TAP_PM25_PROXY_SCHEMA = "uwm.tap_pm25_proxy.v1"

def build_tap_pm25_proxy(
    *,
    tap_root: str | Path,
    proxy_id: str,
    created_at: str,
    include_records: bool = False,
    max_records_per_period: int | None = None,
) -> dict[str, Any]:
    ...

def validate_tap_pm25_proxy(payload: dict[str, Any]) -> dict[str, Any]:
    ...
```

Default output should be summary-oriented to avoid writing millions of rows into JSON. Full raw TAP zips remain the source files; benchmark code can stream from zips or consume a sampled panel.

Required proxy payload fields:

- `schema`
- `proxy_id`
- `created_at`
- `source_dataset_ids`
- `source_root`
- `periods_1km`
- `species_10km`
- `record_counts`
- `coverage`
- `summary`
- `synthetic_flags`
- `claim_boundary`
- `limitations`
- `empirical_superiority_claim`

Claim policy:

```text
synthetic_status: public_proxy
claim_boundary.max_claim_level: bounded_support
empirical_superiority_claim: false
limitations include not_station_observation and not_policy_intervention_outcome
```

### `data_agent/uwm/tap_temporal_benchmark.py`

Responsibility:

- Build a temporal state prediction benchmark from TAP daily grid time series.
- Compare UWM online state updates to traditional static baselines.
- Report sign tests and a temporal-order negative control.
- Keep policy-outcome superiority explicitly false.

Primary public functions:

```python
TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA = "uwm.tap_gridded_temporal_benchmark.v1"

def build_tap_gridded_temporal_benchmark(
    *,
    tap_root: str | Path,
    benchmark_id: str,
    created_at: str,
    train_days: int = 3,
    max_grid_series_per_period: int = 5000,
) -> dict[str, Any]:
    ...

def validate_tap_gridded_temporal_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    ...
```

Benchmark unit:

```text
period x tile x GridID daily PM2.5 sequence
```

The initial benchmark will use a deterministic sampled subset to stay fast and reproducible. Sampling must be stable by sorted `(period, tile_id, grid_id)` order and capped by `max_grid_series_per_period`.

Traditional baseline suite:

- `static_train_mean`: the mean of training days.
- `static_last_train_observation`: the last training-day value.
- `period_static_mean`: the period-level training mean across sampled grids.

UWM temporal state update suite:

- `online_persistence_state_update`: predicts the next holdout day from the previous observed day.
- `adaptive_online_state_update`: predicts with a convex update from prior state and train mean. The default alpha is fixed at `0.7` and documented in the payload.

The benchmark must not use current or future holdout labels for the same prediction. It can use prior holdout observations only after they would have been observed online.

Required benchmark fields:

- `schema`
- `benchmark_id`
- `created_at`
- `source_dataset_ids`
- `traditional_baseline_suite`
- `uwm_state_update_suite`
- `period_results`
- `overall_results`
- `overall_sign_tests`
- `temporal_order_negative_control_summary`
- `supported_claim`
- `claim_boundary`
- `limitations`
- `empirical_superiority_claim`

Claim policy:

```text
supported_claim: tap_gridded_temporal_state_prediction_advantage_over_static_baseline
claim_boundary.max_claim_level: bounded_support when UWM update beats all static baselines
empirical_superiority_claim: false
observed_policy_outcome_superiority_claim: false
```

### `scripts/build_uwm_tap_pm25_proxy.py`

Responsibility:

- Run the parser and benchmark on the local TAP package.
- Write UWM-ready artifacts under:

```text
data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06/
```

Expected files:

- `tap_pm25_proxy.json`
- `tap_gridded_temporal_benchmark.json`
- `snapshot_manifest.json`

The script must print a compact JSON summary containing output paths, record counts, benchmark MAE values, win rates, claim boundary, and limitations.

### Manifest and Report Updates

The existing manifest row:

```text
tap_pm25_china_access_pending
```

will no longer be the only TAP status. The implementation should add a new manifest row:

```text
tap_pm25_observed_gridded_chongqing_2018_2024
```

This row should use existing manifest enums:

```text
source_type: public
access_status: available
synthetic_status: public_proxy
claim_boundary: bounded_support
quality_status: tap_gridded_fusion_product_not_station_or_policy_outcome
license: TAP_noncommercial_terms_no_redistribution
used_by: air_pollution_exposure;uwm_air;state_dynamics_validation;mmfe_alignment;evidence_gate
```

The pending row may remain for history if its lineage states that TAP data was later obtained in this local package. It must not be counted as the active TAP evidence row after the new row is added.

Reports to update:

- `docs/reports/uwm_data_foundation_manifest.csv`
- `docs/reports/uwm_data_foundation_manifest.md`
- `docs/reports/uwm_data_foundation_coverage_audit.md`
- `docs/reports/uwm_data_foundation_summary_2026-07-05.md`

Report wording must distinguish three claims:

1. TAP gridded PM2.5 is available and improves air-pollution exposure data foundation.
2. TAP gridded temporal benchmark can support bounded temporal state-prediction advantage over static baselines if the benchmark passes.
3. TAP does not support observed policy intervention outcome superiority.

## Data Flow

1. The script receives `--tap-root /Users/zhouning/Downloads/tap_uwm`.
2. The proxy parser discovers period directories and known random zips.
3. For each 1 km period:
   - read all `Tile_*_lonlat.csv.zip` files;
   - build a per-tile `GridID -> lon, lat` map;
   - stream each `China_PM25_1km_YYYY_DOY_TILE.csv.zip`;
   - validate the lon/lat join;
   - compute period summaries and a deterministic sampled grid-day panel.
4. For the 10 km species zip:
   - parse all daily species CSV files;
   - compute full-month and first-week summaries.
5. The benchmark consumes deterministic sampled 1 km grid sequences.
6. The script writes JSON artifacts and snapshot manifest.
7. Tests validate schema, joins, benchmark math, and claim boundaries.

## Error Handling

Parser errors should fail closed:

- Missing TAP root: raise `FileNotFoundError`.
- No 1 km period directories: raise `ValueError`.
- Missing lon/lat tile for a PM2.5 tile: raise `ValueError`.
- Missing `GridID` or `PM2.5` columns in PM2.5 CSV: raise `ValueError`.
- Missing `GridID`, `Longitude`, or `Latitude` columns in lon/lat CSV: raise `ValueError`.
- Any nonzero GridID join miss count in production mode: raise `ValueError`.
- Empty benchmark holdout: raise `ValueError`.

Validation errors should return structured `{valid: False, errors: [...]}` rather than raising.

## Testing

New tests:

```text
data_agent/test_uwm_tap_pm25_proxy.py
data_agent/test_uwm_tap_gridded_temporal_benchmark.py
```

Test requirements:

- Fixture zip construction uses temporary directories and the standard `zipfile` module.
- `test_tap_pm25_proxy_joins_gridid_to_lonlat_and_summarizes_periods`
  validates a minimal 1 km TAP fixture with two tiles and two days.
- `test_tap_pm25_proxy_parses_species_zip`
  validates PM2.5 and species summaries from 10 km fixture CSVs.
- `test_tap_benchmark_online_state_update_beats_static_baselines`
  validates MAE reduction, win rate, and sign test on a constructed sequence.
- `test_tap_benchmark_keeps_policy_outcome_claim_false`
  validates `empirical_superiority_claim is False` and `observed_policy_outcome_superiority_claim is False`.
- Existing UWM tests must remain green:

```text
uv run python -m pytest data_agent/test_uwm_*.py -q
```

## Non-Goals

- Do not build full polygon zonal statistics in this slice.
- Do not train or modify planner policy from TAP in this slice.
- Do not claim station-observed validation from TAP.
- Do not claim observed policy intervention superiority.
- Do not redistribute raw TAP data into repo-tracked files.
- Do not add new dependencies unless an existing project dependency cannot safely read the required CSV zip formats.

## Follow-Up Slice

After this slice passes, the next development slice should be TAP admin aggregation:

```text
TAP 1 km grid -> Chongqing admin units -> admin-day PM2.5 panel
-> scene state update -> planner/evidence gate refresh
```

That later slice can update the livability intervention package to use real TAP gridded PM2.5 instead of TAP-like PM2.5 v2, while still keeping the policy-outcome gate closed.

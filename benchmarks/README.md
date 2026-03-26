# GIS Data Agent — Benchmark Suite

## Overview

Synthetic benchmark datasets for performance testing and regression validation.

## Data Generation

```bash
python benchmarks/generate_benchmark_data.py
```

Generates 6 GeoJSON files in `benchmarks/data/`:

| Dataset | Features | Description |
|---------|----------|-------------|
| parcels_small_clean | 100 | Small clean dataset |
| parcels_small_dirty | 100 | Small dataset with quality issues |
| parcels_medium_clean | 1,000 | Medium clean dataset |
| parcels_medium_dirty | 1,000 | Medium with quality issues |
| parcels_large_clean | 10,000 | Large clean dataset |
| parcels_large_dirty | 10,000 | Large with quality issues |

### Attributes

Each parcel has: `parcel_id`, `land_type` (0-4), `land_name`, `slope`, `area_m2`,
`elevation`, `pop_density`, `soil_quality`, `distance_to_road`, `geometry`.

### Quality Issues (dirty datasets)

- Missing `land_name` values (~2.5% of rows)
- Invalid `slope` values (-999) (~1.7% of rows)
- Duplicate geometries (3 per dataset)

## Running Benchmarks

```bash
python benchmarks/run_benchmarks.py
```

Measures:
- **Data loading**: GeoJSON read time per scale
- **Spatial operations**: Buffer, dissolve, spatial join
- **Quality checking**: Null detection, duplicate geometry, invalid value detection

Results saved to `benchmarks/benchmark_results.json`.

## Baseline Performance (reference)

| Operation | Small (100) | Medium (1K) | Large (10K) |
|-----------|-------------|-------------|-------------|
| Load | <0.1s | ~0.3s | ~2s |
| Buffer | <0.01s | ~0.05s | ~0.5s |
| Dissolve | <0.01s | ~0.1s | ~1s |

# TWM Demo Data Quality Report

## Gate Status

- Status: `pass`
- Blockers: 0
- Warnings: 2

### Blockers

- None

### Warnings

- parcel_current: 5 features exceed 10% area mismatch
- real_imagery_manifest.json missing; using synthetic raster fixture fallback

## Layer Quality

| Layer | Rows | Geometry | Invalid | Empty | Area m2 |
|---|---:|---|---:|---:|---:|
| parcel_current | 2217 | MultiPolygon, Polygon | 0 | 0 | 12816662.463 |
| synthetic_pbf | 274 | MultiPolygon, Polygon | 0 | 0 | 5377897.719 |
| synthetic_eco_redline | 1 | MultiPolygon | 0 | 0 | 1335483.975 |
| admin_units | 2 | Polygon | 0 | 0 | 12741883.554 |
| synthetic_annual_change | 260 | MultiPolygon, Polygon | 0 | 0 | 1098728.503 |
| synthetic_projects | 36 | MultiPolygon, Polygon | 0 | 0 | 392828.693 |
| synthetic_planning_zones | 2457 | MultiPolygon, Polygon | 0 | 0 | 12816649.989 |
| synthetic_urban_boundary | 194 | MultiPolygon, Polygon | 0 | 0 | 12816649.952 |
| synthetic_remote_sensing_tiles | 12 | Polygon | 0 | 0 | 33830231.641 |

## Parcel Continuity

```json
{
  "connected_components": 1,
  "largest_component_features": 2217,
  "largest_component_ratio": 1.0
}
```

## Admin Coverage

```json
{
  "has_admin9": true,
  "unique_admin9": 2,
  "admin9_counts": {
    "500227104": 2216,
    "500227105": 1
  }
}
```

## Parcel Area Consistency

```json
{
  "compared": 2217,
  "median_abs_rel_error": 0.000311,
  "p95_abs_rel_error": 0.000336,
  "max_abs_rel_error": 3.0,
  "count_gt_5pct": 5,
  "count_gt_10pct": 5
}
```

## Overlay Semantics

| Overlay | Positive intersections | Unique left | Unique right | Mean left ratio | Full-cover hits |
|---|---:|---:|---:|---:|---:|
| project_pbf | 39 | 22 | 28 | 0.303361 | 11 |
| project_eco | 2 | 2 | 1 | 0.999364 | 2 |
| project_planning | 36 | 36 | 36 | 1.0 | 36 |
| pbf_eco | 11 | 11 | 1 | 0.35885 | 3 |

## Relation Tables

| Relation | Rows | Unique projects |
|---|---:|---:|
| change_parcel_rel | 507 | 0 |
| project_eco_rel | 2 | 2 |
| project_parcel_rel | 110 | 36 |
| project_pbf_rel | 39 | 22 |
| project_planning_rel | 36 | 36 |
| project_rs_tile_rel | 43 | 36 |
| project_urban_boundary_rel | 36 | 36 |

## Governance Tables

| Table | Rows | Unique projects |
|---|---:|---:|
| approval_records | 36 | 36 |
| enforcement_events | 24 | 22 |
| metadata_vector | 10 | 0 |
| multimodal_evidence_index | 53 | 0 |
| review_tasks | 24 | 22 |
| rule_evaluation | 108 | 36 |
| standard_field_catalog | 130 | 0 |
| state_snapshots | 11 | 0 |

## One Map Standard Contracts

Contract: `data_agent/test_data/twm_one_map_village_standard_sample/standards/one_map_role_contracts.zh.json`

| Role | Target | Rows | Required fields | Missing | Empty required |
|---|---|---:|---:|---|---|
| parcel_current | parcel_current | 2217 | 14/14 |  | {} |
| pbf | synthetic_pbf | 274 | 19/19 |  | {} |
| eco_redline | synthetic_eco_redline | 1 | 12/12 |  | {} |
| urban_boundary | synthetic_urban_boundary | 194 | 11/11 |  | {} |
| planning_zone | synthetic_planning_zones | 2457 | 7/7 |  | {} |
| project | synthetic_projects | 36 | 8/8 |  | {} |
| approval | approval_records | 36 | 8/8 |  | {} |
| enforcement | enforcement_events | 24 | 15/15 |  | {} |
| metadata_vector | metadata_vector | 10 | 12/12 |  | {} |

## Raster Fixtures

| Raster | Size | CRS | Valid pixels | Mean |
|---|---:|---|---:|---:|
| synthetic_ndvi_2026 | 256x256 | EPSG:4523 | 22604 | 0.66006 |
| synthetic_change_intensity_2026 | 256x256 | EPSG:4523 | 22604 | 0.093399 |

## Real Imagery

```json
{
  "missing_real_imagery_manifest": true,
  "stac": null,
  "target_grid": null
}
```

| Product | Size | Bands | CRS | First-band valid pixels | First-band mean |
|---|---:|---:|---|---:|---:|


## Optimization Dataset

```json
{
  "exists": true,
  "counts": {
    "objectives": 13,
    "scenarios": 7,
    "feasibility_rows": 7,
    "memberships": 100,
    "metrics": 91,
    "violations": 19
  },
  "pareto": {
    "method": "hard_constraint_filter_then_normalized_weighted_score_and_non_dominated_sorting",
    "comparison_scope": "legal_feasible_space",
    "objective_count": 13,
    "scenario_count": 7,
    "legal_feasible_scenario_count": 1,
    "blocked_scenario_count": 6,
    "ranked_count": 1,
    "blocked_count": 6
  }
}
```

## Domain Integrity

```json
{
  "checks": {
    "rule_evaluation_project_coverage": {
      "expected_projects": 36,
      "covered_projects": 36,
      "missing_projects": []
    },
    "approval_records_project_coverage": {
      "expected_projects": 36,
      "covered_projects": 36,
      "missing_projects": []
    },
    "rule_hits": {
      "hit_requires_review": 24,
      "rows": 108
    },
    "enforcement_review_chain": {
      "enforcement_events": 24,
      "reviewed_events": 24,
      "missing_review": []
    },
    "state_snapshot_years": [
      2020,
      2035
    ],
    "standard_field_catalog": {
      "rows": 130,
      "deprecated_fields": 1
    },
    "project_text_evidence_coverage": {
      "expected_projects": 36,
      "covered_projects": 36,
      "missing_projects": []
    },
    "raster_observation_evidence": {
      "rows": 2,
      "linked_products": [
        "RASTER-CHANGE-2026",
        "RASTER-NDVI-2026"
      ]
    }
  },
  "warnings": [],
  "blockers": []
}
```

## Dictionary Coverage

```json
{
  "missing_dictionary": false,
  "missing_layer_aliases": [],
  "unknown_fields": {}
}
```

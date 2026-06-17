# TWM Demo Data Quality Report

## Gate Status

- Status: `pass`
- Blockers: 0
- Warnings: 1

### Blockers

- None

### Warnings

- parcel_current: 121 features exceed 10% area mismatch

## Layer Quality

| Layer | Rows | Geometry | Invalid | Empty | Area m2 |
|---|---:|---|---:|---:|---:|
| parcel_current | 21218 | MultiPolygon, Polygon | 0 | 0 | 236067608.513 |
| synthetic_pbf | 14 | Polygon | 0 | 0 | 16344189.542 |
| synthetic_eco_redline | 10 | Polygon | 0 | 0 | 12078792.802 |
| admin_units | 11 | Polygon | 0 | 0 | 720457848.126 |
| synthetic_annual_change | 266 | Polygon | 0 | 0 | 4014391.728 |
| synthetic_projects | 90 | MultiPolygon, Polygon | 0 | 0 | 6859702.069 |
| synthetic_planning_zones | 5 | MultiPolygon | 0 | 0 | 229304900.003 |
| synthetic_urban_boundary | 5 | Polygon | 0 | 0 | 3830462.603 |
| synthetic_remote_sensing_tiles | 10 | MultiPolygon, Polygon | 0 | 0 | 236067634.606 |

## Parcel Continuity

```json
{
  "connected_components": 5,
  "largest_component_features": 21203,
  "largest_component_ratio": 0.9993
}
```

## Admin Coverage

```json
{
  "has_admin9": true,
  "unique_admin9": 3,
  "admin9_counts": {
    "500227100": 4900,
    "500227101": 5443,
    "500227102": 10875
  }
}
```

## Parcel Area Consistency

```json
{
  "compared": 21218,
  "median_abs_rel_error": 0.000436,
  "p95_abs_rel_error": 0.000481,
  "max_abs_rel_error": 0.999953,
  "count_gt_5pct": 138,
  "count_gt_10pct": 121
}
```

## Overlay Semantics

| Overlay | Positive intersections | Unique left | Unique right | Mean left ratio | Full-cover hits |
|---|---:|---:|---:|---:|---:|
| project_pbf | 35 | 35 | 14 | 0.662549 | 12 |
| project_eco | 33 | 33 | 10 | 0.792326 | 17 |
| project_planning | 264 | 90 | 5 | 0.338333 | 26 |
| pbf_eco | 1 | 1 | 1 | 9e-06 | 0 |

## Relation Tables

| Relation | Rows | Unique projects |
|---|---:|---:|
| change_parcel_rel | 266 | 0 |
| project_eco_rel | 33 | 33 |
| project_parcel_rel | 1093 | 90 |
| project_pbf_rel | 35 | 35 |
| project_planning_rel | 264 | 90 |
| project_rs_tile_rel | 93 | 90 |
| project_urban_boundary_rel | 13 | 13 |

## Governance Tables

| Table | Rows | Unique projects |
|---|---:|---:|
| approval_records | 90 | 90 |
| enforcement_events | 114 | 68 |
| metadata_vector | 9 | 0 |
| multimodal_evidence_index | 224 | 0 |
| review_tasks | 114 | 68 |
| rule_evaluation | 360 | 90 |
| standard_field_catalog | 267 | 0 |
| state_snapshots | 10 | 0 |

## One Map Standard Contracts

Contract: `data_agent/test_data/twm_bishan_multi_admin_eval/standards/one_map_role_contracts.zh.json`

| Role | Target | Rows | Required fields | Missing | Empty required |
|---|---|---:|---:|---|---|
| parcel_current | parcel_current | 21218 | 14/14 |  | {} |
| pbf | synthetic_pbf | 14 | 19/19 |  | {} |
| eco_redline | synthetic_eco_redline | 10 | 12/12 |  | {} |
| urban_boundary | synthetic_urban_boundary | 5 | 11/11 |  | {} |
| planning_zone | synthetic_planning_zones | 5 | 7/7 |  | {} |
| project | synthetic_projects | 90 | 8/8 |  | {} |
| approval | approval_records | 90 | 8/8 |  | {} |
| enforcement | enforcement_events | 114 | 15/15 |  | {} |
| metadata_vector | metadata_vector | 9 | 12/12 |  | {} |

## Raster Fixtures

| Raster | Size | CRS | Valid pixels | Mean |
|---|---:|---|---:|---:|
| synthetic_ndvi_2026 | 384x384 | EPSG:32648 | 64753 | 0.583423 |
| synthetic_change_intensity_2026 | 384x384 | EPSG:32648 | 64753 | 0.058148 |

## Real Imagery

```json
{
  "missing_real_imagery_manifest": false,
  "stac": {
    "endpoint": "https://earth-search.aws.element84.com/v1",
    "collection": "sentinel-2-l2a",
    "datetime": "2025-01-01T00:00:00Z/2025-12-31T23:59:59Z",
    "cloud_cover_max": 20.0,
    "matched_items": 50,
    "selected_date": "2025-08-03",
    "coverage_ratio_estimate": 1.0,
    "avg_cloud_cover": 0.087723,
    "selected_items": [
      {
        "id": "S2C_48RXU_20250803_0_L2A",
        "datetime": "2025-08-03T03:50:03.848000Z",
        "cloud_cover": 0.05672,
        "grid": "MGRS-48RXU",
        "bbox": [
          106.034119,
          29.735248,
          106.775827,
          30.728858
        ]
      },
      {
        "id": "S2C_48RXT_20250803_0_L2A",
        "datetime": "2025-08-03T03:50:17.836000Z",
        "cloud_cover": 0.118727,
        "grid": "MGRS-48RXT",
        "bbox": [
          106.025066,
          28.835798,
          106.516331,
          29.826404
        ]
      }
    ]
  },
  "target_grid": {
    "crs": "EPSG:32648",
    "resolution_m": 60.0,
    "product_set": "core",
    "width": 349,
    "height": 410,
    "transform": [
      59.982993079,
      0.0,
      611330.165779103,
      0.0,
      -59.979386289,
      3307087.679765264
    ]
  }
}
```

| Product | Size | Bands | CRS | First-band valid pixels | First-band mean |
|---|---:|---:|---|---:|---:|
| sentinel2_l2a_reflectance_stack | 349x410 | 4 | EPSG:32648 | 143090 | -0.054532 |
| sentinel2_l2a_rgb | 349x410 | 3 | EPSG:32648 | 139668 | 73.73233 |
| sentinel2_l2a_ndvi | 349x410 | 1 | EPSG:32648 | 11739 | 0.64549 |
| sentinel2_l2a_scl | 349x410 | 1 | EPSG:32648 | 143090 | 4.105458 |

## Optimization Dataset

```json
{
  "exists": true,
  "counts": {
    "objectives": 13,
    "scenarios": 7,
    "feasibility_rows": 7,
    "memberships": 134,
    "metrics": 91,
    "violations": 16
  },
  "pareto": {
    "method": "hard_constraint_filter_then_normalized_weighted_score_and_non_dominated_sorting",
    "comparison_scope": "legal_feasible_space",
    "objective_count": 13,
    "scenario_count": 7,
    "legal_feasible_scenario_count": 3,
    "blocked_scenario_count": 4,
    "ranked_count": 3,
    "blocked_count": 4
  }
}
```

## Domain Integrity

```json
{
  "checks": {
    "rule_evaluation_project_coverage": {
      "expected_projects": 90,
      "covered_projects": 90,
      "missing_projects": []
    },
    "approval_records_project_coverage": {
      "expected_projects": 90,
      "covered_projects": 90,
      "missing_projects": []
    },
    "rule_hits": {
      "hit_requires_review": 114,
      "rows": 360
    },
    "enforcement_review_chain": {
      "enforcement_events": 114,
      "reviewed_events": 114,
      "missing_review": []
    },
    "state_snapshot_years": [
      2025,
      2026
    ],
    "standard_field_catalog": {
      "rows": 267,
      "deprecated_fields": 1
    },
    "project_text_evidence_coverage": {
      "expected_projects": 90,
      "covered_projects": 90,
      "missing_projects": []
    },
    "raster_observation_evidence": {
      "rows": 2,
      "linked_products": [
        "RASTER-CHANGE-2026",
        "RASTER-NDVI-2026"
      ]
    },
    "observed_remote_sensing_evidence": {
      "expected_products": 4,
      "rows": 4,
      "linked_products": [
        "REAL-S2-L2A-NDVI",
        "REAL-S2-L2A-REFLECTANCE",
        "REAL-S2-L2A-RGB",
        "REAL-S2-L2A-SCL"
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

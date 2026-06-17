# TWM Demo Data Quality Report

## Gate Status

- Status: `pass`
- Blockers: 0
- Warnings: 1

### Blockers

- None

### Warnings

- parcel_current: 59 features exceed 10% area mismatch

## Layer Quality

| Layer | Rows | Geometry | Invalid | Empty | Area m2 |
|---|---:|---|---:|---:|---:|
| parcel_current | 4900 | MultiPolygon, Polygon | 0 | 0 | 63629824.312 |
| synthetic_pbf | 14 | Polygon | 0 | 0 | 23275420.423 |
| synthetic_eco_redline | 10 | Polygon | 0 | 0 | 19866857.796 |
| admin_units | 5 | Polygon | 0 | 0 | 330784536.588 |
| synthetic_annual_change | 78 | Polygon | 0 | 0 | 1405899.77 |
| synthetic_projects | 60 | MultiPolygon, Polygon | 0 | 0 | 2340404.353 |
| synthetic_planning_zones | 5 | MultiPolygon | 0 | 0 | 60443629.555 |
| synthetic_urban_boundary | 5 | Polygon | 0 | 0 | 850358.743 |
| synthetic_remote_sensing_tiles | 11 | MultiPolygon, Polygon | 0 | 0 | 63629982.916 |

## Parcel Continuity

```json
{
  "connected_components": 6,
  "largest_component_features": 4893,
  "largest_component_ratio": 0.9986
}
```

## Admin Coverage

```json
{
  "has_admin9": true,
  "unique_admin9": 1,
  "admin9_counts": {
    "500227100": 4900
  }
}
```

## Parcel Area Consistency

```json
{
  "compared": 4900,
  "median_abs_rel_error": 0.000407,
  "p95_abs_rel_error": 0.000432,
  "max_abs_rel_error": 0.999953,
  "count_gt_5pct": 64,
  "count_gt_10pct": 59
}
```

## Overlay Semantics

| Overlay | Positive intersections | Unique left | Unique right | Mean left ratio | Full-cover hits |
|---|---:|---:|---:|---:|---:|
| project_pbf | 39 | 34 | 14 | 0.483445 | 8 |
| project_eco | 28 | 28 | 10 | 0.76613 | 12 |
| project_planning | 151 | 60 | 5 | 0.38462 | 12 |
| pbf_eco | 9 | 8 | 5 | 0.20444 | 0 |

## Relation Tables

| Relation | Rows | Unique projects |
|---|---:|---:|
| change_parcel_rel | 78 | 0 |
| project_eco_rel | 28 | 28 |
| project_parcel_rel | 354 | 60 |
| project_pbf_rel | 39 | 34 |
| project_planning_rel | 151 | 60 |
| project_rs_tile_rel | 71 | 60 |
| project_urban_boundary_rel | 7 | 7 |

## Governance Tables

| Table | Rows | Unique projects |
|---|---:|---:|
| approval_records | 60 | 60 |
| enforcement_events | 92 | 51 |
| metadata_vector | 9 | 0 |
| multimodal_evidence_index | 173 | 0 |
| review_tasks | 92 | 51 |
| rule_evaluation | 240 | 60 |
| standard_field_catalog | 267 | 0 |
| state_snapshots | 10 | 0 |

## One Map Standard Contracts

Contract: `data_agent/test_data/twm_bishan_demo/standards/one_map_role_contracts.zh.json`

| Role | Target | Rows | Required fields | Missing | Empty required |
|---|---|---:|---:|---|---|
| parcel_current | parcel_current | 4900 | 14/14 |  | {} |
| pbf | synthetic_pbf | 14 | 19/19 |  | {} |
| eco_redline | synthetic_eco_redline | 10 | 12/12 |  | {} |
| urban_boundary | synthetic_urban_boundary | 5 | 11/11 |  | {} |
| planning_zone | synthetic_planning_zones | 5 | 7/7 |  | {} |
| project | synthetic_projects | 60 | 8/8 |  | {} |
| approval | approval_records | 60 | 8/8 |  | {} |
| enforcement | enforcement_events | 92 | 15/15 |  | {} |
| metadata_vector | metadata_vector | 9 | 12/12 |  | {} |

## Raster Fixtures

| Raster | Size | CRS | Valid pixels | Mean |
|---|---:|---|---:|---:|
| synthetic_ndvi_2026 | 256x256 | EPSG:32648 | 27078 | 0.628087 |
| synthetic_change_intensity_2026 | 256x256 | EPSG:32648 | 27078 | 0.060754 |

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
    "width": 197,
    "height": 214,
    "transform": [
      59.789326377,
      0.0,
      620485.733067192,
      0.0,
      -59.768899144,
      3307087.679765264
    ]
  }
}
```

| Product | Size | Bands | CRS | First-band valid pixels | First-band mean |
|---|---:|---:|---|---:|---:|
| sentinel2_l2a_reflectance_stack | 197x214 | 4 | EPSG:32648 | 42158 | -0.057872 |
| sentinel2_l2a_rgb | 197x214 | 3 | EPSG:32648 | 41195 | 89.426848 |
| sentinel2_l2a_ndvi | 197x214 | 1 | EPSG:32648 | 1828 | 0.774765 |
| sentinel2_l2a_scl | 197x214 | 1 | EPSG:32648 | 42158 | 4.057996 |

## Optimization Dataset

```json
{
  "exists": true,
  "counts": {
    "objectives": 13,
    "scenarios": 7,
    "feasibility_rows": 7,
    "memberships": 91,
    "metrics": 91,
    "violations": 18
  },
  "pareto": {
    "method": "hard_constraint_filter_then_normalized_weighted_score_and_non_dominated_sorting",
    "comparison_scope": "legal_feasible_space",
    "objective_count": 13,
    "scenario_count": 7,
    "legal_feasible_scenario_count": 2,
    "blocked_scenario_count": 5,
    "ranked_count": 2,
    "blocked_count": 5
  }
}
```

## Domain Integrity

```json
{
  "checks": {
    "rule_evaluation_project_coverage": {
      "expected_projects": 60,
      "covered_projects": 60,
      "missing_projects": []
    },
    "approval_records_project_coverage": {
      "expected_projects": 60,
      "covered_projects": 60,
      "missing_projects": []
    },
    "rule_hits": {
      "hit_requires_review": 92,
      "rows": 240
    },
    "enforcement_review_chain": {
      "enforcement_events": 92,
      "reviewed_events": 92,
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
      "expected_projects": 60,
      "covered_projects": 60,
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

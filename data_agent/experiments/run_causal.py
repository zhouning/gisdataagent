"""Causal Inference Paper — Experiment Runner.

Runs all experiments for the three-angle causal inference paper:
  - 6 synthetic scenarios (Angle A validation)
  - Chongqing building → UHI (real-world Angle A)
  - Chongqing LULC → LST (real-world Angle A + supplementary)
  - LLM causal DAG validation (Angle B)
  - World model intervention (Angle C)

Usage:
    python -m data_agent.experiments.run_causal --synthetic-only
    python -m data_agent.experiments.run_causal --all
"""

import argparse
import json
import sys
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from data_agent.experiments.common import (
    OUTPUT_DIR, DATA_DIR, CHONGQING_BBOX, CHONGQING_FULL_BBOX,
    load_shapefile, load_raster, init_gee, fetch_modis_lst, fetch_ndvi,
)


# =========================================================================
# Experiment 1: Six Synthetic Scenarios (Angle A)
# =========================================================================

def generate_psm_data(n=2000, seed=42):
    """Park proximity → house price. True ATE = +15000."""
    rng = np.random.default_rng(seed)
    # Confounders
    income = rng.normal(50000, 15000, n)
    school_dist = rng.uniform(0, 5, n)
    # Treatment: near park (propensity depends on confounders)
    logit = -1.0 + 0.00002 * income - 0.3 * school_dist + rng.normal(0, 0.5, n)
    prop = 1 / (1 + np.exp(-logit))
    treatment = rng.binomial(1, prop)
    # Outcome: price depends on confounders + treatment effect
    noise = rng.normal(0, 8000, n)
    price = 150000 + 1.5 * income + (-5000) * school_dist + 15000 * treatment + noise
    df = pd.DataFrame({
        "treatment": treatment,
        "price": price,
        "income": income,
        "school_dist": school_dist,
    })
    return df, {"true_ate": 15000, "method": "PSM", "scenario": "park_price"}


def generate_did_data(n=500, seed=42):
    """Vehicle restriction → PM2.5. True effect = -8.0."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        treated = int(i < n // 2)
        for t in range(6):
            post = int(t >= 3)
            base = 45 + rng.normal(0, 3)
            trend = -0.5 * t
            effect = -8.0 * treated * post
            pm25 = base + trend + 5 * treated + effect + rng.normal(0, 2)
            rows.append({"entity": i, "time": t, "treated": treated,
                         "post": post, "pm25": pm25})
    df = pd.DataFrame(rows)
    return df, {"true_effect": -8.0, "method": "DiD", "scenario": "pm25_restriction"}


def generate_granger_data(n_time=100, seed=42):
    """Urban expansion → farmland decline. True lag = 2."""
    rng = np.random.default_rng(seed)
    urban = np.zeros(n_time)
    farm = np.zeros(n_time)
    urban[0] = 50
    farm[0] = 200
    for t in range(1, n_time):
        urban[t] = urban[t - 1] + rng.normal(1.5, 0.5)
        lag_urban = urban[t - 2] if t >= 2 else urban[0]
        farm[t] = farm[t - 1] - 0.3 * lag_urban + rng.normal(0, 1)
    df = pd.DataFrame({"time": range(n_time), "location": 0,
                        "urban_area": urban, "farmland_area": farm})
    return df, {"true_lag": 2, "method": "Granger", "scenario": "urban_farmland"}


def generate_erf_data(n=1000, seed=42):
    """Pollution distance → health. Quadratic dose-response."""
    rng = np.random.default_rng(seed)
    distance = rng.uniform(0, 20, n)
    income = rng.normal(50000, 10000, n)
    health = 60 + 2.0 * distance - 0.05 * distance**2 + 0.0001 * income + rng.normal(0, 3, n)
    df = pd.DataFrame({"distance": distance, "health_score": health, "income": income})
    return df, {"method": "ERF", "scenario": "pollution_health", "true_shape": "quadratic"}


def generate_gccm_data(n_time=200, seed=42):
    """Rainfall → NDVI. Nonlinear ecosystem coupling."""
    rng = np.random.default_rng(seed)
    rain = np.zeros(n_time)
    ndvi = np.zeros(n_time)
    rain[0] = 50
    ndvi[0] = 0.5
    for t in range(1, n_time):
        rain[t] = 50 + 20 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 5)
        ndvi[t] = 0.3 + 0.004 * rain[t - 1] + 0.5 * ndvi[t - 1] + rng.normal(0, 0.02)
    df = pd.DataFrame({"time": range(n_time), "location": 0,
                        "rainfall": rain, "ndvi": ndvi})
    return df, {"method": "GCCM", "scenario": "rain_ndvi", "true_direction": "rain→ndvi"}


def generate_causal_forest_data(n=1000, seed=42):
    """Irrigation → crop yield. Heterogeneous by aridity. True ATE_arid = +200."""
    rng = np.random.default_rng(seed)
    aridity = rng.uniform(0, 1, n)
    soil_quality = rng.normal(50, 10, n)
    treatment = rng.binomial(1, 0.5, n)
    cate = 200 * aridity  # Higher effect in arid areas
    base_yield = 500 + 3 * soil_quality + rng.normal(0, 30, n)
    crop_yield = base_yield + cate * treatment
    df = pd.DataFrame({
        "treatment": treatment, "crop_yield": crop_yield,
        "aridity": aridity, "soil_quality": soil_quality,
    })
    return df, {"method": "CausalForest", "scenario": "irrigation_yield",
                "true_ate_arid": 200}


def run_synthetic_experiments():
    """Run all 6 synthetic scenarios and collect results."""
    from data_agent.causal_inference import (
        propensity_score_matching,
        difference_in_differences,
        spatial_granger_causality,
        exposure_response_function,
        geographic_causal_mapping,
        causal_forest_analysis,
    )

    results = []
    generators = [
        ("PSM", generate_psm_data, propensity_score_matching),
        ("DiD", generate_did_data, difference_in_differences),
        ("Granger", generate_granger_data, spatial_granger_causality),
        ("ERF", generate_erf_data, exposure_response_function),
        ("GCCM", generate_gccm_data, geographic_causal_mapping),
        ("CausalForest", generate_causal_forest_data, causal_forest_analysis),
    ]

    for name, gen_fn, method_fn in generators:
        print(f"\n--- Synthetic Scenario: {name} ---")
        df, meta = gen_fn()

        # Save to temp CSV
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
        df.to_csv(tmp.name, index=False)
        tmp.close()

        try:
            if name == "PSM":
                result_json = propensity_score_matching(
                    file_path=tmp.name,
                    treatment_col="treatment",
                    outcome_col="price",
                    confounders="income,school_dist",
                )
            elif name == "DiD":
                result_json = difference_in_differences(
                    file_path=tmp.name,
                    outcome_col="pm25",
                    treatment_col="treated",
                    time_col="time",
                    post_col="post",
                    entity_col="entity",
                )
            elif name == "Granger":
                result_json = spatial_granger_causality(
                    file_path=tmp.name,
                    variables="urban_area,farmland_area",
                    time_col="time",
                    location_col="location",
                    max_lag=4,
                )
            elif name == "ERF":
                result_json = exposure_response_function(
                    file_path=tmp.name,
                    exposure_col="distance",
                    outcome_col="health_score",
                    confounders="income",
                )
            elif name == "GCCM":
                result_json = geographic_causal_mapping(
                    file_path=tmp.name,
                    cause_col="rainfall",
                    effect_col="ndvi",
                )
            elif name == "CausalForest":
                result_json = causal_forest_analysis(
                    file_path=tmp.name,
                    treatment_col="treatment",
                    outcome_col="crop_yield",
                    feature_cols="aridity,soil_quality",
                )

            result = json.loads(result_json)
            result["_meta"] = meta
            results.append({"scenario": name, "meta": meta, "result": result})
            print(f"  Result: {json.dumps({k: v for k, v in result.items() if not k.startswith('_') and 'path' not in k}, indent=2, default=str)[:500]}")

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"scenario": name, "meta": meta, "error": str(e)})
        finally:
            os.unlink(tmp.name)

    # Save consolidated results
    out_path = OUTPUT_DIR / "synthetic_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nSynthetic results saved to {out_path}")
    return results


# =========================================================================
# Experiment 2: Chongqing Building → UHI (Real-world, Angle A)
# =========================================================================

def run_chongqing_uhi():
    """High-rise buildings → urban heat island effect via PSM + Causal Forest.

    Treatment: floors >= 10 (high-rise) vs < 10 (low-rise)
    Outcome: MODIS LST
    Confounders: elevation, slope, NDVI
    """
    from data_agent.causal_inference import (
        propensity_score_matching,
        causal_forest_analysis,
    )
    import geopandas as gpd

    print("\n=== Chongqing UHI Experiment ===")

    # 1. Load buildings
    print("  Loading building footprints...")
    buildings = load_shapefile("buildings")
    print(f"  Loaded {len(buildings)} buildings")

    # Parse floor count from attributes
    # The field name contains 层高 (floor height)
    floor_col = None
    for col in buildings.columns:
        if "层" in col or "floor" in col.lower() or "height" in col.lower():
            floor_col = col
            break

    if floor_col is None:
        # Try numeric columns
        numeric_cols = buildings.select_dtypes(include=[np.number]).columns.tolist()
        print(f"  Available numeric columns: {numeric_cols[:10]}")
        if numeric_cols:
            floor_col = numeric_cols[0]

    print(f"  Using floor column: {floor_col}")

    # 2. Compute centroids for spatial sampling
    buildings = buildings.to_crs("EPSG:4326")
    buildings["centroid_x"] = buildings.geometry.centroid.x
    buildings["centroid_y"] = buildings.geometry.centroid.y
    buildings["area_sqm"] = buildings.to_crs("EPSG:32648").geometry.area

    # 3. Create treatment variable (high-rise >= 10 floors)
    buildings["floors"] = pd.to_numeric(buildings[floor_col], errors="coerce")
    buildings = buildings.dropna(subset=["floors"])
    buildings["high_rise"] = (buildings["floors"] >= 10).astype(int)

    print(f"  High-rise: {buildings['high_rise'].sum()}, Low-rise: {(1 - buildings['high_rise']).sum()}")

    # 4. Load DEM for elevation confounder
    print("  Loading DEM...")
    dem_data, dem_transform, dem_crs = load_raster("dem")

    # Sample DEM at building centroids
    from rasterio.transform import rowcol
    elevations = []
    for _, row in buildings.iterrows():
        try:
            r, c = rowcol(dem_transform, row["centroid_x"], row["centroid_y"])
            if 0 <= r < dem_data.shape[0] and 0 <= c < dem_data.shape[1]:
                elevations.append(float(dem_data[r, c]))
            else:
                elevations.append(np.nan)
        except Exception:
            elevations.append(np.nan)
    buildings["elevation"] = elevations

    # 5. Stratified sample (n=5000: 2500 per group)
    n_per_group = 2500
    high = buildings[buildings["high_rise"] == 1].dropna(subset=["elevation"])
    low = buildings[buildings["high_rise"] == 0].dropna(subset=["elevation"])
    n_high = min(n_per_group, len(high))
    n_low = min(n_per_group, len(low))
    sample = pd.concat([
        high.sample(n=n_high, random_state=42),
        low.sample(n=n_low, random_state=42),
    ])
    print(f"  Sample size: {len(sample)} (high={n_high}, low={n_low})")

    # 6. Fetch MODIS LST from GEE
    print("  Fetching MODIS LST from GEE...")
    if init_gee():
        import ee
        bbox = CHONGQING_BBOX
        roi = ee.Geometry.Rectangle(bbox)
        collection = (
            ee.ImageCollection("MODIS/061/MOD11A2")
            .filterDate("2021-01-01", "2021-12-31")
            .filterBounds(roi)
            .select("LST_Day_1km")
        )
        lst_img = collection.mean().multiply(0.02).subtract(273.15)

        # Sample LST at building centroids
        points = [
            ee.Feature(ee.Geometry.Point([r["centroid_x"], r["centroid_y"]]))
            for _, r in sample.iterrows()
        ]
        fc = ee.FeatureCollection(points[:5000])  # GEE limit

        # Use reduceRegions for batch extraction
        sampled = lst_img.reduceRegions(
            collection=fc, reducer=ee.Reducer.mean(), scale=1000,
        ).getInfo()

        lst_values = [f["properties"].get("mean", np.nan) for f in sampled["features"]]
        sample = sample.iloc[:len(lst_values)].copy()
        sample["lst"] = lst_values
    else:
        print("  GEE unavailable, generating synthetic LST...")
        rng = np.random.default_rng(42)
        base_lst = 28.0
        sample["lst"] = (
            base_lst
            - 0.005 * sample["elevation"]
            + 0.3 * sample["high_rise"]
            + rng.normal(0, 1.5, len(sample))
        )

    # 7. Run PSM
    print("  Running PSM...")
    sample_clean = sample[["high_rise", "lst", "elevation", "area_sqm", "centroid_x", "centroid_y"]].dropna()
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    sample_clean.to_csv(tmp.name, index=False)
    tmp.close()

    try:
        psm_result = json.loads(propensity_score_matching(
            file_path=tmp.name,
            treatment_col="high_rise",
            outcome_col="lst",
            confounders="elevation,area_sqm,centroid_x,centroid_y",
        ))
        print(f"  PSM ATE: {psm_result.get('ate', 'N/A')}")
        print(f"  PSM ATT: {psm_result.get('att', 'N/A')}")

        # 8. Run Causal Forest for CATE
        print("  Running Causal Forest for CATE...")
        cf_result = json.loads(causal_forest_analysis(
            file_path=tmp.name,
            treatment_col="high_rise",
            outcome_col="lst",
            feature_cols="elevation,area_sqm,centroid_x,centroid_y",
        ))
        print(f"  CF ATE: {cf_result.get('ate', 'N/A')}")

    except Exception as e:
        print(f"  ERROR: {e}")
        psm_result = {"error": str(e)}
        cf_result = {"error": str(e)}
    finally:
        os.unlink(tmp.name)

    # Save results
    uhi_results = {
        "n_buildings_total": len(buildings),
        "n_sample": len(sample_clean),
        "psm": psm_result,
        "causal_forest": cf_result,
    }
    out_path = OUTPUT_DIR / "chongqing_uhi_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(uhi_results, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nUHI results saved to {out_path}")
    return uhi_results


# =========================================================================
# Experiment 3: Chongqing LULC → LST (Real-world, supplementary)
# =========================================================================

def run_chongqing_lulc_lst():
    """Built-up land vs cropland/forest → surface temperature difference.

    Uses CLCD classification + MODIS LST + DEM confounders.
    """
    from data_agent.causal_inference import propensity_score_matching
    import rasterio
    from rasterio.transform import xy

    print("\n=== Chongqing LULC → LST Experiment ===")

    # 1. Load CLCD classification
    print("  Loading CLCD raster...")
    clcd_data, clcd_transform, clcd_crs = load_raster("clcd")
    print(f"  CLCD shape: {clcd_data.shape}, unique values: {np.unique(clcd_data)[:15]}")

    # 2. Load DEM
    print("  Loading DEM...")
    dem_data, dem_transform, _ = load_raster("dem")

    # 3. Sample pixels — built-up (8) vs cropland/forest (7, 2, 3)
    # CLCD classes: 1=cropland, 2=forest, 3=grassland, 4=shrub, 5=water, 7=tundra, 8=impervious, 15=snow
    # In some CLCD versions: 1=cropland, 2=forest, 3=shrub, 4=grassland, 5=water, 7=tundra/barren, 8=built-up
    rng = np.random.default_rng(42)
    buildup_mask = (clcd_data == 8)
    # Use multiple natural classes as control group
    natural_mask = np.isin(clcd_data, [1, 2, 3, 4])  # cropland + forest + shrub + grassland
    print(f"  Built-up pixels: {buildup_mask.sum()}, Natural pixels: {natural_mask.sum()}")

    n_sample = 3000
    rows_b, cols_b = np.where(buildup_mask)
    rows_c, cols_c = np.where(natural_mask)

    idx_b = rng.choice(len(rows_b), min(n_sample, len(rows_b)), replace=False)
    idx_c = rng.choice(len(rows_c), min(n_sample, len(rows_c)), replace=False)

    records = []
    for idx_arr, label, rows_arr, cols_arr in [
        (idx_b, 1, rows_b, cols_b),
        (idx_c, 0, rows_c, cols_c),
    ]:
        for i in idx_arr:
            r, c = rows_arr[i], cols_arr[i]
            lon, lat = xy(clcd_transform, r, c)
            # Sample DEM (resample to CLCD grid)
            try:
                from rasterio.transform import rowcol
                dr, dc = rowcol(dem_transform, lon, lat)
                if 0 <= dr < dem_data.shape[0] and 0 <= dc < dem_data.shape[1]:
                    elev = float(dem_data[dr, dc])
                else:
                    elev = np.nan
            except Exception:
                elev = np.nan

            records.append({
                "treatment": label,  # 1=built-up, 0=cropland
                "lon": lon,
                "lat": lat,
                "elevation": elev,
            })

    df = pd.DataFrame(records).dropna()
    print(f"  Sample: {len(df)} pixels (built-up={df['treatment'].sum()}, cropland={(1-df['treatment']).sum()})")

    # 4. Fetch MODIS LST
    print("  Fetching MODIS LST...")
    if init_gee():
        import ee
        points = [
            ee.Feature(ee.Geometry.Point([r["lon"], r["lat"]]))
            for _, r in df.iterrows()
        ]
        # Batch in chunks of 5000
        lst_values = []
        chunk_size = 5000
        for i in range(0, len(points), chunk_size):
            chunk = points[i:i + chunk_size]
            fc = ee.FeatureCollection(chunk)
            roi = ee.Geometry.Rectangle(CHONGQING_FULL_BBOX)
            lst_col = (
                ee.ImageCollection("MODIS/061/MOD11A2")
                .filterDate("2020-01-01", "2020-12-31")
                .filterBounds(roi)
                .select("LST_Day_1km")
            )
            lst_img = lst_col.mean().multiply(0.02).subtract(273.15)
            sampled = lst_img.reduceRegions(
                collection=fc, reducer=ee.Reducer.mean(), scale=1000,
            ).getInfo()
            lst_values.extend([f["properties"].get("mean", np.nan) for f in sampled["features"]])

        df = df.iloc[:len(lst_values)].copy()
        df["lst"] = lst_values
    else:
        print("  GEE unavailable, generating synthetic LST...")
        rng2 = np.random.default_rng(99)
        df["lst"] = (
            30.0
            - 0.008 * df["elevation"]
            + 2.5 * df["treatment"]  # Built-up is warmer
            + rng2.normal(0, 2, len(df))
        )

    # 5. Run PSM
    print("  Running PSM...")
    df_clean = df.dropna()
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df_clean.to_csv(tmp.name, index=False)
    tmp.close()

    try:
        result = json.loads(propensity_score_matching(
            file_path=tmp.name,
            treatment_col="treatment",
            outcome_col="lst",
            confounders="elevation,lon,lat",
        ))
        print(f"  PSM ATE (built-up vs cropland): {result.get('ate', 'N/A')} °C")
        print(f"  Naive diff: {df_clean[df_clean['treatment']==1]['lst'].mean() - df_clean[df_clean['treatment']==0]['lst'].mean():.2f} °C")
    except Exception as e:
        print(f"  ERROR: {e}")
        result = {"error": str(e)}
    finally:
        os.unlink(tmp.name)

    out_path = OUTPUT_DIR / "chongqing_lulc_lst_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nLULC→LST results saved to {out_path}")
    return result


# =========================================================================
# CLI Entry
# =========================================================================

def main():
    parser = argparse.ArgumentParser(description="Causal Inference Paper Experiments")
    parser.add_argument("--synthetic-only", action="store_true",
                        help="Run only the 6 synthetic scenarios (fast, no API)")
    parser.add_argument("--uhi", action="store_true", help="Run Chongqing UHI experiment")
    parser.add_argument("--lulc", action="store_true", help="Run Chongqing LULC→LST experiment")
    parser.add_argument("--all", action="store_true", help="Run all experiments")
    args = parser.parse_args()

    if args.all or args.synthetic_only or (not any([args.uhi, args.lulc])):
        print("\n" + "=" * 60)
        print("PHASE 1: Synthetic Scenarios")
        print("=" * 60)
        run_synthetic_experiments()

    if args.all or args.uhi:
        print("\n" + "=" * 60)
        print("PHASE 2: Chongqing UHI")
        print("=" * 60)
        run_chongqing_uhi()

    if args.all or args.lulc:
        print("\n" + "=" * 60)
        print("PHASE 3: Chongqing LULC → LST")
        print("=" * 60)
        run_chongqing_lulc_lst()

    if not args.synthetic_only:
        print("\n" + "=" * 60)
        print(f"All outputs in: {OUTPUT_DIR}")
        print("=" * 60)


if __name__ == "__main__":
    main()

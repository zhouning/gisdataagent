"""Generate synthetic benchmark datasets for GIS Data Agent.

Creates Shapefiles at 3 scales (100/1000/10000 parcels) with realistic
attributes for DRL optimization and spatial analysis benchmarking.

Usage:
    python benchmarks/generate_benchmark_data.py [output_dir]
"""

import os
import sys
import time
import numpy as np

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generate_grid_parcels(n_parcels: int, seed: int = 42) -> "gpd.GeoDataFrame":
    """Generate a grid of square parcels with realistic attributes.

    Args:
        n_parcels: Target number of parcels (actual may differ due to grid rounding)
        seed: Random seed for reproducibility
    """
    import geopandas as gpd
    from shapely.geometry import box

    rng = np.random.default_rng(seed)

    # Grid dimensions
    cols = int(np.ceil(np.sqrt(n_parcels)))
    rows = int(np.ceil(n_parcels / cols))
    actual = min(rows * cols, n_parcels)

    # Base coordinates (Wuhan area)
    base_lon, base_lat = 114.3, 30.5
    cell_size = 0.005  # ~500m

    geometries = []
    for i in range(actual):
        r, c = divmod(i, cols)
        x0 = base_lon + c * cell_size
        y0 = base_lat + r * cell_size
        geometries.append(box(x0, y0, x0 + cell_size, y0 + cell_size))

    # Land use types: 0=farmland, 1=forest, 2=built-up, 3=water, 4=grassland
    land_types = rng.choice([0, 1, 2, 3, 4], actual, p=[0.4, 0.25, 0.2, 0.1, 0.05])

    # Slope: varies by type (built-up tends flat, forest steeper)
    base_slope = rng.uniform(0, 35, actual)
    type_slope_factor = {0: 0.5, 1: 1.2, 2: 0.3, 3: 0.1, 4: 0.8}
    slopes = np.array([base_slope[i] * type_slope_factor[land_types[i]] for i in range(actual)])
    slopes = np.clip(slopes, 0, 45)

    # Area: slight variation around cell_size^2
    areas = rng.uniform(0.8, 1.2, actual) * (cell_size * 111000) ** 2  # m²

    # Population density: higher in built-up
    pop_density = rng.uniform(0, 100, actual)
    pop_density[land_types == 2] *= 10  # Built-up areas denser
    pop_density[land_types == 3] = 0     # No population on water

    # Elevation
    elevations = rng.uniform(20, 500, actual)
    elevations[land_types == 3] = rng.uniform(10, 30, (land_types == 3).sum())  # Water lower

    gdf = gpd.GeoDataFrame({
        "parcel_id": range(actual),
        "land_type": land_types,
        "land_name": [["farmland", "forest", "built_up", "water", "grassland"][t] for t in land_types],
        "slope": np.round(slopes, 2),
        "area_m2": np.round(areas, 1),
        "elevation": np.round(elevations, 1),
        "pop_density": np.round(pop_density, 1),
        "soil_quality": rng.uniform(0, 1, actual).round(3),
        "distance_to_road": rng.exponential(500, actual).round(1),
        "geometry": geometries,
    }, crs="EPSG:4326")

    return gdf


def generate_quality_issues(gdf: "gpd.GeoDataFrame", error_rate: float = 0.05, seed: int = 99):
    """Add realistic data quality issues for quality-check benchmarking."""
    import geopandas as gpd

    rng = np.random.default_rng(seed)
    gdf_dirty = gdf.copy()
    n = len(gdf_dirty)
    n_errors = int(n * error_rate)

    # Missing values
    idx = rng.choice(n, n_errors, replace=False)
    gdf_dirty.loc[gdf_dirty.index[idx[:n_errors//2]], "land_name"] = None

    # Out-of-range values
    idx2 = rng.choice(n, n_errors, replace=False)
    gdf_dirty.loc[gdf_dirty.index[idx2[:n_errors//3]], "slope"] = -999

    # Duplicate geometries
    if n > 5:
        dup_idx = rng.choice(n, min(3, n_errors), replace=False)
        for di in dup_idx:
            gdf_dirty.loc[gdf_dirty.index[di], "geometry"] = gdf_dirty.geometry.iloc[0]

    return gdf_dirty


def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(output_dir, exist_ok=True)

    scales = [
        ("small", 100),
        ("medium", 1000),
        ("large", 10000),
    ]

    print("=" * 50)
    print("GIS Data Agent — Benchmark Data Generator")
    print("=" * 50)

    for name, n in scales:
        t0 = time.time()
        print(f"\n[{name}] Generating {n} parcels...")

        gdf = generate_grid_parcels(n, seed=42 + n)

        # Clean dataset
        clean_path = os.path.join(output_dir, f"parcels_{name}_clean.geojson")
        gdf.to_file(clean_path, driver="GeoJSON")
        print(f"  Clean: {clean_path} ({len(gdf)} features)")

        # Dirty dataset (with quality issues)
        gdf_dirty = generate_quality_issues(gdf)
        dirty_path = os.path.join(output_dir, f"parcels_{name}_dirty.geojson")
        gdf_dirty.to_file(dirty_path, driver="GeoJSON")
        print(f"  Dirty: {dirty_path}")

        dt = time.time() - t0
        print(f"  Time: {dt:.1f}s")

    print(f"\nAll datasets saved to: {output_dir}")
    print("=" * 50)


if __name__ == "__main__":
    main()

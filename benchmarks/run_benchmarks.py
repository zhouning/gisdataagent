"""Run benchmark suite and report results.

Measures performance across different data scales and operations.

Usage:
    python benchmarks/run_benchmarks.py
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def benchmark_data_loading(data_dir: str) -> list:
    """Benchmark data loading performance."""
    results = []
    try:
        import geopandas as gpd
    except ImportError:
        print("  [SKIP] geopandas not available")
        return results

    for f in sorted(os.listdir(data_dir)):
        if not f.endswith("_clean.geojson"):
            continue
        path = os.path.join(data_dir, f)
        t0 = time.time()
        gdf = gpd.read_file(path)
        dt = time.time() - t0
        results.append({
            "operation": "load",
            "dataset": f,
            "features": len(gdf),
            "columns": len(gdf.columns),
            "duration_s": round(dt, 3),
        })
        print(f"  Load {f}: {len(gdf)} features in {dt:.3f}s")
    return results


def benchmark_spatial_operations(data_dir: str) -> list:
    """Benchmark spatial processing operations."""
    results = []
    try:
        import geopandas as gpd
    except ImportError:
        return results

    for scale in ["small", "medium"]:
        path = os.path.join(data_dir, f"parcels_{scale}_clean.geojson")
        if not os.path.exists(path):
            continue
        gdf = gpd.read_file(path)

        # Buffer operation
        t0 = time.time()
        _ = gdf.geometry.buffer(0.001)
        dt = time.time() - t0
        results.append({
            "operation": "buffer",
            "dataset": f"parcels_{scale}",
            "features": len(gdf),
            "duration_s": round(dt, 3),
        })
        print(f"  Buffer {scale}: {dt:.3f}s")

        # Dissolve by type
        t0 = time.time()
        _ = gdf.dissolve(by="land_type")
        dt = time.time() - t0
        results.append({
            "operation": "dissolve",
            "dataset": f"parcels_{scale}",
            "features": len(gdf),
            "duration_s": round(dt, 3),
        })
        print(f"  Dissolve {scale}: {dt:.3f}s")

        # Spatial join (self-join for neighbor detection)
        t0 = time.time()
        _ = gpd.sjoin(gdf.head(min(100, len(gdf))), gdf, how="inner", predicate="intersects")
        dt = time.time() - t0
        results.append({
            "operation": "spatial_join",
            "dataset": f"parcels_{scale}",
            "features": min(100, len(gdf)),
            "duration_s": round(dt, 3),
        })
        print(f"  Spatial join {scale}: {dt:.3f}s")

    return results


def benchmark_quality_check(data_dir: str) -> list:
    """Benchmark data quality checking."""
    results = []
    try:
        import geopandas as gpd
    except ImportError:
        return results

    for scale in ["small", "medium"]:
        path = os.path.join(data_dir, f"parcels_{scale}_dirty.geojson")
        if not os.path.exists(path):
            continue

        t0 = time.time()
        gdf = gpd.read_file(path)

        # Quality checks
        null_count = gdf.isnull().sum().sum()
        dup_geom = gdf.geometry.duplicated().sum()
        invalid_slope = (gdf["slope"] < 0).sum()

        dt = time.time() - t0
        results.append({
            "operation": "quality_check",
            "dataset": f"parcels_{scale}_dirty",
            "features": len(gdf),
            "null_values": int(null_count),
            "duplicate_geometries": int(dup_geom),
            "invalid_slopes": int(invalid_slope),
            "duration_s": round(dt, 3),
        })
        print(f"  Quality check {scale}: {null_count} nulls, {dup_geom} dup geoms, {invalid_slope} invalid slopes ({dt:.3f}s)")

    return results


def main():
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    output_file = os.path.join(os.path.dirname(__file__), "benchmark_results.json")

    if not os.path.exists(data_dir):
        print("Error: Benchmark data not found. Run generate_benchmark_data.py first.")
        sys.exit(1)

    print("=" * 50)
    print("GIS Data Agent — Benchmark Suite")
    print("=" * 50)

    all_results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "benchmarks": {},
    }

    print("\n[1/3] Data Loading Benchmarks:")
    all_results["benchmarks"]["loading"] = benchmark_data_loading(data_dir)

    print("\n[2/3] Spatial Operations Benchmarks:")
    all_results["benchmarks"]["spatial_ops"] = benchmark_spatial_operations(data_dir)

    print("\n[3/3] Quality Check Benchmarks:")
    all_results["benchmarks"]["quality_check"] = benchmark_quality_check(data_dir)

    # Save results
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {output_file}")

    # Summary
    total_ops = sum(len(v) for v in all_results["benchmarks"].values())
    print(f"\n{'=' * 50}")
    print(f"Completed {total_ops} benchmark operations")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()

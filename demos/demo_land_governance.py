#!/usr/bin/env python
"""
Demo: Land Governance Audit (土地治理审计)

Demonstrates the governance pipeline with land data quality audit:
1. Generate realistic dirty shapefile data
2. Run topology check (overlaps, self-intersections)
3. Field standardization audit
4. Generate governance report

Usage:
    python demos/demo_land_governance.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generate_sample_parcels(output_path: str) -> str:
    """Generate sample parcel shapefile with intentional quality issues."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Polygon, MultiPolygon

    np.random.seed(42)
    n = 30

    # Generate base grid parcels
    parcels = []
    for i in range(6):
        for j in range(5):
            x0 = 116.3 + i * 0.005
            y0 = 39.9 + j * 0.004
            w = 0.004 + np.random.uniform(-0.001, 0.001)
            h = 0.003 + np.random.uniform(-0.001, 0.001)
            poly = Polygon([
                (x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)
            ])
            parcels.append(poly)

    # Inject quality issues
    # Issue 1: Overlap (parcel 5 overlaps with parcel 6)
    coords = list(parcels[5].exterior.coords)
    coords[1] = (coords[1][0] + 0.003, coords[1][1])  # extend right
    parcels[5] = Polygon(coords)

    # Issue 2: Self-intersection (parcel 10 — bowtie)
    x0, y0 = 116.31, 39.92
    parcels[10] = Polygon([
        (x0, y0), (x0 + 0.004, y0 + 0.003),
        (x0, y0 + 0.003), (x0 + 0.004, y0),
        (x0, y0)
    ])

    # Build GeoDataFrame with mixed-quality attributes
    land_use_types = ["耕地", "林地", "园地", "草地", "城镇", "水域", ""]  # empty = missing
    data = {
        "geometry": parcels[:n],
        "DLMC": [land_use_types[i % len(land_use_types)] for i in range(n)],
        "DLBM": [f"0{(i%6)+1}" if i % 8 != 0 else "" for i in range(n)],  # some missing codes
        "ZMJ": [round(np.random.uniform(500, 5000), 1) for _ in range(n)],
        "QSDWMC": [f"村组{i//5+1}" for i in range(n)],
    }

    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")
    gdf.to_file(output_path, encoding="utf-8")
    return output_path


def run_demo():
    """Run the land governance audit demo."""
    from data_agent.pipeline_runner import run_pipeline_headless, PipelineResult

    tmp_dir = tempfile.mkdtemp(prefix="demo_gov_")
    shp_path = os.path.join(tmp_dir, "sample_parcels.shp")
    generate_sample_parcels(shp_path)
    print(f"[Demo] Generated sample parcels: {shp_path} (30 features, with quality issues)")

    query = (
        f"请对以下土地数据进行质量审计: {shp_path}\n"
        "检查内容:\n"
        "1. 拓扑检查：检测重叠、自相交等拓扑错误\n"
        "2. 属性检查：检测必填字段缺失（DLMC、DLBM）\n"
        "3. 坐标系检查：验证坐标系是否正确\n"
        "4. 生成治理审计报告"
    )

    print(f"[Demo] Running governance pipeline...")
    result: PipelineResult = run_pipeline_headless(
        query=query,
        user_id="demo_user",
        session_id="demo_gov_001",
        role="analyst",
    )

    print("\n" + "=" * 60)
    print("DEMO RESULTS — Land Governance Audit")
    print("=" * 60)
    print(f"Pipeline: {result.pipeline_type}")
    print(f"Intent: {result.intent}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Tokens: {result.total_input_tokens} in / {result.total_output_tokens} out")

    if result.error:
        print(f"Error: {result.error}")
    else:
        print(f"\nGenerated files ({len(result.generated_files)}):")
        for f in result.generated_files:
            print(f"  - {f['path']} ({f['type']})")

    if result.report_text:
        print(f"\nReport preview (first 500 chars):")
        print(result.report_text[:500])

    return result


if __name__ == "__main__":
    run_demo()

#!/usr/bin/env python
"""
Demo: Population Analysis & Visualization (人口分析可视化)

Demonstrates the general pipeline with population data analysis:
1. Generate sample district-level population data
2. Create choropleth map (population density)
3. Statistical summary and ranking
4. Heatmap overlay

Usage:
    python demos/demo_population_analysis.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generate_sample_districts(output_path: str) -> str:
    """Generate sample district polygons with population attributes."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Polygon

    np.random.seed(123)

    # Grid of districts centered around Beijing
    districts = []
    names = []
    populations = []
    areas_km2 = []

    district_names = [
        "东城区", "西城区", "朝阳区", "海淀区", "丰台区", "石景山区",
        "通州区", "顺义区", "大兴区", "昌平区", "房山区", "门头沟区",
        "怀柔区", "平谷区", "密云区", "延庆区",
    ]

    for i, name in enumerate(district_names):
        row = i // 4
        col = i % 4
        x0 = 116.1 + col * 0.15
        y0 = 40.1 - row * 0.12

        # Irregular polygon
        offsets = np.random.uniform(-0.02, 0.02, (5, 2))
        coords = [
            (x0 + offsets[0, 0], y0 + offsets[0, 1]),
            (x0 + 0.12 + offsets[1, 0], y0 + offsets[1, 1]),
            (x0 + 0.14 + offsets[2, 0], y0 + 0.10 + offsets[2, 1]),
            (x0 + 0.02 + offsets[3, 0], y0 + 0.11 + offsets[3, 1]),
            (x0 + offsets[4, 0], y0 + offsets[4, 1]),
        ]
        coords.append(coords[0])

        districts.append(Polygon(coords))
        names.append(name)

        # Core urban districts have higher population
        if i < 6:
            pop = np.random.randint(800000, 2500000)
            area = np.random.uniform(20, 80)
        else:
            pop = np.random.randint(200000, 900000)
            area = np.random.uniform(300, 2000)

        populations.append(pop)
        areas_km2.append(round(area, 1))

    gdf = gpd.GeoDataFrame({
        "geometry": districts,
        "name": names,
        "population": populations,
        "area_km2": areas_km2,
        "pop_density": [round(p / a) for p, a in zip(populations, areas_km2)],
    }, crs="EPSG:4326")

    gdf.to_file(output_path, encoding="utf-8")
    return output_path


def run_demo():
    """Run the population analysis demo."""
    from data_agent.pipeline_runner import run_pipeline_headless, PipelineResult

    tmp_dir = tempfile.mkdtemp(prefix="demo_pop_")
    shp_path = os.path.join(tmp_dir, "beijing_districts.shp")
    generate_sample_districts(shp_path)
    print(f"[Demo] Generated sample districts: {shp_path} (16 districts)")

    query = (
        f"请分析北京各区人口分布: {shp_path}\n"
        "分析内容:\n"
        "1. 使用人口密度(pop_density)字段生成分级设色专题图\n"
        "2. 统计各区人口排名\n"
        "3. 计算人口集中度指标\n"
        "4. 输出分析报告"
    )

    print(f"[Demo] Running general pipeline...")
    result: PipelineResult = run_pipeline_headless(
        query=query,
        user_id="demo_user",
        session_id="demo_pop_001",
        role="analyst",
    )

    print("\n" + "=" * 60)
    print("DEMO RESULTS — Population Analysis")
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

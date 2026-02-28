#!/usr/bin/env python
"""
Demo: Retail Site Selection Analysis (零售选址分析)

Demonstrates the headless pipeline runner with a retail site selection scenario:
1. Upload simulated store CSV (with addresses)
2. Geocode addresses to coordinates
3. DBSCAN clustering to find store clusters
4. Buffer analysis around cluster centroids
5. Interactive map with all layers

Usage:
    python demos/demo_retail_site_selection.py
"""
import os
import sys
import csv
import tempfile

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# --- Step 1: Generate sample store data ---
SAMPLE_STORES = [
    {"name": "门店A-朝阳大悦城", "address": "北京市朝阳区朝阳北路101号", "lng": 116.510, "lat": 39.921},
    {"name": "门店B-三里屯", "address": "北京市朝阳区三里屯路19号", "lng": 116.454, "lat": 39.936},
    {"name": "门店C-国贸CBD", "address": "北京市朝阳区建国门外大街1号", "lng": 116.461, "lat": 39.908},
    {"name": "门店D-望京SOHO", "address": "北京市朝阳区望京街10号", "lng": 116.480, "lat": 40.001},
    {"name": "门店E-五道口", "address": "北京市海淀区成府路28号", "lng": 116.338, "lat": 39.992},
    {"name": "门店F-中关村", "address": "北京市海淀区中关村大街27号", "lng": 116.316, "lat": 39.982},
    {"name": "门店G-西直门", "address": "北京市西城区西直门外大街1号", "lng": 116.354, "lat": 39.943},
    {"name": "门店H-王府井", "address": "北京市东城区王府井大街255号", "lng": 116.410, "lat": 39.915},
    {"name": "门店I-西单", "address": "北京市西城区西单北大街120号", "lng": 116.373, "lat": 39.912},
    {"name": "门店J-亦庄", "address": "北京市大兴区荣华南路10号", "lng": 116.506, "lat": 39.795},
    {"name": "门店K-通州万达", "address": "北京市通州区新华西街58号", "lng": 116.657, "lat": 39.903},
    {"name": "门店L-回龙观", "address": "北京市昌平区回龙观西大街35号", "lng": 116.334, "lat": 40.074},
    {"name": "门店M-双井", "address": "北京市朝阳区东三环中路20号", "lng": 116.463, "lat": 39.899},
    {"name": "门店N-安贞", "address": "北京市朝阳区安贞路甲2号", "lng": 116.405, "lat": 39.968},
    {"name": "门店O-丰台科技园", "address": "北京市丰台区丰台北路18号", "lng": 116.290, "lat": 39.855},
]


def generate_sample_csv(output_path: str) -> str:
    """Write sample store data to CSV."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "address", "lng", "lat"])
        writer.writeheader()
        writer.writerows(SAMPLE_STORES)
    return output_path


def run_demo():
    """Run the retail site selection demo using pipeline_runner."""
    from data_agent.pipeline_runner import run_pipeline_headless, PipelineResult

    # Create temp CSV
    tmp_dir = tempfile.mkdtemp(prefix="demo_retail_")
    csv_path = os.path.join(tmp_dir, "stores_beijing.csv")
    generate_sample_csv(csv_path)
    print(f"[Demo] Generated sample data: {csv_path} ({len(SAMPLE_STORES)} stores)")

    # Run headless pipeline
    query = (
        f"请分析北京门店分布情况。数据文件: {csv_path}\n"
        "步骤:\n"
        "1. 加载CSV数据并检查数据质量\n"
        "2. 对门店进行DBSCAN聚类分析(eps=3000米, min_samples=2)\n"
        "3. 生成交互式地图展示门店位置和聚类结果\n"
        "4. 输出分析报告总结"
    )

    print(f"[Demo] Running pipeline: {query[:60]}...")
    result: PipelineResult = run_pipeline_headless(
        query=query,
        user_id="demo_user",
        session_id="demo_retail_001",
        role="analyst",
    )

    # Report results
    print("\n" + "=" * 60)
    print("DEMO RESULTS — Retail Site Selection")
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

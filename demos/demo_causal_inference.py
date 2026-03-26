"""Demo: Three-Angle Causal Inference System.

Demonstrates the three complementary causal inference approaches:
  A: Statistical causal inference (PSM, DiD, Granger, etc.)
  B: LLM-based causal reasoning (DAG, counterfactual, mechanism)
  C: Causal world model (intervention, counterfactual comparison)

Usage:
    python demos/demo_causal_inference.py
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def demo_angle_a():
    """Demonstrate statistical causal inference tools."""
    print("\n" + "-" * 50)
    print("Angle A: Statistical Causal Inference (GeoFM-enhanced)")
    print("-" * 50)

    # Generate synthetic data for PSM demo
    np.random.seed(42)
    n = 200
    treatment = np.random.binomial(1, 0.5, n)
    x1 = np.random.normal(0, 1, n)
    x2 = np.random.normal(0, 1, n)
    outcome = 2 * treatment + 0.5 * x1 - 0.3 * x2 + np.random.normal(0, 0.5, n)

    print(f"\n  Synthetic dataset: {n} observations")
    print(f"  Treatment group: {treatment.sum()}, Control group: {n - treatment.sum()}")
    print(f"  True ATE: 2.0")

    try:
        import tempfile
        import geopandas as gpd
        from shapely.geometry import Point

        gdf = gpd.GeoDataFrame({
            "treatment": treatment,
            "outcome": outcome,
            "covariate_1": x1,
            "covariate_2": x2,
            "geometry": [Point(114 + i * 0.01, 30 + i * 0.01) for i in range(n)]
        }, crs="EPSG:4326")

        # Save to temp file (propensity_score_matching takes a file path)
        tmp = tempfile.NamedTemporaryFile(suffix=".geojson", delete=False)
        gdf.to_file(tmp.name, driver="GeoJSON")
        tmp.close()

        from data_agent.causal_inference import propensity_score_matching
        result = propensity_score_matching(
            file_path=tmp.name,
            treatment_col="treatment",
            outcome_col="outcome",
            confounders="covariate_1,covariate_2",
        )
        # result is a JSON string
        import json
        parsed = json.loads(result) if isinstance(result, str) else result
        print(f"  Estimated ATT: {parsed.get('att', 'N/A')}")
        print(f"  Matched pairs: {parsed.get('matched_pairs', 'N/A')}")
        print("  Status: OK")

        os.unlink(tmp.name)
    except Exception as e:
        print(f"  Note: Full execution requires dependencies ({e})")

    print("\n  Available tools:")
    tools = ["propensity_score_matching", "exposure_response_function",
             "difference_in_differences", "granger_causality",
             "geographical_convergent_cross_mapping", "causal_forest"]
    for t in tools:
        print(f"    - {t}")


def demo_angle_b():
    """Demonstrate LLM causal reasoning tools."""
    print("\n" + "-" * 50)
    print("Angle B: LLM Causal Reasoning (Gemini-powered)")
    print("-" * 50)

    print("\n  Available tools:")
    tools = {
        "construct_causal_dag": "Build causal DAG from variable descriptions",
        "counterfactual_reasoning": "What-if analysis with structured reasoning chains",
        "explain_causal_mechanism": "Interpret Angle A statistical results",
        "generate_what_if_scenarios": "Map to world model scenarios",
    }
    for name, desc in tools.items():
        print(f"    - {name}: {desc}")

    print('\n  Example DAG construction query:')
    print('    "分析公园建设对周边房价的影响，考虑交通、噪音、绿化等因素"')
    print("  -> Variables: park_construction, housing_price, traffic, noise, green_coverage")
    print("  -> Confounders: distance_to_center, income_level")


def demo_angle_c():
    """Demonstrate causal world model tools."""
    print("\n" + "-" * 50)
    print("Angle C: Causal World Model (Spatial Intervention)")
    print("-" * 50)

    print("\n  Available tools:")
    tools = {
        "intervention_predict": "Apply spatial intervention + predict LULC change",
        "counterfactual_comparison": "Compare parallel scenarios pixel-by-pixel",
        "embedding_treatment_effect": "Measure treatment effect in embedding space",
        "integrate_statistical_prior": "Calibrate predictions with Angle A ATT",
    }
    for name, desc in tools.items():
        print(f"    - {name}: {desc}")

    print("\n  Integration with World Model:")
    print("    - Spatial mask blending for sub-region interventions")
    print("    - Dual forward pass for counterfactual comparison")
    print("    - Cosine/Euclidean/Manhattan distance metrics")
    print("    - ATT-calibrated prediction offset")


def main():
    print("=" * 60)
    print("GIS Data Agent — Three-Angle Causal Inference Demo")
    print("=" * 60)

    demo_angle_a()
    demo_angle_b()
    demo_angle_c()

    print("\n" + "=" * 60)
    print("Demo complete. Use the web UI for interactive causal analysis.")
    print("=" * 60)


if __name__ == "__main__":
    main()

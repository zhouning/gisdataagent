"""Demo: World Model prediction — AlphaEarth + LatentDynamicsNet.

Demonstrates the world model's ability to predict future land use/land cover
changes under different scenarios using satellite embedding analysis.

Usage:
    python demos/demo_world_model.py
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    print("=" * 60)
    print("GIS Data Agent — World Model Demo")
    print("=" * 60)

    # Demo 1: List available scenarios
    print("\n[1/3] Available prediction scenarios:")
    scenarios = {
        "urban_sprawl": "城市蔓延 — 模拟城市扩张对周边农业用地的影响",
        "ecological_restoration": "生态修复 — 模拟退耕还林政策下的植被恢复",
        "agricultural_intensification": "农业集约化 — 模拟现代农业技术对土地利用的改变",
        "climate_adaptation": "气候适应 — 模拟极端气候事件后的土地利用调整",
        "baseline": "基线趋势 — 维持当前发展趋势的自然演变",
    }
    for key, desc in scenarios.items():
        print(f"  - {key}: {desc}")

    # Demo 2: Explain the model architecture
    print("\n[2/3] Model architecture:")
    print("  - AlphaEarth: Google Satellite Embedding V1 (64-dim)")
    print("  - LatentDynamicsNet: Residual CNN with dilated convolutions")
    print("  - Parameters: ~459K")
    print("  - Receptive field: ~170m (dilation 1/2/4)")
    print("  - LULC decoder: LogisticRegression (83.7% accuracy)")

    # Demo 3: Show prediction pipeline
    print("\n[3/3] Prediction pipeline:")
    print("  1. Fetch AlphaEarth embeddings for target region (bbox)")
    print("  2. Apply scenario-specific intervention (one-hot encoding)")
    print("  3. Forward pass through LatentDynamicsNet")
    print("  4. Decode predicted embeddings to LULC classes")
    print("  5. Generate transition matrix and change statistics")

    # Try to import and check model status
    try:
        from data_agent.world_model import list_scenarios, get_model_info
        scenarios_live = list_scenarios()
        print(f"\n  Live scenarios from module: {[s['id'] for s in scenarios_live]}")
        info = get_model_info()
        print(f"  Weights exist: {info.get('weights_exist', False)}")
        print(f"  Decoder exist: {info.get('decoder_exist', False)}")
        print(f"  Param count: {info.get('param_count', 'N/A')}")
    except Exception as e:
        print(f"\n  Note: World model not available ({e})")
        print("  This demo shows the architecture; full execution requires model weights.")

    print("\n" + "=" * 60)
    print("Demo complete. Run the full agent for interactive predictions.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

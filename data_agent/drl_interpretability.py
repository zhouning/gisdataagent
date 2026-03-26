"""DRL Optimization Explainability — SHAP feature importance analysis."""

import logging
import os
import json
import uuid
from typing import Optional

import numpy as np

logger = logging.getLogger("data_agent.drl_interpretability")

# Feature names from drl_engine.py observation space
PARCEL_FEATURE_NAMES = [
    "slope (坡度)", "is_farmland (耕地)", "neighbor_ratio (邻域比)",
    "neighbor_slope (邻域坡度)", "area (面积)", "slope_vs_mean (坡度偏差)"
]
GLOBAL_FEATURE_NAMES = [
    "contiguity (连片度)", "farmland_deviation (耕地偏差)", "step_progress (步骤)",
    "type_ratio_0", "type_ratio_1", "type_ratio_2",
    "slope_change (坡度变化)", "contiguity_change (连片变化)"
]


def explain_drl_decision(
    model_path: str,
    observation: Optional[np.ndarray] = None,
    n_background: int = 50,
    output_dir: str = "",
) -> dict:
    """Explain a DRL model's decisions using permutation-based feature importance.

    Instead of SHAP (heavy dependency), we use a lightweight permutation importance
    approach that works with any model.

    Args:
        model_path: Path to the trained MaskablePPO model
        observation: Optional specific observation to explain
        n_background: Number of random observations for baseline
        output_dir: Directory to save explanation chart

    Returns:
        dict with feature_importance, chart_path, summary
    """
    try:
        from sb3_contrib import MaskablePPO
    except ImportError:
        return {"status": "error", "message": "sb3_contrib not installed"}

    try:
        model = MaskablePPO.load(model_path)
    except Exception as e:
        return {"status": "error", "message": f"Failed to load model: {e}"}

    # Generate random observations if none provided
    obs_space = model.observation_space
    if observation is None:
        observation = obs_space.sample()

    n_features = observation.shape[0] if observation.ndim == 1 else observation.shape[-1]

    # Feature names
    all_features = list(PARCEL_FEATURE_NAMES) + list(GLOBAL_FEATURE_NAMES)
    if len(all_features) < n_features:
        all_features.extend([f"feature_{i}" for i in range(len(all_features), n_features)])
    all_features = all_features[:n_features]

    # Permutation importance: for each feature, shuffle it and measure action change
    base_action, _ = model.predict(observation.reshape(1, -1), deterministic=True)
    base_action_probs = _get_action_probs(model, observation)

    importance = np.zeros(n_features)
    n_repeats = min(n_background, 20)

    for feat_idx in range(n_features):
        diffs = []
        for _ in range(n_repeats):
            perturbed = observation.copy()
            perturbed[feat_idx] = np.random.uniform(
                obs_space.low[feat_idx] if hasattr(obs_space, 'low') else -1,
                obs_space.high[feat_idx] if hasattr(obs_space, 'high') else 1,
            )
            perturbed_probs = _get_action_probs(model, perturbed)
            if base_action_probs is not None and perturbed_probs is not None:
                diff = np.mean(np.abs(base_action_probs - perturbed_probs))
            else:
                perturbed_action, _ = model.predict(perturbed.reshape(1, -1), deterministic=True)
                diff = float(perturbed_action != base_action)
            diffs.append(diff)
        importance[feat_idx] = np.mean(diffs)

    # Normalize to percentages
    total = importance.sum()
    if total > 0:
        importance_pct = (importance / total * 100).tolist()
    else:
        importance_pct = importance.tolist()

    # Build result
    features_ranked = sorted(
        zip(all_features, importance_pct),
        key=lambda x: x[1], reverse=True
    )

    result = {
        "status": "ok",
        "feature_importance": [{"feature": f, "importance": round(v, 2)} for f, v in features_ranked],
        "top_features": [f for f, _ in features_ranked[:3]],
        "summary": f"最重要的特征: {features_ranked[0][0]} ({features_ranked[0][1]:.1f}%), "
                   f"{features_ranked[1][0]} ({features_ranked[1][1]:.1f}%), "
                   f"{features_ranked[2][0]} ({features_ranked[2][1]:.1f}%)" if len(features_ranked) >= 3 else "",
    }

    # Generate chart
    if output_dir:
        chart_path = _generate_importance_chart(features_ranked, output_dir)
        if chart_path:
            result["chart_path"] = chart_path

    return result


def _get_action_probs(model, obs: np.ndarray) -> Optional[np.ndarray]:
    """Get action probability distribution from the model."""
    try:
        import torch
        obs_tensor = torch.as_tensor(obs.reshape(1, -1), dtype=torch.float32).to(model.device)
        with torch.no_grad():
            dist = model.policy.get_distribution(obs_tensor)
            probs = dist.distribution.probs.cpu().numpy().flatten()
        return probs
    except Exception:
        return None


def _generate_importance_chart(features_ranked: list, output_dir: str) -> Optional[str]:
    """Generate a horizontal bar chart of feature importance."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        names = [f for f, _ in features_ranked[:10]]
        values = [v for _, v in features_ranked[:10]]

        fig, ax = plt.subplots(figsize=(8, 5))
        colors = ['#4f6ef7' if i < 3 else '#94a3b8' for i in range(len(names))]
        bars = ax.barh(range(len(names)), values, color=colors)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=10)
        ax.set_xlabel("Importance (%)", fontsize=11)
        ax.set_title("DRL Decision Feature Importance", fontsize=13, fontweight='bold')
        ax.invert_yaxis()

        for bar, val in zip(bars, values):
            ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                    f'{val:.1f}%', va='center', fontsize=9)

        plt.tight_layout()
        uid = uuid.uuid4().hex[:8]
        path = os.path.join(output_dir, f"drl_explain_{uid}.png")
        plt.savefig(path, dpi=120, bbox_inches='tight')
        plt.close(fig)
        return path
    except Exception as e:
        logger.warning("Chart generation failed: %s", e)
        return None


def get_scenario_feature_summary(scenario_id: str) -> dict:
    """Get a human-readable summary of which features matter most for a scenario."""
    scenario_insights = {
        "farmland_optimization": {
            "key_features": ["slope", "is_farmland", "contiguity"],
            "description": "耕地优化主要考虑坡度适宜性、现有耕地分布和连片程度"
        },
        "urban_green_layout": {
            "key_features": ["area", "neighbor_ratio", "contiguity"],
            "description": "城市绿地布局关注地块面积、周边绿地比例和空间连续性"
        },
        "facility_siting": {
            "key_features": ["slope", "area", "neighbor_slope"],
            "description": "设施选址优先考虑地形条件和地块规模"
        },
    }
    return scenario_insights.get(scenario_id, {
        "key_features": ["slope", "contiguity", "area"],
        "description": "通用场景下坡度、连片度和面积是关键决策因素"
    })

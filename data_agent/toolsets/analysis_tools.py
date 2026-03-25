"""Analysis toolset: FFI calculation, DRL optimization, multi-objective Pareto."""
import asyncio
import os
import traceback

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import torch
from sb3_contrib import MaskablePPO
from stable_baselines3.common.monitor import Monitor

from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.base_toolset import BaseToolset

from .. import drl_engine
from ..FFI import ffi as calculate_ffi
from ..parcel_scoring_policy import ParcelScoringPolicy
from ..gis_processors import _generate_output_path, _resolve_path
from ..utils import _load_spatial_data, _configure_fonts


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def _plot_land_use_result(gdf, land_use_types, title, output_path):
    """Helper function for visualizing land use results."""
    _configure_fonts()
    OTHER, FARMLAND, FOREST = drl_engine.OTHER, drl_engine.FARMLAND, drl_engine.FOREST
    cmap = {OTHER: '#D3D3D3', FARMLAND: '#FFD700', FOREST: '#228B22'}
    gdf_plot = gdf.copy()
    gdf_plot['color'] = [cmap.get(t, '#333333') for t in land_use_types]
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    gdf_plot.plot(ax=ax, color=gdf_plot['color'], edgecolor='none')
    ax.set_title(title, fontsize=15)
    ax.set_axis_off()
    patches = [mpatches.Patch(color='#FFD700', label='耕地'), mpatches.Patch(color='#228B22', label='林地'), mpatches.Patch(color='#D3D3D3', label='其他')]
    ax.legend(handles=patches, loc='lower right', fontsize=12)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()


def drl_model(data_path: str, scenario_id: str = "",
              slope_weight: str = "", contiguity_weight: str = "",
              balance_weight: str = "", pair_bonus: str = "") -> str:
    """使用深度强化学习模型进行布局优化。

    Args:
        data_path: 输入数据路径 (Shapefile/GeoJSON)
        scenario_id: 场景模板 ID (farmland_optimization/urban_green_space/facility_siting)
        slope_weight: 坡度权重 (100-3000, 默认由场景决定)
        contiguity_weight: 连片权重 (100-2000)
        balance_weight: 平衡权重 (100-2000)
        pair_bonus: 配对奖励 (0.1-10.0)
    """
    try:
        res_data_path = _resolve_path(data_path)

        # Build scenario with optional weight overrides
        scenario = None
        if scenario_id and scenario_id in drl_engine.SCENARIOS:
            scenario = drl_engine.SCENARIOS[scenario_id]
        # Apply user weight overrides (construct temporary scenario)
        if any([slope_weight, contiguity_weight, balance_weight, pair_bonus]):
            base = scenario or drl_engine.SCENARIOS.get("farmland_optimization")
            scenario = drl_engine.DRLScenario(
                name=base.name if base else "自定义",
                description=base.description if base else "用户自定义权重",
                source_types=base.source_types if base else {'旱地', '水田'},
                target_types=base.target_types if base else {'果园', '有林地'},
                slope_weight=float(slope_weight) if slope_weight else (base.slope_weight if base else 1000.0),
                contiguity_weight=float(contiguity_weight) if contiguity_weight else (base.contiguity_weight if base else 500.0),
                balance_weight=float(balance_weight) if balance_weight else (base.balance_weight if base else 500.0),
                pair_bonus=float(pair_bonus) if pair_bonus else (base.pair_bonus if base else 1.0),
            )

        # scorer_weights_v7.pt lives in data_agent/ (parent of toolsets/)
        weights_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scorer_weights_v7.pt')

        env = drl_engine.LandUseOptEnv(res_data_path, max_conversions=200, scenario=scenario)
        env_mon = Monitor(env)

        checkpoint = torch.load(weights_path, map_location='cpu')

        model = MaskablePPO(
            ParcelScoringPolicy,
            env_mon,
            policy_kwargs=dict(
                k_parcel=checkpoint.get('k_parcel', 6),
                k_global=checkpoint.get('k_global', 8),
                scorer_hiddens=checkpoint.get('scorer_hiddens', [128, 64]),
                value_hiddens=checkpoint.get('value_hiddens', [128, 64]),
            ),
            device='cpu',
        )

        model.policy.scorer_net.load_state_dict(checkpoint['scorer_net'])
        model.policy.value_net.load_state_dict(checkpoint['value_net'])
        model.policy.eval()

        obs, info = env.reset()
        terminated, truncated = False, False
        while not (terminated or truncated):
            masks = env.action_masks()
            if not masks.any(): break
            action, _ = model.predict(obs, action_masks=masks, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)

        out_map = _generate_output_path("optimized_map", "png")
        _plot_land_use_result(env.gdf, env.land_use, "基于 PPO v7 的耕地布局优化", out_map)

        out_shp = _generate_output_path("optimized_data", "shp")
        gdf_out = env.gdf.copy()
        gdf_out['Opt_Type'] = env.land_use
        gdf_out.to_file(out_shp)

        summary = f"Optimization Complete (v7).\n" \
                  f"Conversions: {info.get('completed_conversions', 0)}\n" \
                  f"Pairs: {info.get('completed_pairs', 0)}\n" \
                  f"Net Change: {info.get('farmland_change', 0)}\n" \
                  f"Result SHP: {out_shp}\nVisualization: {out_map}"
        return {"output_path": out_map, "optimized_data_path": out_shp, "summary": summary}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error: {str(e)}"


async def drl_model_long_running(data_path: str, scenario_id: str = "",
                                 slope_weight: str = "", contiguity_weight: str = "",
                                 balance_weight: str = "", pair_bonus: str = "") -> str:
    """使用深度强化学习模型进行布局优化。"""
    return await asyncio.to_thread(drl_model, data_path, scenario_id,
                                   slope_weight, contiguity_weight,
                                   balance_weight, pair_bonus)

# Preserve tool name for ADK FunctionTool registration
drl_model_long_running.__name__ = "drl_model"
drl_model_long_running.__qualname__ = "drl_model"


def ffi(data_path: str) -> str:
    """计算破碎化指数。"""
    res_path = _resolve_path(data_path)
    return calculate_ffi(res_path) if os.path.exists(res_path) else f"Error: {res_path} not found"


def drl_multi_objective(data_path: str, objectives: str = "slope,contiguity,area_balance",
                        iterations: str = "5") -> str:
    """多目标用地优化 — Pareto 前沿分析，在多个冲突目标间寻找权衡方案集。

    Args:
        data_path: 用地数据路径（SHP/GeoJSON）
        objectives: 优化目标（逗号分隔: slope,contiguity,area_balance）
        iterations: 优化迭代轮数（不同权重组合数，默认5）

    Returns:
        JSON 包含 Pareto 前沿解集和各目标值。
    """
    import json
    try:
        res_path = _resolve_path(data_path)
        gdf = gpd.read_file(res_path)
        from ..drl_engine import optimize_multi_objective
        result = optimize_multi_objective(gdf, max_steps=200)

        # Generate Pareto visualization
        try:
            out_png = _generate_output_path("pareto_frontier", "png")
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            frontier = result["pareto_frontier"]
            if len(frontier) >= 2:
                fig, ax = plt.subplots(1, 1, figsize=(8, 6))
                xs = [s["objectives"][0] for s in frontier]
                ys = [s["objectives"][1] for s in frontier]
                sizes = [s["objectives"][2] * 100 + 20 for s in frontier]
                ax.scatter(xs, ys, s=sizes, c='steelblue', alpha=0.7, edgecolors='navy')
                ax.set_xlabel("Slope Score")
                ax.set_ylabel("Contiguity Score")
                ax.set_title(f"Pareto Frontier ({len(frontier)} solutions)")
                for i, s in enumerate(frontier):
                    ax.annotate(f"#{i+1}", (xs[i], ys[i]), fontsize=8)
                plt.tight_layout()
                plt.savefig(out_png, dpi=150)
                plt.close(fig)
                result["visualization"] = out_png
        except Exception:
            pass

        return json.dumps({"status": "ok", **result}, default=str)
    except Exception as e:
        import json, traceback
        traceback.print_exc()
        return json.dumps({"status": "error", "message": str(e)})


def train_drl_model(data_path: str, scenario: str = "farmland_optimization",
                    epochs: str = "50") -> str:
    """使用用户数据训练自定义 DRL 模型。训练完成后保存权重文件。

    Args:
        data_path: 训练数据的Shapefile路径。
        scenario: 场景模板ID（farmland_optimization/urban_green_space/facility_siting）。
        epochs: 训练轮数，默认50。

    Returns:
        训练结果摘要和模型权重路径。
    """
    try:
        import torch
        res_path = _resolve_path(data_path)
        n_epochs = int(epochs)

        from data_agent.drl_engine import LandUseOptEnv, SCENARIOS
        sc = SCENARIOS.get(scenario)

        env = LandUseOptEnv(res_path, scenario=sc)
        env_mon = Monitor(env)

        model = MaskablePPO(
            ParcelScoringPolicy,
            env_mon,
            policy_kwargs=dict(
                k_parcel=6, k_global=8,
                scorer_hiddens=[128, 64], value_hiddens=[128, 64],
            ),
            n_steps=200,
            device='cpu',
            verbose=0,
        )

        model.learn(total_timesteps=200 * n_epochs)

        # Save weights
        out_path = _generate_output_path(f"trained_{scenario}", "pt")
        torch.save({
            "scorer_net": model.policy.scorer_net.state_dict(),
            "value_net": model.policy.value_net.state_dict(),
            "k_parcel": 6, "k_global": 8,
            "scorer_hiddens": [128, 64], "value_hiddens": [128, 64],
            "scenario": scenario, "epochs": n_epochs,
        }, out_path)

        return json.dumps({
            "status": "success",
            "message": f"训练完成：{n_epochs} 轮，场景 {scenario}",
            "weights_path": out_path,
            "parcels": env.n_parcels,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def list_drl_scenarios() -> str:
    """列出所有可用的 DRL 优化场景模板。

    Returns:
        JSON格式的场景列表，包含名称、描述、权重配置。
    """
    from data_agent.drl_engine import list_scenarios
    return json.dumps({"scenarios": list_scenarios()}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_SYNC_FUNCS = [ffi, drl_multi_objective, list_drl_scenarios]
_LONG_RUNNING_FUNCS = [drl_model_long_running]


class AnalysisToolset(BaseToolset):
    """FFI calculation and DRL layout optimization tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _SYNC_FUNCS] + [
            LongRunningFunctionTool(f) for f in _LONG_RUNNING_FUNCS
        ]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]

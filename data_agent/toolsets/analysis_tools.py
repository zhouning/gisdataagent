"""Analysis toolset: FFI calculation and DRL land-use optimization."""
import os

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import torch
from sb3_contrib import MaskablePPO
from stable_baselines3.common.monitor import Monitor

from google.adk.tools import FunctionTool
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


def drl_model(data_path: str) -> str:
    """使用深度强化学习模型进行布局优化。"""
    try:
        res_data_path = _resolve_path(data_path)

        # scorer_weights_v7.pt lives in data_agent/ (parent of toolsets/)
        weights_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scorer_weights_v7.pt')

        env = drl_engine.LandUseOptEnv(res_data_path, max_conversions=200)
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


def ffi(data_path: str) -> str:
    """计算破碎化指数。"""
    res_path = _resolve_path(data_path)
    return calculate_ffi(res_path) if os.path.exists(res_path) else f"Error: {res_path} not found"


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [ffi, drl_model]


class AnalysisToolset(BaseToolset):
    """FFI calculation and DRL layout optimization tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]

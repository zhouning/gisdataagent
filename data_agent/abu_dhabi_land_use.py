"""Read-only presentation service for the frozen Abu Dhabi land-use benchmark."""

from __future__ import annotations

import io
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from PIL import Image

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_ROOT = REPOSITORY_ROOT / "benchmarks/abu_dhabi_land_use_v1"
MODEL_IDS = ("geosos_flus", "geospatial_kernel", "paper58")
SCENARIO_IDS = ("compact", "ecological_priority", "outward_growth")
SEED_IDS = ("ensemble", "31", "47", "73")

MODEL_PRESENTATION: dict[str, dict[str, Any]] = {
    "geosos_flus": {
        "label": "GeoSOS-FLUS",
        "family": "传统 ANN + CA 基线",
        "mechanism": "ANN 学习类别适宜性，CA 在邻域竞争、转换成本和目标数量约束下完成空间分配。",
        "state": "六类土地覆盖栅格",
        "action": "年度目标类别像元数",
        "runtime": "外部 FLUS Console",
        "inputs": ["2021 土地覆盖", "地形", "夜间灯光", "道路距离", "坐标", "硬排除区"],
        "caveats": [
            "FLUS 保留原生迭代收敛行为，目标类别数量可能存在小幅误差。",
            "冻结转换矩阵没有追加建成区不可逆规则，规划结果中保留了既有建成区退出。",
        ],
    },
    "geospatial_kernel": {
        "label": "GWM Geospatial Kernel",
        "family": "显式状态、动作与空间传播内核",
        "mechanism": (
            "梯度提升模型学习类别适宜性，显式分配器综合 3x3/7x7 邻域、"
            "动作和硬约束，并逐年写回状态。"
        ),
        "state": "土地覆盖、邻域组成和显式空间驱动",
        "action": "年度目标类别像元数",
        "runtime": "HistGradientBoosting + 显式分配器",
        "inputs": ["2017-2021 历史转移", "地形", "夜间灯光", "道路距离", "坐标", "硬排除区"],
        "caveats": [
            "这是阿布扎比基准内的显式 Kernel 实现，不等同于完整 TWM 治理运行时。",
            "规划结果是给定需求下的条件分配，不是对真实政策需求的预测。",
        ],
    },
    "paper58": {
        "label": "Paper58",
        "family": "AlphaEarth 潜状态动力学",
        "mechanism": (
            "需求条件 LDN 在 64 维 AlphaEarth 潜状态中预测下一状态，"
            "经语义解码器和共享分配器生成土地覆盖。"
        ),
        "state": "64 维 AlphaEarth 年度嵌入",
        "action": "类别占比与相对变化需求向量",
        "runtime": "Demand-conditioned LDN checkpoint",
        "inputs": ["2017-2021 AlphaEarth", "历史土地覆盖", "年度需求", "硬排除区"],
        "caveats": [
            "未来外生观测不写回，规划阶段递归使用模型预测的潜状态。",
            "潜状态维度没有逐维物理语义，语义地图来自单独训练的解码器。",
        ],
    },
}

INPUT_SOURCES = [
    {
        "name": "年度土地覆盖",
        "source": "Dynamic World V1",
        "years": "2017-2024",
        "role": "状态、训练标签与历史评价",
    },
    {
        "name": "遥感潜状态",
        "source": "AlphaEarth Satellite Embedding",
        "years": "2017-2024",
        "role": "Paper58 64 维潜状态",
    },
    {
        "name": "夜间灯光",
        "source": "NOAA VIIRS DNB",
        "years": "2017-2024",
        "role": "人类活动强度代理",
    },
    {"name": "地形", "source": "Copernicus DEM GLO30", "years": "2024.1", "role": "高程和坡度驱动"},
    {
        "name": "道路与公共约束",
        "source": "OpenStreetMap / Geofabrik",
        "years": "2026-07-31",
        "role": "道路可达性和代理约束",
    },
    {
        "name": "水体与湿地约束",
        "source": "ESA WorldCover 2021",
        "years": "2021",
        "role": "硬排除区构造",
    },
]

FIGURES = {
    "land_cover_overview": "figures/fig01_land_cover_overview.png",
    "driver_inputs": "figures/fig02_driver_inputs.png",
    "temporal_quality": "figures/fig03_temporal_quality.png",
    "experiment_design": "figures/fig04_experiment_design.png",
    "historical_maps": "figures/fig05_historical_2024_maps.png",
    "historical_errors": "figures/fig06_historical_change_errors.png",
    "historical_metrics": "figures/fig07_historical_metrics.png",
    "planning_metrics": "figures/fig08_planning_metrics.png",
    "planning_map": "planning_2030_comparison.png",
}

CLASS_LEGEND = [
    {"value": 1, "label": "水体", "color": "#3978a8"},
    {"value": 2, "label": "木本植被", "color": "#27734f"},
    {"value": 3, "label": "低矮植被", "color": "#85b84f"},
    {"value": 4, "label": "湿地", "color": "#47a9a5"},
    {"value": 5, "label": "建成区", "color": "#d85852"},
    {"value": 6, "label": "裸地", "color": "#d5bd78"},
]


def configured_benchmark_root() -> Path:
    configured = os.environ.get("ABU_DHABI_LAND_USE_BENCHMARK_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_BENCHMARK_ROOT


class AbuDhabiLandUseService:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or configured_benchmark_root()).resolve()

    def _read_json(self, relative_path: str) -> dict[str, Any]:
        path = self.root / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"abu_dhabi_artifact_missing:{relative_path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"abu_dhabi_artifact_invalid:{relative_path}")
        return payload

    @staticmethod
    def _mean_metric(summary: dict[str, Any], metric: str) -> float | None:
        value = summary.get(metric, {})
        mean = value.get("mean") if isinstance(value, dict) else None
        return float(mean) if isinstance(mean, (int, float)) else None

    def _historical_summary(self, comparison: dict[str, Any], model_id: str) -> dict[str, Any]:
        model_summary = comparison.get("summaries", {}).get(model_id, {})
        years: dict[str, Any] = {}
        for year in (2023, 2024):
            row = model_summary.get(str(year), {})
            years[str(year)] = {
                "change_f1": self._mean_metric(row, "change_f1"),
                "change_fom": self._mean_metric(row, "change_figure_of_merit"),
                "macro_f1": self._mean_metric(row, "macro_f1"),
                "overall_accuracy": self._mean_metric(row, "overall_accuracy"),
                "demand_total_variation": self._mean_metric(row, "demand_total_variation"),
                "constraint_violation_rate": self._mean_metric(row, "constraint_violation_rate"),
                "high_confidence_change_fom": self._mean_metric(
                    row, "reliability_change_figure_of_merit"
                ),
            }
        return years

    @staticmethod
    def _planning_candidates(planning: dict[str, Any], model_id: str) -> list[dict[str, Any]]:
        fields = (
            "candidate_id",
            "model_id",
            "scenario_id",
            "built_gain_pixels",
            "green_gain_pixels",
            "removed_built_pixels",
            "demand_total_variation",
            "ecological_conversion_rate",
            "new_built_neighbor_fraction",
            "new_built_mean_prior_built_distance_m",
            "new_built_mean_major_road_distance_m",
            "constraint_violation_rate",
        )
        return [
            {key: row.get(key) for key in fields}
            for row in planning.get("final_candidates", [])
            if row.get("model_id") == model_id
        ]

    def overview(self) -> dict[str, Any]:
        protocol = self._read_json("protocol.json")
        comparison = self._read_json("comparison_report.json")
        planning = self._read_json("planning_comparison_report.json")
        data_audit = self._read_json("data_audit.json")
        output_audit = self._read_json("output_audit.json")
        grid = data_audit.get("grid", {})
        warnings = data_audit.get("warnings", {})
        pareto = set(planning.get("pareto_frontier", []))
        models = []
        for model_id in MODEL_IDS:
            candidates = self._planning_candidates(planning, model_id)
            models.append(
                {
                    "id": model_id,
                    **MODEL_PRESENTATION[model_id],
                    "historical": self._historical_summary(comparison, model_id),
                    "planning": candidates,
                    "pareto_scenarios": [
                        row["scenario_id"]
                        for row in candidates
                        if row.get("candidate_id") in pareto
                    ],
                }
            )
        return {
            "schema": "gwm.abu_dhabi_land_use_presentation.v1",
            "status": protocol.get("status"),
            "benchmark_id": protocol.get("benchmark_id"),
            "title": protocol.get("title"),
            "scope": {
                "city": protocol.get("spatial_world", {}).get("name"),
                "boundary": protocol.get("spatial_world", {}).get("boundary_source"),
                "crs": grid.get("crs"),
                "resolution_m": grid.get("resolution_m"),
                "width": grid.get("width"),
                "height": grid.get("height"),
                "valid_pixels": 79726,
                "area_km2": 797.26,
                "observed_years": protocol.get("temporal_world", {}).get("observed_years", []),
            },
            "data_quality": {
                "status": data_audit.get("status"),
                "mean_low_confidence_fraction": warnings.get(
                    "mean_fraction_below_dynamic_world_confidence_0_5"
                ),
                "median_one_year_reversion_fraction": warnings.get(
                    "median_one_year_land_cover_reversion_fraction"
                ),
                "interpretation": warnings.get("interpretation"),
            },
            "output_audit": {
                "status": output_audit.get("status"),
                "prediction_count": output_audit.get("prediction_count"),
                "failure_count": output_audit.get("failure_count"),
                "track_counts": output_audit.get("track_counts", {}),
            },
            "input_sources": INPUT_SOURCES,
            "models": models,
            "interpretation": comparison.get("interpretation", []),
            "pareto_frontier": planning.get("pareto_frontier", []),
            "claim_boundary": {
                "supports": protocol.get("claim_boundary", {}).get("supports", []),
                "does_not_support": protocol.get("claim_boundary", {}).get("does_not_support", []),
                "planning": planning.get("claim_boundary", []),
            },
            "required_controls": protocol.get("required_controls", []),
            "figures": list(FIGURES),
            "legend": CLASS_LEGEND,
        }

    def model(self, model_id: str) -> dict[str, Any]:
        if model_id not in MODEL_IDS:
            raise KeyError(model_id)
        comparison = self._read_json("comparison_report.json")
        planning = self._read_json("planning_comparison_report.json")
        run_report = self._read_json(f"artifacts/predictions/{model_id}/report.json")
        training_runs = []
        for row in run_report.get("seeds", []):
            training = dict(row.get("training", {}))
            training.pop("history", None)
            training_runs.append({"seed": row.get("seed"), "training": training})
        pareto = set(planning.get("pareto_frontier", []))
        candidates = self._planning_candidates(planning, model_id)
        for row in candidates:
            row["pareto"] = row.get("candidate_id") in pareto
        return {
            "schema": "gwm.abu_dhabi_land_use_model_presentation.v1",
            "status": run_report.get("status"),
            "benchmark_id": run_report.get("benchmark_id"),
            "model": {"id": model_id, **MODEL_PRESENTATION[model_id]},
            "state_writeback": run_report.get("state_writeback"),
            "test_label_access_during_fit": run_report.get("test_label_access_during_fit"),
            "historical": self._historical_summary(comparison, model_id),
            "training_runs": training_runs,
            "planning": candidates,
            "options": {
                "historical_years": [2023, 2024],
                "planning_years": list(range(2025, 2031)),
                "scenarios": list(SCENARIO_IDS),
                "seeds": list(SEED_IDS),
            },
            "legend": CLASS_LEGEND,
        }

    def resolve_raster(
        self,
        model_id: str,
        *,
        track: str,
        year: int,
        seed: str = "ensemble",
        scenario: str | None = None,
    ) -> Path:
        if seed not in SEED_IDS:
            raise ValueError("unsupported_seed")
        seed_dir = "ensemble" if seed == "ensemble" else f"seed_{seed}"
        if model_id == "observed":
            if track != "historical" or year not in range(2017, 2025):
                raise ValueError("unsupported_observed_raster")
            relative = f"artifacts/gee/land_cover/land_cover_{year}_100m.tif"
        elif model_id not in MODEL_IDS:
            raise KeyError(model_id)
        elif track == "historical":
            if year not in (2023, 2024):
                raise ValueError("unsupported_historical_year")
            relative = f"artifacts/predictions/{model_id}/{seed_dir}/prediction_{year}.tif"
        elif track == "planning":
            if year not in range(2025, 2031):
                raise ValueError("unsupported_planning_year")
            if scenario not in SCENARIO_IDS:
                raise ValueError("unsupported_scenario")
            relative = f"artifacts/planning/{model_id}/{scenario}/{seed_dir}/prediction_{year}.tif"
        else:
            raise ValueError("unsupported_track")
        path = (self.root / relative).resolve()
        if self.root not in path.parents or not path.is_file():
            raise FileNotFoundError(f"abu_dhabi_raster_missing:{relative}")
        return path

    def resolve_figure(self, figure_id: str) -> Path:
        relative = FIGURES.get(figure_id)
        if relative is None:
            raise KeyError(figure_id)
        path = (self.root / relative).resolve()
        if self.root not in path.parents or not path.is_file():
            raise FileNotFoundError(f"abu_dhabi_figure_missing:{figure_id}")
        return path

    def render_raster_png(self, path: Path) -> bytes:
        return _render_land_cover_png(str(path), path.stat().st_mtime_ns)


@lru_cache(maxsize=96)
def _render_land_cover_png(path_string: str, _mtime_ns: int) -> bytes:
    with rasterio.open(path_string) as dataset:
        state = dataset.read(1)
    rgba = np.zeros((*state.shape, 4), dtype=np.uint8)
    for item in CLASS_LEGEND:
        color = item["color"].lstrip("#")
        rgb = tuple(int(color[index : index + 2], 16) for index in (0, 2, 4))
        rgba[state == item["value"]] = (*rgb, 255)
    image = Image.fromarray(rgba, mode="RGBA")
    image = image.resize((image.width * 2, image.height * 2), Image.Resampling.NEAREST)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()

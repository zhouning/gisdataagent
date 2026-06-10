"""WorldModelV21Toolset - Paper9 World Model v2.1 planning tools."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..world_model_v21 import get_world_model_v21_service


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _int_arg(value: str | int, default: int) -> int:
    raw = str(value).strip() if value is not None else ""
    return int(raw) if raw else default


def _optional_float_arg(value: str | float | None) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    return float(raw) if raw else None


def _bool_arg(value: str | bool, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on", "是", "需要", "运行"}


def _default_path(value: str, env_name: str) -> str:
    raw = str(value or "").strip()
    return raw or os.environ.get(env_name, "")


_DATASET_PRESETS = {
    "bishan": {
        "prepared_dir": "/app/bishan-runs/prepared",
        "ensemble_dir": "/app/bishan-runs/prepared/ensemble_seed0",
    },
    "dongxing": {
        "prepared_dir": "/app/dongxing-runs/prepared",
        "ensemble_dir": "/app/dongxing-runs/prepared/ensemble_seed0",
    },
}


def _dataset_key(value: str) -> str:
    raw = str(value or "").strip().lower()
    compact = raw.replace("_", "").replace("-", "").replace(" ", "")
    if compact in {"bishan", "璧山"}:
        return "bishan"
    if compact in {"dongxing", "东兴", "dongxingcity"}:
        return "dongxing"
    return ""


def _dataset_path(value: str, env_name: str, dataset: str, path_key: str) -> str:
    raw = str(value or "").strip()
    if raw:
        return raw
    key = _dataset_key(dataset)
    if key:
        return _DATASET_PRESETS[key][path_key]
    return os.environ.get(env_name, "")


def _env_kind_arg(value: str) -> str:
    raw = str(value or "county").strip().lower()
    compact = raw.replace("_", "").replace("-", "").replace(" ", "")
    if compact == "restoration":
        return "restoration"
    if compact == "county":
        return "county"
    return raw


def world_model_v21_status() -> str:
    """Return Paper9 World Model v2.1 availability, source commit, and defaults.

    Use this before planning to check whether the Paper9 repository, Python
    package, and default prepared/checkpoint directories are available.
    """
    try:
        return _json(get_world_model_v21_service().status())
    except Exception as exc:
        return _json({"error": str(exc)})


def _world_model_v21_plan_sync(
    prepared_dir: str = "",
    ensemble_dir: str = "",
    dataset: str = "",
    env_kind: str = "county",
    horizon: str = "1",
    top_k: str = "1",
    n_episodes: str = "1",
    continuation: str = "greedy",
    scoring: str = "reward",
    threads: str = "0",
    seed_offset: str = "0",
    proj_crs: str = "",
    cultivated_area_floor_delta_ha: str = "",
    baimu_area_floor_delta_ha: str = "",
    gamma_conn: str = "",
    delta_conn: str = "",
) -> str:
    """Run Paper9 World Model v2.1 MPC planning.

    Parameters are string-friendly for local LLM tool calls. Set dataset to
    "bishan" or "dongxing" when the user names one of the demo datasets. If
    prepared_dir or ensemble_dir is blank, the tool uses the dataset preset
    first, then PAPER9_FARMLAND_MPC_DEFAULT_* env vars.
    """
    payload = {
        "prepared_dir": _default_path(
            _dataset_path(
                prepared_dir,
                "PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR",
                dataset,
                "prepared_dir",
            ),
            "PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR",
        ),
        "ensemble_dir": _default_path(
            _dataset_path(
                ensemble_dir,
                "PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR",
                dataset,
                "ensemble_dir",
            ),
            "PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR",
        ),
        "dataset": _dataset_key(dataset) or None,
        "env_kind": _env_kind_arg(env_kind),
        "horizon": _int_arg(horizon, 1),
        "top_k": _int_arg(top_k, 1),
        "n_episodes": _int_arg(n_episodes, 1),
        "continuation": str(continuation or "greedy").strip().lower(),
        "scoring": str(scoring or "reward").strip().lower(),
        "threads": _int_arg(threads, 0),
        "seed_offset": _int_arg(seed_offset, 0),
        "proj_crs": str(proj_crs or "").strip() or None,
        "cultivated_area_floor_delta_ha": _optional_float_arg(
            cultivated_area_floor_delta_ha
        ),
        "baimu_area_floor_delta_ha": _optional_float_arg(
            baimu_area_floor_delta_ha
        ),
        "gamma_conn": _optional_float_arg(gamma_conn),
        "delta_conn": _optional_float_arg(delta_conn),
    }

    try:
        from ..user_context import current_user_id

        result = get_world_model_v21_service().run_plan(
            payload, user_id=current_user_id.get("agent_world_model_v21")
        )
        map_config = result.pop("map_config", None)
        if map_config:
            result["map_update"] = map_config
            result["map_update_queued"] = True
        return _json(result)
    except Exception as exc:
        return _json({"error": str(exc), "payload": payload})


def _world_model_v21_prepare_sync(
    dltb_path: str = "",
    dem_path: str = "",
    prepared_dir: str = "",
    proj_crs: str = "EPSG:32648",
    slope_method: str = "auto",
    run_phase_bc: str = "true",
    min_parcels: str = "3",
    min_area_ha: str = "0.5",
    max_parcels: str = "30",
    min_parcels_per_township: str = "50",
    xzq_path: str = "",
    reference_layer: str = "",
) -> str:
    """Run World Model v2.1 Tool 1 prepare: DLTB+DEM -> prepared_dir."""
    payload = {
        "dltb_path": str(dltb_path or "").strip(),
        "dem_path": str(dem_path or "").strip(),
        "prepared_dir": str(prepared_dir or "").strip(),
        "proj_crs": str(proj_crs or "EPSG:32648").strip(),
        "slope_method": str(slope_method or "auto").strip(),
        "run_phase_bc": _bool_arg(run_phase_bc, True),
        "min_parcels": _int_arg(min_parcels, 3),
        "min_area_ha": _optional_float_arg(min_area_ha) or 0.5,
        "max_parcels": _int_arg(max_parcels, 30),
        "min_parcels_per_township": _int_arg(min_parcels_per_township, 50),
        "xzq_path": str(xzq_path or "").strip() or None,
        "reference_layer": str(reference_layer or "").strip() or None,
    }
    try:
        from ..user_context import current_user_id

        return _json(get_world_model_v21_service().run_prepare(
            payload, user_id=current_user_id.get("agent_world_model_v21")
        ))
    except Exception as exc:
        return _json({"error": str(exc), "payload": payload})


def _world_model_v21_sample_sync(
    prepared_dir: str = "",
    env_kind: str = "county",
    n_transition_episodes: str = "60",
    n_pairwise_states: str = "1000",
    n_pairwise_actions: str = "50",
    seed: str = "0",
    proj_crs: str = "",
) -> str:
    """Run World Model v2.1 Tool 2 sampling: prepared_dir -> tool2/*.npz."""
    payload = {
        "prepared_dir": str(prepared_dir or "").strip(),
        "env_kind": _env_kind_arg(env_kind),
        "n_transition_episodes": _int_arg(n_transition_episodes, 60),
        "n_pairwise_states": _int_arg(n_pairwise_states, 1000),
        "n_pairwise_actions": _int_arg(n_pairwise_actions, 50),
        "seed": _int_arg(seed, 0),
        "proj_crs": str(proj_crs or "").strip() or None,
    }
    try:
        from ..user_context import current_user_id

        return _json(get_world_model_v21_service().run_sample(
            payload, user_id=current_user_id.get("agent_world_model_v21")
        ))
    except Exception as exc:
        return _json({"error": str(exc), "payload": payload})


def _world_model_v21_train_sync(
    prepared_dir: str = "",
    n_members: str = "3",
    epochs: str = "30",
    patience: str = "8",
    lambda_rank: str = "5.0",
    margin: str = "0.1",
    batch_size: str = "256",
    n_pairs_per_state: str = "10",
    pw_subsample: str = "100",
    lr: str = "0.001",
    weight_decay: str = "0.00001",
    val_split: str = "0.1",
    seed_base: str = "0",
    torch_threads: str = "0",
    out_subdir: str = "tool3",
) -> str:
    """Run World Model v2.1 Tool 3 training: tool2 samples -> ONNX ensemble."""
    payload = {
        "prepared_dir": str(prepared_dir or "").strip(),
        "n_members": _int_arg(n_members, 3),
        "epochs": _int_arg(epochs, 30),
        "patience": _int_arg(patience, 8),
        "lambda_rank": _optional_float_arg(lambda_rank) or 5.0,
        "margin": _optional_float_arg(margin) or 0.1,
        "batch_size": _int_arg(batch_size, 256),
        "n_pairs_per_state": _int_arg(n_pairs_per_state, 10),
        "pw_subsample": _int_arg(pw_subsample, 100),
        "lr": _optional_float_arg(lr) or 0.001,
        "weight_decay": _optional_float_arg(weight_decay) or 0.00001,
        "val_split": _optional_float_arg(val_split) or 0.1,
        "seed_base": _int_arg(seed_base, 0),
        "torch_threads": _int_arg(torch_threads, 0),
        "out_subdir": str(out_subdir or "tool3").strip() or "tool3",
    }
    try:
        from ..user_context import current_user_id

        return _json(get_world_model_v21_service().run_train(
            payload, user_id=current_user_id.get("agent_world_model_v21")
        ))
    except Exception as exc:
        return _json({"error": str(exc), "payload": payload})


def _world_model_v21_pipeline_sync(
    dltb_path: str = "",
    dem_path: str = "",
    prepared_dir: str = "",
    ensemble_dir: str = "",
    dataset: str = "",
    reuse_existing: str = "true",
    run_prepare: str = "true",
    run_sample: str = "true",
    run_train: str = "true",
    run_plan: str = "true",
    env_kind: str = "county",
    horizon: str = "1",
    top_k: str = "1",
    n_episodes: str = "1",
    continuation: str = "greedy",
    scoring: str = "reward",
    threads: str = "0",
    proj_crs: str = "EPSG:32648",
    n_transition_episodes: str = "60",
    n_pairwise_states: str = "1000",
    n_pairwise_actions: str = "50",
    n_members: str = "3",
    epochs: str = "30",
    out_subdir: str = "tool3",
) -> str:
    """Run/reuse the full World Model v2.1 A->B->C->D pipeline.

    Set dataset to "bishan" or "dongxing" when the user names one of the demo
    datasets. Blank prepared_dir/ensemble_dir values are resolved from the
    dataset preset before falling back to Docker environment defaults.
    """
    payload = {
        "dltb_path": str(dltb_path or "").strip(),
        "dem_path": str(dem_path or "").strip(),
        "prepared_dir": _dataset_path(
            prepared_dir,
            "PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR",
            dataset,
            "prepared_dir",
        ),
        "ensemble_dir": _dataset_path(
            ensemble_dir,
            "PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR",
            dataset,
            "ensemble_dir",
        ),
        "dataset": _dataset_key(dataset) or None,
        "reuse_existing": _bool_arg(reuse_existing, True),
        "run_prepare": _bool_arg(run_prepare, True),
        "run_sample": _bool_arg(run_sample, True),
        "run_train": _bool_arg(run_train, True),
        "run_plan": _bool_arg(run_plan, True),
        "env_kind": _env_kind_arg(env_kind),
        "horizon": _int_arg(horizon, 1),
        "top_k": _int_arg(top_k, 1),
        "n_episodes": _int_arg(n_episodes, 1),
        "continuation": str(continuation or "greedy").strip().lower(),
        "scoring": str(scoring or "reward").strip().lower(),
        "threads": _int_arg(threads, 0),
        "proj_crs": str(proj_crs or "").strip() or None,
        "n_transition_episodes": _int_arg(n_transition_episodes, 60),
        "n_pairwise_states": _int_arg(n_pairwise_states, 1000),
        "n_pairwise_actions": _int_arg(n_pairwise_actions, 50),
        "n_members": _int_arg(n_members, 3),
        "epochs": _int_arg(epochs, 30),
        "out_subdir": str(out_subdir or "tool3").strip() or "tool3",
    }
    try:
        from ..user_context import current_user_id

        result = get_world_model_v21_service().run_pipeline(
            payload, user_id=current_user_id.get("agent_world_model_v21")
        )
        plan_result = result.get("plan_result") or {}
        map_config = plan_result.pop("map_config", None)
        if map_config:
            plan_result["map_update"] = map_config
            plan_result["map_update_queued"] = True
        return _json(result)
    except Exception as exc:
        return _json({"error": str(exc), "payload": payload})


async def world_model_v21_plan(
    prepared_dir: str = "",
    ensemble_dir: str = "",
    dataset: str = "",
    env_kind: str = "county",
    horizon: str = "1",
    top_k: str = "1",
    n_episodes: str = "1",
    continuation: str = "greedy",
    scoring: str = "reward",
    threads: str = "0",
    seed_offset: str = "0",
    proj_crs: str = "",
    cultivated_area_floor_delta_ha: str = "",
    baimu_area_floor_delta_ha: str = "",
    gamma_conn: str = "",
    delta_conn: str = "",
) -> str:
    """Run Paper9 World Model v2.1 MPC planning as a long-running ADK tool.

    dataset accepts "bishan" or "dongxing" and controls default paths when
    prepared_dir/ensemble_dir are omitted.
    """
    return await asyncio.to_thread(
        _world_model_v21_plan_sync,
        prepared_dir,
        ensemble_dir,
        dataset,
        env_kind,
        horizon,
        top_k,
        n_episodes,
        continuation,
        scoring,
        threads,
        seed_offset,
        proj_crs,
        cultivated_area_floor_delta_ha,
        baimu_area_floor_delta_ha,
        gamma_conn,
        delta_conn,
    )


async def world_model_v21_prepare(
    dltb_path: str = "",
    dem_path: str = "",
    prepared_dir: str = "",
    proj_crs: str = "EPSG:32648",
    slope_method: str = "auto",
    run_phase_bc: str = "true",
    min_parcels: str = "3",
    min_area_ha: str = "0.5",
    max_parcels: str = "30",
    min_parcels_per_township: str = "50",
    xzq_path: str = "",
    reference_layer: str = "",
) -> str:
    """Run Paper9 Tool 1 prepare as a long-running ADK tool."""
    return await asyncio.to_thread(
        _world_model_v21_prepare_sync,
        dltb_path,
        dem_path,
        prepared_dir,
        proj_crs,
        slope_method,
        run_phase_bc,
        min_parcels,
        min_area_ha,
        max_parcels,
        min_parcels_per_township,
        xzq_path,
        reference_layer,
    )


async def world_model_v21_sample(
    prepared_dir: str = "",
    env_kind: str = "county",
    n_transition_episodes: str = "60",
    n_pairwise_states: str = "1000",
    n_pairwise_actions: str = "50",
    seed: str = "0",
    proj_crs: str = "",
) -> str:
    """Run Paper9 Tool 2 sampling as a long-running ADK tool."""
    return await asyncio.to_thread(
        _world_model_v21_sample_sync,
        prepared_dir,
        env_kind,
        n_transition_episodes,
        n_pairwise_states,
        n_pairwise_actions,
        seed,
        proj_crs,
    )


async def world_model_v21_train(
    prepared_dir: str = "",
    n_members: str = "3",
    epochs: str = "30",
    patience: str = "8",
    lambda_rank: str = "5.0",
    margin: str = "0.1",
    batch_size: str = "256",
    n_pairs_per_state: str = "10",
    pw_subsample: str = "100",
    lr: str = "0.001",
    weight_decay: str = "0.00001",
    val_split: str = "0.1",
    seed_base: str = "0",
    torch_threads: str = "0",
    out_subdir: str = "tool3",
) -> str:
    """Run Paper9 Tool 3 training as a long-running ADK tool."""
    return await asyncio.to_thread(
        _world_model_v21_train_sync,
        prepared_dir,
        n_members,
        epochs,
        patience,
        lambda_rank,
        margin,
        batch_size,
        n_pairs_per_state,
        pw_subsample,
        lr,
        weight_decay,
        val_split,
        seed_base,
        torch_threads,
        out_subdir,
    )


async def world_model_v21_pipeline(
    dltb_path: str = "",
    dem_path: str = "",
    prepared_dir: str = "",
    ensemble_dir: str = "",
    dataset: str = "",
    reuse_existing: str = "true",
    run_prepare: str = "true",
    run_sample: str = "true",
    run_train: str = "true",
    run_plan: str = "true",
    env_kind: str = "county",
    horizon: str = "1",
    top_k: str = "1",
    n_episodes: str = "1",
    continuation: str = "greedy",
    scoring: str = "reward",
    threads: str = "0",
    proj_crs: str = "EPSG:32648",
    n_transition_episodes: str = "60",
    n_pairwise_states: str = "1000",
    n_pairwise_actions: str = "50",
    n_members: str = "3",
    epochs: str = "30",
    out_subdir: str = "tool3",
) -> str:
    """Run/reuse Paper9 Tools 1-4 as one long-running ADK tool.

    dataset accepts "bishan" or "dongxing" and controls default paths when
    prepared_dir/ensemble_dir are omitted.
    """
    return await asyncio.to_thread(
        _world_model_v21_pipeline_sync,
        dltb_path,
        dem_path,
        prepared_dir,
        ensemble_dir,
        dataset,
        reuse_existing,
        run_prepare,
        run_sample,
        run_train,
        run_plan,
        env_kind,
        horizon,
        top_k,
        n_episodes,
        continuation,
        scoring,
        threads,
        proj_crs,
        n_transition_episodes,
        n_pairwise_states,
        n_pairwise_actions,
        n_members,
        epochs,
        out_subdir,
    )


world_model_v21_plan.__name__ = "world_model_v21_plan"
world_model_v21_plan.__qualname__ = "world_model_v21_plan"
world_model_v21_prepare.__name__ = "world_model_v21_prepare"
world_model_v21_prepare.__qualname__ = "world_model_v21_prepare"
world_model_v21_sample.__name__ = "world_model_v21_sample"
world_model_v21_sample.__qualname__ = "world_model_v21_sample"
world_model_v21_train.__name__ = "world_model_v21_train"
world_model_v21_train.__qualname__ = "world_model_v21_train"
world_model_v21_pipeline.__name__ = "world_model_v21_pipeline"
world_model_v21_pipeline.__qualname__ = "world_model_v21_pipeline"


_SYNC_FUNCS = [world_model_v21_status]
_LONG_RUNNING_FUNCS = [
    world_model_v21_prepare,
    world_model_v21_sample,
    world_model_v21_train,
    world_model_v21_plan,
    world_model_v21_pipeline,
]


class WorldModelV21Toolset(BaseToolset):
    """Paper9 World Model v2.1 tools for source status and MPC planning."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _SYNC_FUNCS] + [
            LongRunningFunctionTool(f) for f in _LONG_RUNNING_FUNCS
        ]
        if self.tool_filter is None:
            return all_tools
        return [
            t for t in all_tools if self._is_tool_selected(t, readonly_context)
        ]

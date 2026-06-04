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


def _default_path(value: str, env_name: str) -> str:
    raw = str(value or "").strip()
    return raw or os.environ.get(env_name, "")


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
    env_kind: str = "county",
    horizon: str = "5",
    top_k: str = "50",
    n_episodes: str = "1",
    continuation: str = "random",
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

    Parameters are string-friendly for local LLM tool calls. If prepared_dir or
    ensemble_dir is blank, the tool uses PAPER9_FARMLAND_MPC_DEFAULT_* env vars.
    """
    payload = {
        "prepared_dir": _default_path(
            prepared_dir, "PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR"
        ),
        "ensemble_dir": _default_path(
            ensemble_dir, "PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR"
        ),
        "env_kind": _env_kind_arg(env_kind),
        "horizon": _int_arg(horizon, 5),
        "top_k": _int_arg(top_k, 50),
        "n_episodes": _int_arg(n_episodes, 1),
        "continuation": str(continuation or "random").strip().lower(),
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


async def world_model_v21_plan(
    prepared_dir: str = "",
    ensemble_dir: str = "",
    env_kind: str = "county",
    horizon: str = "5",
    top_k: str = "50",
    n_episodes: str = "1",
    continuation: str = "random",
    scoring: str = "reward",
    threads: str = "0",
    seed_offset: str = "0",
    proj_crs: str = "",
    cultivated_area_floor_delta_ha: str = "",
    baimu_area_floor_delta_ha: str = "",
    gamma_conn: str = "",
    delta_conn: str = "",
) -> str:
    """Run Paper9 World Model v2.1 MPC planning as a long-running ADK tool."""
    return await asyncio.to_thread(
        _world_model_v21_plan_sync,
        prepared_dir,
        ensemble_dir,
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


world_model_v21_plan.__name__ = "world_model_v21_plan"
world_model_v21_plan.__qualname__ = "world_model_v21_plan"


_SYNC_FUNCS = [world_model_v21_status]
_LONG_RUNNING_FUNCS = [world_model_v21_plan]


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

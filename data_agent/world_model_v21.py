"""World Model v2.1 adapter for Paper9 arcgis-farmland-mpc.

This module intentionally keeps Paper9 as the algorithm source of truth. It
loads the local Paper9 checkout lazily so GIS Data Agent can still start when
the Paper9 repo or its optional dependencies are absent.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

VERSION = "2.1.0"
DEFAULT_REPO = Path(r"D:\test\_publish\arcgis-farmland-mpc")

_instance_lock = threading.Lock()
_instance = None


class WorldModelV21Error(Exception):
    status_code = 500


class WorldModelV21ValidationError(WorldModelV21Error):
    status_code = 400


class WorldModelV21UnavailableError(WorldModelV21Error):
    status_code = 503


def get_world_model_v21_service():
    """Return singleton WorldModelV21Service instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = WorldModelV21Service()
    return _instance


class WorldModelV21Service:
    """Thin adapter around Paper9 Tool 4 MPC planning."""

    def __init__(self, repo_path: str | Path | None = None):
        raw = repo_path or os.environ.get("PAPER9_FARMLAND_MPC_REPO") or DEFAULT_REPO
        self.repo_path = Path(raw)

    def status(self) -> dict[str, Any]:
        """Return Paper9 source and capability status without running MPC."""
        repo_exists = self.repo_path.is_dir()
        import_info = self._import_paper9() if repo_exists else {
            "importable": False,
            "package_version": None,
            "error": "Paper9 repository not found",
        }
        defaults = {
            "prepared_dir": os.environ.get(
                "PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR", ""
            ),
            "ensemble_dir": os.environ.get(
                "PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR", ""
            ),
            "out_dir_policy": "per-user timestamped uploads directory",
        }
        onnx_count = 0
        if defaults["ensemble_dir"]:
            onnx_count = len(self.find_onnx_members(defaults["ensemble_dir"]))

        ready = repo_exists and import_info["importable"]
        return {
            "status": "ready" if ready else "unavailable",
            "version": VERSION,
            "paper9": {
                "repo_path": str(self.repo_path),
                "repo_exists": repo_exists,
                "remote": self._git(["config", "--get", "remote.origin.url"]),
                "commit": self._git(["rev-parse", "HEAD"]),
                "commit_date": self._git(["show", "-s", "--format=%ci", "HEAD"]),
                **import_info,
            },
            "defaults": defaults,
            "capabilities": {
                "tool4_plan": ready,
                "prepare_sample_train": False,
                "onnx_inference": ready,
                "county_env": True,
                "restoration_env": True,
                "cultivated_area_floor": True,
                "baimu_area_floor": True,
            },
            "onnx_member_count": onnx_count,
        }

    def find_onnx_members(self, ensemble_dir: str | Path) -> list[Path]:
        """Return ONNX ensemble members from standard or shipped Paper9 names."""
        root = Path(ensemble_dir)
        if not root.is_dir():
            return []
        members = sorted(root.glob("*.onnx"), key=lambda p: p.name)
        return [p for p in members if "member" in p.stem]

    def validate_plan_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize a Tool 4 planning payload."""
        prepared_dir = self._required_existing_dir(payload, "prepared_dir")
        ensemble_dir = self._required_existing_dir(payload, "ensemble_dir")
        members = self.find_onnx_members(ensemble_dir)
        if not members:
            raise WorldModelV21ValidationError(
                f"No ONNX ensemble members found under {ensemble_dir}"
            )

        horizon = self._int_range(payload, "horizon", 5, 1, 20)
        top_k = self._int_range(payload, "top_k", 50, 1, 500)
        n_episodes = self._int_range(payload, "n_episodes", 1, 1, 20)

        continuation = str(payload.get("continuation", "random")).strip().lower()
        if continuation not in {"random", "greedy"}:
            raise WorldModelV21ValidationError(
                "continuation must be 'random' or 'greedy'"
            )

        scoring = str(payload.get("scoring", "reward")).strip().lower()
        if scoring == "slope_only":
            scoring = "slope"
        if scoring not in {"reward", "slope"}:
            raise WorldModelV21ValidationError("scoring must be 'reward' or 'slope'")

        env_kind = str(payload.get("env_kind", "county")).strip().lower()
        if env_kind not in {"county", "restoration"}:
            raise WorldModelV21ValidationError(
                "env_kind must be 'county' or 'restoration'"
            )

        return {
            "prepared_dir": prepared_dir,
            "ensemble_dir": ensemble_dir,
            "onnx_members": members,
            "horizon": horizon,
            "top_k": top_k,
            "n_episodes": n_episodes,
            "continuation": continuation,
            "scoring": scoring,
            "env_kind": env_kind,
            "threads": self._int_range(payload, "threads", 0, 0, 64),
            "proj_crs": payload.get("proj_crs") or None,
            "seed_offset": self._int_range(payload, "seed_offset", 0, 0, 1_000_000),
            "cultivated_area_floor_delta_ha": self._optional_float(
                payload, "cultivated_area_floor_delta_ha"
            ),
            "baimu_area_floor_delta_ha": self._optional_float(
                payload, "baimu_area_floor_delta_ha"
            ),
            "gamma_conn": self._optional_float(payload, "gamma_conn"),
            "delta_conn": self._optional_float(payload, "delta_conn"),
        }

    def _import_paper9(self) -> dict[str, Any]:
        repo = str(self.repo_path)
        if repo not in sys.path:
            sys.path.insert(0, repo)
        try:
            package = importlib.import_module("farmland_mpc")
            return {
                "importable": True,
                "package_version": getattr(package, "__version__", None),
                "error": None,
            }
        except Exception as exc:
            return {
                "importable": False,
                "package_version": None,
                "error": str(exc),
            }

    def _git(self, args: list[str]) -> str | None:
        if not self.repo_path.is_dir():
            return None
        try:
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    f"safe.directory={self.repo_path.as_posix()}",
                    "-C",
                    str(self.repo_path),
                    *args,
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _required_existing_dir(self, payload: dict[str, Any], key: str) -> Path:
        raw = str(payload.get(key, "")).strip()
        if not raw:
            raise WorldModelV21ValidationError(f"{key} is required")
        path = Path(raw)
        if not path.is_dir():
            raise WorldModelV21ValidationError(f"{key} not found: {path}")
        return path

    def _int_range(
        self,
        payload: dict[str, Any],
        key: str,
        default: int,
        min_value: int,
        max_value: int,
    ) -> int:
        raw = payload.get(key, default)
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise WorldModelV21ValidationError(
                f"{key} must be between {min_value} and {max_value}"
            ) from exc
        if value < min_value or value > max_value:
            raise WorldModelV21ValidationError(
                f"{key} must be between {min_value} and {max_value}"
            )
        return value

    def _optional_float(self, payload: dict[str, Any], key: str) -> float | None:
        raw = payload.get(key)
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise WorldModelV21ValidationError(f"{key} must be numeric") from exc

"""World Model v2.1 adapter for Paper9 arcgis-farmland-mpc.

This module intentionally keeps Paper9 as the algorithm source of truth. It
loads the local Paper9 checkout lazily so GIS Data Agent can still start when
the Paper9 repo or its optional dependencies are absent.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
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

    def run_plan(self, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
        """Run Paper9 Tool 4 MPC planning and return normalized JSON."""
        cfg = self.validate_plan_request(payload)
        plan_run = self._load_paper9_plan_run()
        out_dir = self._new_output_dir(user_id)

        output_fc = out_dir / "optimized_dltb.shp"
        input_dltb_fc = (
            cfg["prepared_dir"] / "dem_slope_analysis" / "output" / "DLTB_with_slope.shp"
        )
        output_fc_arg = (
            str(output_fc)
            if cfg["env_kind"] == "county" and input_dltb_fc.exists()
            else None
        )

        try:
            summary = plan_run(
                ensemble_dir=str(cfg["ensemble_dir"]),
                out_dir=str(out_dir),
                horizon=cfg["horizon"],
                top_k=cfg["top_k"],
                n_episodes=cfg["n_episodes"],
                continuation=cfg["continuation"],
                scoring=cfg["scoring"],
                threads=cfg["threads"],
                seed_offset=cfg["seed_offset"],
                prepared_dir=str(cfg["prepared_dir"]),
                proj_crs=cfg["proj_crs"],
                env_kind=cfg["env_kind"],
                output_fc=output_fc_arg,
                input_dltb_fc=str(input_dltb_fc) if output_fc_arg else None,
                cultivated_area_floor_delta_ha=cfg[
                    "cultivated_area_floor_delta_ha"
                ],
                baimu_area_floor_delta_ha=cfg["baimu_area_floor_delta_ha"],
                gamma_conn=cfg["gamma_conn"],
                delta_conn=cfg["delta_conn"],
            )
        except WorldModelV21Error:
            raise
        except Exception as exc:
            raise WorldModelV21UnavailableError(str(exc)) from exc

        warnings: list[str] = []
        map_layer = None
        if output_fc_arg:
            map_layer = self._convert_optimized_shp_to_fgb(output_fc, out_dir, warnings)
        elif (out_dir / "mpc_land_use.npy").exists():
            map_layer = self._build_restoration_grid_geojson(
                cfg["prepared_dir"], out_dir, out_dir / "mpc_land_use.npy", warnings
            )

        artifacts = {
            "summary_json": "mpc_summary.json"
            if (out_dir / "mpc_summary.json").exists()
            else None,
            "land_use_npy": "mpc_land_use.npy"
            if (out_dir / "mpc_land_use.npy").exists()
            else None,
            "optimized_shp": output_fc.name if output_fc.exists() else None,
            "map_layer": self._upload_relative_path(map_layer) if map_layer else None,
        }
        return {
            "status": "ok",
            "version": VERSION,
            "source": "arcgis-farmland-mpc",
            "mode": "tool4_mpc",
            "env_kind": cfg["env_kind"],
            "prepared_dir": str(cfg["prepared_dir"]),
            "ensemble_dir": str(cfg["ensemble_dir"]),
            "out_dir": str(out_dir),
            "summary": self._normalize_summary(summary),
            "artifacts": artifacts,
            "map_config": self._build_map_config(map_layer) if map_layer else None,
            "map_update_queued": False,
            "warnings": warnings,
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

    def _load_paper9_plan_run(self):
        info = self._import_paper9()
        if not info["importable"]:
            raise WorldModelV21UnavailableError(info["error"] or "Paper9 import failed")
        from farmland_mpc.mpc_plan import run

        return run

    def _new_output_dir(self, user_id: str) -> Path:
        safe_user = re.sub(r"[^A-Za-z0-9_.-]+", "_", user_id or "anonymous")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_dir = (
            Path(__file__).resolve().parent
            / "uploads"
            / safe_user
            / "world_model_v21"
            / stamp
        )
        out_dir.mkdir(parents=True, exist_ok=False)
        return out_dir

    def _normalize_summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        results = summary.get("results") or []
        first = results[0] if results else {}
        aggregate = summary.get("aggregate") or {}
        config = summary.get("config") or {}
        return {
            "total_reward": first.get("total_reward"),
            "steps_run": first.get("steps_run"),
            "swaps_completed": first.get("swaps_completed"),
            "n_selected": first.get("n_selected"),
            "budget_used": first.get("budget_used"),
            "budget_fraction_used": first.get("budget_fraction_used"),
            "slope_change_pct": first.get(
                "slope_change_pct", aggregate.get("slope_pct_mean")
            ),
            "cont_change": first.get("cont_change", aggregate.get("cont_mean")),
            "baimu_area_change_ha": first.get(
                "baimu_area_change_ha", aggregate.get("baimu_ha_mean")
            ),
            "n_episodes": config.get("n_episodes"),
            "n_blocks": config.get("n_blocks"),
            "n_parcels": config.get("n_parcels"),
            "max_steps": config.get("max_steps"),
            "ensemble_members": (summary.get("ensemble") or {}).get("n_members"),
        }

    def _convert_optimized_shp_to_fgb(
        self, optimized_shp: Path, out_dir: Path, warnings: list[str]
    ) -> Path | None:
        if not optimized_shp.exists():
            warnings.append(f"optimized shapefile not found: {optimized_shp}")
            return None
        try:
            import geopandas as gpd

            gdf = gpd.read_file(optimized_shp)
            if gdf.crs is not None:
                gdf = gdf.to_crs(epsg=4326)
            map_layer = out_dir / "optimized_dltb.fgb"
            gdf.to_file(map_layer, driver="FlatGeobuf")
            return map_layer
        except Exception as exc:
            warnings.append(f"map conversion failed: {exc}")
            return None

    def _build_restoration_grid_geojson(
        self,
        prepared_dir: Path,
        out_dir: Path,
        land_use_npy: Path,
        warnings: list[str],
    ) -> Path | None:
        attrs_path = prepared_dir / "attributes.csv"
        if not attrs_path.exists():
            warnings.append(f"restoration attributes not found: {attrs_path}")
            return None
        try:
            import geopandas as gpd
            import numpy as np
            import pandas as pd
            from shapely.geometry import box

            attrs = pd.read_csv(attrs_path)
            selected = np.load(land_use_npy)
            if len(attrs) != len(selected):
                warnings.append(
                    f"land use length mismatch: attrs={len(attrs)} selected={len(selected)}"
                )
                return None

            max_row = int(attrs["row"].max())
            # Approximate Buchanan VA 2 km planning grid. The source prepared
            # data is tabular row/col, so this builds a stable display grid.
            origin_lng = -82.45
            origin_lat = 37.00
            cell_lng = 0.0225
            cell_lat = 0.0180

            geometries = []
            selected_values = []
            labels = []
            opt_codes = []
            for idx, row in attrs.iterrows():
                r = int(row["row"])
                c = int(row["col"])
                min_lng = origin_lng + c * cell_lng
                max_lng = min_lng + cell_lng
                min_lat = origin_lat + (max_row - r) * cell_lat
                max_lat = min_lat + cell_lat
                geometries.append(box(min_lng, min_lat, max_lng, max_lat))
                is_selected = int(selected[idx]) == 1
                selected_values.append(1 if is_selected else 0)
                labels.append("selected" if is_selected else "not_selected")
                opt_codes.append("031" if is_selected else "011")

            gdf = gpd.GeoDataFrame(
                attrs.copy(),
                geometry=geometries,
                crs="EPSG:4326",
            )
            gdf["selected"] = selected_values
            gdf["selected_label"] = labels
            gdf["OPT_DLBM"] = opt_codes
            out_path = out_dir / "restoration_mpc_units.geojson"
            gdf.to_file(out_path, driver="GeoJSON")
            return out_path
        except Exception as exc:
            warnings.append(f"restoration grid map failed: {exc}")
            return None

    def _build_map_config(self, map_layer: Path) -> dict[str, Any]:
        center, zoom = self._map_view_from_layer(map_layer)
        rel_path = self._upload_relative_path(map_layer)
        if map_layer.suffix.lower() == ".fgb":
            layer_ref = {
                "type": "fgb",
                "fgb": rel_path,
                "category_column": "OPT_DLBM",
                "style_map": {
                    "011": {
                        "fillColor": "#FFD166",
                        "color": "#B7791F",
                        "fillOpacity": 0.7,
                        "weight": 0.4,
                    },
                    "031": {
                        "fillColor": "#2F855A",
                        "color": "#276749",
                        "fillOpacity": 0.7,
                        "weight": 0.4,
                    },
                },
            }
        else:
            layer_ref = {
                "type": "categorized",
                "geojson": rel_path,
                "category_column": "selected_label",
                "category_labels": {
                    "selected": "MPC selected",
                    "not_selected": "Not selected",
                },
                "style_map": {
                    "selected": {
                        "fillColor": "#2F855A",
                        "color": "#14532D",
                        "fillOpacity": 0.82,
                        "weight": 0.7,
                    },
                    "not_selected": {
                        "fillColor": "#CBD5E1",
                        "color": "#64748B",
                        "fillOpacity": 0.28,
                        "weight": 0.25,
                    },
                },
            }
        return {
            "layers": [
                {
                    "name": "World Model v2.1 optimized",
                    "visible": True,
                    **layer_ref,
                }
            ],
            "center": center,
            "zoom": zoom,
        }

    def _upload_relative_path(self, path: Path) -> str:
        uploads_base = Path(__file__).resolve().parent / "uploads"
        try:
            rel = path.resolve().relative_to(uploads_base.resolve())
            # /uploads/<user>/<path> is served as /api/user/files/<path>
            # for the current user, so strip the user directory.
            if len(rel.parts) > 1:
                return Path(*rel.parts[1:]).as_posix()
            return rel.as_posix()
        except Exception:
            return path.name

    def _map_view_from_layer(self, map_layer: Path) -> tuple[list[float] | None, int]:
        try:
            import geopandas as gpd

            gdf = gpd.read_file(map_layer)
            if gdf.empty:
                return None, 12
            if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            minx, miny, maxx, maxy = [float(v) for v in gdf.total_bounds]
            center = [(miny + maxy) / 2.0, (minx + maxx) / 2.0]
            return center, self._estimate_zoom_from_extent(minx, miny, maxx, maxy)
        except Exception:
            return None, 12

    def _estimate_zoom_from_extent(
        self, min_lng: float, min_lat: float, max_lng: float, max_lat: float
    ) -> int:
        span = max(abs(max_lng - min_lng), abs(max_lat - min_lat))
        if span >= 1.0:
            return 8
        if span >= 0.5:
            return 9
        if span >= 0.18:
            return 10
        if span >= 0.09:
            return 11
        if span >= 0.045:
            return 12
        if span >= 0.022:
            return 13
        if span >= 0.011:
            return 14
        if span >= 0.006:
            return 15
        return 16

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

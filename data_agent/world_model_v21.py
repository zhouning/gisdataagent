"""World Model v2.1 adapter for Paper9 arcgis-farmland-mpc.

This module intentionally keeps Paper9 as the algorithm source of truth. It
loads the local Paper9 checkout lazily so GIS Data Agent can still start when
the Paper9 repo or its optional dependencies are absent.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .paper9_agent_governance import (
    EXPECTED_ALGORITHM_VERSION,
    EXPECTED_PACKAGE_VERSION,
    Paper9AuditPolicy,
    Paper9EpisodeStore,
    audit_paper9_run,
)

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
        proj_data_dir = self._ensure_proj_data_dir()
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
        version_compatible = bool(
            ready
            and import_info.get("package_version") == EXPECTED_PACKAGE_VERSION
            and import_info.get("algorithm_version") == EXPECTED_ALGORITHM_VERSION
            and import_info.get("source_matches_repo", True)
        )
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
                "tool1_prepare": ready,
                "tool2_sample": ready,
                "tool3_train": ready,
                "tool4_plan": ready,
                "pipeline_a_to_d": ready,
                "prepare_sample_train": ready,
                "onnx_inference": ready,
                "county_env": True,
                "restoration_env": True,
                "cultivated_area_floor": True,
                "baimu_area_floor": True,
                "hard_gate_audit": True,
                "bounded_replan": True,
                "verified_episode_memory": True,
            },
            "finals": {
                "expected_package_version": EXPECTED_PACKAGE_VERSION,
                "expected_algorithm_version": EXPECTED_ALGORITHM_VERSION,
                "version_compatible": version_compatible,
                "ready": version_compatible,
            },
            "runtime": {
                "proj_data_dir": proj_data_dir,
            },
            "onnx_member_count": onnx_count,
        }

    def inspect_resources(
        self,
        *,
        dataset: str,
        prepared_dir: str,
        ensemble_dir: str,
    ) -> dict[str, Any]:
        """Inspect version binding and reusable artifacts without executing MPC."""

        status = self.status()
        prepared = Path(prepared_dir).expanduser() if prepared_dir else None
        ensemble = Path(ensemble_dir).expanduser() if ensemble_dir else None
        stages = {
            "prepare": {
                "ready": bool(prepared and self._prepared_ready(prepared)),
                "path": str(prepared) if prepared else None,
            },
            "sample": {
                "ready": bool(prepared and self._sample_ready(prepared)),
                "path": str(prepared / "tool2") if prepared else None,
            },
            "train": {
                "ready": bool(ensemble and self.find_onnx_members(ensemble)),
                "path": str(ensemble) if ensemble else None,
                "onnx_member_count": len(self.find_onnx_members(ensemble))
                if ensemble
                else 0,
            },
        }
        reusable = [name for name, detail in stages.items() if detail["ready"]]
        required = [name for name, detail in stages.items() if not detail["ready"]]
        planning_ready = bool(
            status.get("finals", {}).get("version_compatible")
            and stages["prepare"]["ready"]
            and stages["train"]["ready"]
        )
        land_use_contract = None
        if prepared:
            input_dltb = (
                prepared / "dem_slope_analysis" / "output" / "DLTB_with_slope.shp"
            )
            if input_dltb.is_file():
                try:
                    land_use_contract = self._detect_land_use_code_contract(input_dltb)
                except Exception as exc:
                    land_use_contract = {"compatible": False, "error": str(exc)}
                    planning_ready = False
        return {
            "status": "ready" if planning_ready else "needs_action",
            "dataset": dataset or None,
            "version": status.get("version"),
            "paper9": status.get("paper9"),
            "finals": status.get("finals"),
            "stages": stages,
            "reusable_stages": reusable,
            "required_stages": required,
            "land_use_code_contract": land_use_contract,
            "planning_ready": planning_ready,
            "recommended_next_action": "run_plan"
            if planning_ready
            else "repair_version_or_missing_stages",
        }

    def audit_run(
        self,
        *,
        out_dir: str,
        attempt: int = 0,
        cultivated_area_floor_delta_ha: float = 0.0,
    ) -> dict[str, Any]:
        """Apply deterministic hard gates and return a bounded recovery branch."""

        return audit_paper9_run(
            out_dir,
            policy=Paper9AuditPolicy(
                cultivated_area_floor_delta_ha=cultivated_area_floor_delta_ha,
                max_replans=1,
            ),
            attempt=attempt,
        )

    def recall_verified_episodes(
        self, *, dataset: str = "", limit: int = 3
    ) -> dict[str, Any]:
        """Recall only episodes that previously passed all deterministic gates."""

        episodes = Paper9EpisodeStore().recall(dataset=dataset, limit=limit)
        return {
            "status": "ok",
            "dataset": dataset or None,
            "count": len(episodes),
            "episodes": episodes,
        }

    def commit_verified_episode(
        self,
        *,
        out_dir: str,
        dataset: str,
        goal: str,
        plan_args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Commit an audited run; failed or incomplete runs are rejected."""

        root = Path(out_dir).expanduser().resolve()
        audit_path = root / "paper9_agent_audit.json"
        if not audit_path.is_file():
            raise WorldModelV21ValidationError(
                f"paper9_agent_audit.json not found under {root}; audit the run first"
            )
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        status = self.status()
        paper9 = status.get("paper9") or {}
        record = Paper9EpisodeStore().commit(
            audit=audit,
            dataset=dataset,
            goal=goal,
            plan_args=plan_args,
            provenance={
                "adapter_version": VERSION,
                "package_version": paper9.get("package_version"),
                "algorithm_name": paper9.get("algorithm_name"),
                "algorithm_version": paper9.get("algorithm_version"),
                "paper9_commit": paper9.get("commit"),
            },
        )
        return {"status": "committed", "episode": record}

    def run_prepare(self, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
        """Run Paper9 Tool 1 data preparation and return normalized JSON."""
        self._ensure_proj_data_dir()
        prepare_run = self._load_paper9_prepare_run()
        dltb_path = self._required_existing_file(payload, "dltb_path")
        dem_path = self._required_existing_file(payload, "dem_path")
        prepared_dir = self._optional_output_dir(
            payload,
            "prepared_dir",
            user_id,
            "prepared",
        )
        kwargs = {
            "dltb_path": str(dltb_path),
            "dem_path": str(dem_path),
            "prepared_dir": str(prepared_dir),
            "proj_crs": str(payload.get("proj_crs") or "EPSG:32648"),
            "dlbm_field": str(payload.get("dlbm_field") or "DLBM"),
            "qsdwdm_field": str(payload.get("qsdwdm_field") or "QSDWDM"),
            "bsm_field": str(payload.get("bsm_field") or "BSM"),
            "slope_method": str(payload.get("slope_method") or "auto"),
            "run_phase_bc": bool(payload.get("run_phase_bc", True)),
            "min_parcels": self._int_range(payload, "min_parcels", 3, 1, 1000),
            "min_area_ha": self._optional_float(payload, "min_area_ha") or 0.5,
            "max_parcels": self._int_range(payload, "max_parcels", 30, 1, 5000),
            "min_parcels_per_township": self._int_range(
                payload, "min_parcels_per_township", 50, 1, 100000
            ),
            "xzq_path": payload.get("xzq_path") or None,
            "reference_layer": payload.get("reference_layer") or None,
        }
        try:
            output_path = prepare_run(**kwargs)
        except Exception as exc:
            raise WorldModelV21UnavailableError(str(exc)) from exc

        summary = self._read_json(prepared_dir / "prepare_data_summary.json")
        return {
            "status": "ok",
            "version": VERSION,
            "source": "arcgis-farmland-mpc",
            "mode": "tool1_prepare",
            "prepared_dir": str(prepared_dir),
            "output_path": str(output_path),
            "summary": summary,
            "artifacts": {
                "dltb_with_slope": self._relative_to(output_path, prepared_dir),
                "prepare_summary": "prepare_data_summary.json"
                if (prepared_dir / "prepare_data_summary.json").exists()
                else None,
                "townships": "townships.json"
                if (prepared_dir / "townships.json").exists()
                else None,
            },
        }

    def run_sample(self, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
        """Run Paper9 Tool 2 transition/pairwise sampling."""
        self._ensure_proj_data_dir()
        sample_run = self._load_paper9_sample_run()
        prepared_dir = self._required_existing_dir(payload, "prepared_dir")
        kwargs = {
            "prepared_dir": str(prepared_dir),
            "n_transition_episodes": self._int_range(
                payload, "n_transition_episodes", 60, 1, 10000
            ),
            "n_pairwise_states": self._int_range(
                payload, "n_pairwise_states", 1000, 1, 200000
            ),
            "n_pairwise_actions": self._int_range(
                payload, "n_pairwise_actions", 50, 1, 10000
            ),
            "seed": self._int_range(payload, "seed", 0, 0, 1_000_000),
            "proj_crs": payload.get("proj_crs") or None,
            "env_kind": str(payload.get("env_kind") or "county").strip().lower(),
        }
        try:
            summary = sample_run(**kwargs)
        except Exception as exc:
            raise WorldModelV21UnavailableError(str(exc)) from exc
        tool2_dir = prepared_dir / "tool2"
        return {
            "status": "ok",
            "version": VERSION,
            "source": "arcgis-farmland-mpc",
            "mode": "tool2_sample",
            "prepared_dir": str(prepared_dir),
            "out_dir": str(tool2_dir),
            "summary": summary,
            "artifacts": {
                "transitions_npz": "tool2/transitions.npz"
                if (tool2_dir / "transitions.npz").exists()
                else None,
                "pairwise_npz": "tool2/pairwise.npz"
                if (tool2_dir / "pairwise.npz").exists()
                else None,
                "sample_summary": "tool2/sample_transitions_summary.json"
                if (tool2_dir / "sample_transitions_summary.json").exists()
                else None,
                "sample_log": "tool2/sample_transitions.log"
                if (tool2_dir / "sample_transitions.log").exists()
                else None,
            },
        }

    def run_train(self, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
        """Run Paper9 Tool 3 contrastive ensemble training and ONNX export."""
        self._ensure_proj_data_dir()
        train_run = self._load_paper9_train_run()
        prepared_dir = self._required_existing_dir(payload, "prepared_dir")
        out_subdir = str(payload.get("out_subdir") or "tool3").strip() or "tool3"
        kwargs = {
            "prepared_dir": str(prepared_dir),
            "n_members": self._int_range(payload, "n_members", 3, 1, 20),
            "epochs": self._int_range(payload, "epochs", 30, 1, 1000),
            "patience": self._int_range(payload, "patience", 8, 1, 1000),
            "lambda_rank": self._optional_float(payload, "lambda_rank")
            if payload.get("lambda_rank") not in (None, "")
            else 5.0,
            "margin": self._optional_float(payload, "margin")
            if payload.get("margin") not in (None, "")
            else 0.1,
            "batch_size": self._int_range(payload, "batch_size", 256, 1, 100000),
            "n_pairs_per_state": self._int_range(
                payload, "n_pairs_per_state", 10, 1, 10000
            ),
            "pw_subsample": self._int_range(payload, "pw_subsample", 100, 1, 100000),
            "lr": self._optional_float(payload, "lr")
            if payload.get("lr") not in (None, "")
            else 1e-3,
            "weight_decay": self._optional_float(payload, "weight_decay")
            if payload.get("weight_decay") not in (None, "")
            else 1e-5,
            "val_split": self._optional_float(payload, "val_split")
            if payload.get("val_split") not in (None, "")
            else 0.1,
            "seed_base": self._int_range(payload, "seed_base", 0, 0, 1_000_000),
            "torch_threads": self._int_range(payload, "torch_threads", 0, 0, 128),
            "out_subdir": out_subdir,
        }
        try:
            summary = train_run(**kwargs)
        except Exception as exc:
            raise WorldModelV21UnavailableError(str(exc)) from exc
        ensemble_dir = prepared_dir / out_subdir
        return {
            "status": "ok",
            "version": VERSION,
            "source": "arcgis-farmland-mpc",
            "mode": "tool3_train",
            "prepared_dir": str(prepared_dir),
            "ensemble_dir": str(ensemble_dir),
            "onnx_member_count": len(self.find_onnx_members(ensemble_dir)),
            "summary": summary,
            "artifacts": {
                "train_summary": f"{out_subdir}/train_summary.json"
                if (ensemble_dir / "train_summary.json").exists()
                else None,
                "train_log": f"{out_subdir}/train.log"
                if (ensemble_dir / "train.log").exists()
                else None,
                "onnx_members": [
                    f"{out_subdir}/{p.name}" for p in self.find_onnx_members(ensemble_dir)
                ],
            },
        }

    def run_pipeline(self, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
        """Run or reuse the A->B->C->D World Model v2.1 pipeline."""
        reuse_existing = bool(payload.get("reuse_existing", True))
        run_prepare = bool(payload.get("run_prepare", True))
        run_sample = bool(payload.get("run_sample", True))
        run_train = bool(payload.get("run_train", True))
        run_plan = bool(payload.get("run_plan", True))
        steps: list[dict[str, Any]] = []

        prepared_dir = Path(str(payload.get("prepared_dir") or "").strip()) if payload.get("prepared_dir") else None
        if run_prepare:
            if reuse_existing and prepared_dir and self._prepared_ready(prepared_dir):
                steps.append({"step": "prepare", "status": "skipped_reused", "prepared_dir": str(prepared_dir)})
            else:
                prepare_payload = dict(payload)
                prepare_result = self.run_prepare(prepare_payload, user_id=user_id)
                steps.append({"step": "prepare", **prepare_result})
                prepared_dir = Path(prepare_result["prepared_dir"])
        elif prepared_dir is None:
            raise WorldModelV21ValidationError("prepared_dir is required when run_prepare=false")

        assert prepared_dir is not None
        if run_sample:
            if reuse_existing and self._sample_ready(prepared_dir):
                steps.append({"step": "sample", "status": "skipped_reused", "prepared_dir": str(prepared_dir)})
            else:
                sample_payload = dict(payload)
                sample_payload["prepared_dir"] = str(prepared_dir)
                steps.append({"step": "sample", **self.run_sample(sample_payload, user_id=user_id)})

        ensemble_dir = Path(str(payload.get("ensemble_dir") or "").strip()) if payload.get("ensemble_dir") else None
        if run_train:
            if reuse_existing and ensemble_dir and self.find_onnx_members(ensemble_dir):
                steps.append({"step": "train", "status": "skipped_reused", "ensemble_dir": str(ensemble_dir)})
            else:
                train_payload = dict(payload)
                train_payload["prepared_dir"] = str(prepared_dir)
                train_result = self.run_train(train_payload, user_id=user_id)
                steps.append({"step": "train", **train_result})
                ensemble_dir = Path(train_result["ensemble_dir"])
        elif ensemble_dir is None:
            raise WorldModelV21ValidationError("ensemble_dir is required when run_train=false")

        plan_result = None
        if run_plan:
            if ensemble_dir is None:
                raise WorldModelV21ValidationError("ensemble_dir is required for run_plan")
            plan_payload = dict(payload)
            plan_payload["prepared_dir"] = str(prepared_dir)
            plan_payload["ensemble_dir"] = str(ensemble_dir)
            plan_result = self.run_plan(plan_payload, user_id=user_id)
            steps.append({"step": "plan", **plan_result})

        return {
            "status": "ok",
            "version": VERSION,
            "source": "arcgis-farmland-mpc",
            "mode": "pipeline_a_to_d",
            "prepared_dir": str(prepared_dir),
            "ensemble_dir": str(ensemble_dir) if ensemble_dir else None,
            "steps": steps,
            "plan_result": plan_result,
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

        horizon = self._int_range(payload, "horizon", 1, 1, 20)
        top_k = self._int_range(payload, "top_k", 1, 1, 500)
        n_episodes = self._int_range(payload, "n_episodes", 1, 1, 20)

        continuation = str(payload.get("continuation", "greedy")).strip().lower()
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
        self._ensure_proj_data_dir()
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
        land_use_contract = (
            self._detect_land_use_code_contract(input_dltb_fc)
            if output_fc_arg
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
                farm_dlbm=(land_use_contract or {}).get("farm_dlbm", "0101"),
                forest_dlbm=(land_use_contract or {}).get("forest_dlbm", "0301"),
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
            "land_use_code_contract": land_use_contract,
        }

    def _detect_land_use_code_contract(self, input_dltb_fc: Path) -> dict[str, Any]:
        """Choose output codes that match the input scheme before MPC execution."""

        info = self._import_paper9()
        if not info["importable"]:
            raise WorldModelV21UnavailableError(info["error"] or "Paper9 import failed")
        try:
            import geopandas as gpd
            from farmland_mpc.landuse import (
                CURRENT_LAND_USE_SCHEME,
                LEGACY_LAND_USE_SCHEME,
                analyse_land_use_codes,
            )

            dltb = gpd.read_file(input_dltb_fc, columns=["DLBM"])
            report = analyse_land_use_codes(
                dltb["DLBM"], require_farmland=True, require_forest=True
            )
        except Exception as exc:
            raise WorldModelV21ValidationError(
                f"Unable to validate DLBM code scheme for {input_dltb_fc}: {exc}"
            ) from exc

        if report.scheme == CURRENT_LAND_USE_SCHEME:
            farm_dlbm, forest_dlbm = "0101", "0301"
        elif report.scheme == LEGACY_LAND_USE_SCHEME:
            farm_dlbm, forest_dlbm = "011", "031"
        else:
            raise WorldModelV21ValidationError(
                f"Unsupported DLBM code scheme: {report.scheme}"
            )
        return {
            "compatible": True,
            "scheme": report.scheme,
            "farm_dlbm": farm_dlbm,
            "forest_dlbm": forest_dlbm,
            "code_counts": report.code_counts,
        }

    def _import_paper9(self) -> dict[str, Any]:
        source_root = self.repo_path / "src" if (self.repo_path / "src").is_dir() else self.repo_path
        repo = str(source_root)
        if repo not in sys.path:
            sys.path.insert(0, repo)
        try:
            package = importlib.import_module("farmland_mpc")
            module_path = Path(getattr(package, "__file__", "") or "").resolve()
            try:
                source_matches_repo = module_path.is_relative_to(source_root.resolve())
            except ValueError:
                source_matches_repo = False
            algorithm_name = None
            algorithm_version = None
            try:
                version_module = importlib.import_module("paper9_mnr.version")
                algorithm_name = getattr(version_module, "ALGORITHM_NAME", None)
                algorithm_version = getattr(version_module, "ALGORITHM_VERSION", None)
            except Exception:
                pass
            return {
                "importable": True,
                "package_version": getattr(package, "__version__", None),
                "algorithm_name": algorithm_name,
                "algorithm_version": algorithm_version,
                "module_path": str(module_path),
                "source_matches_repo": source_matches_repo,
                "error": None,
            }
        except Exception as exc:
            return {
                "importable": False,
                "package_version": None,
                "algorithm_name": None,
                "algorithm_version": None,
                "module_path": None,
                "source_matches_repo": False,
                "error": str(exc),
            }

    def _ensure_proj_data_dir(self) -> str | None:
        existing = os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB")
        if existing and (Path(existing) / "proj.db").exists():
            os.environ["PROJ_DATA"] = existing
            os.environ["PROJ_LIB"] = existing
            try:
                import pyproj

                pyproj.datadir.set_data_dir(existing)
            except Exception:
                pass
            return existing

        pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        candidates = [
            Path(sys.prefix) / "share" / "proj",
            Path(sys.prefix)
            / "lib"
            / pyver
            / "site-packages"
            / "pyproj"
            / "proj_dir"
            / "share"
            / "proj",
            Path(sys.prefix) / "lib" / pyver / "site-packages" / "pyogrio" / "proj_data",
            Path(sys.prefix) / "lib" / pyver / "site-packages" / "rasterio" / "proj_data",
            Path(sys.base_prefix) / "share" / "proj",
            Path("/usr/local/share/proj"),
            Path("/usr/share/proj"),
        ]
        conda_prefix = os.environ.get("CONDA_PREFIX")
        if conda_prefix:
            candidates.append(Path(conda_prefix) / "share" / "proj")
        candidates.extend([
            Path.home() / "miniconda3" / "envs" / "farmland-mpc" / "share" / "proj",
            Path.home() / "miniconda3" / "share" / "proj",
        ])

        for candidate in candidates:
            if not (candidate / "proj.db").exists():
                continue
            value = str(candidate)
            os.environ["PROJ_DATA"] = value
            os.environ["PROJ_LIB"] = value
            try:
                import pyproj

                pyproj.datadir.set_data_dir(value)
            except Exception:
                pass
            return value
        return None

    def _load_paper9_plan_run(self):
        info = self._import_paper9()
        if not info["importable"]:
            raise WorldModelV21UnavailableError(info["error"] or "Paper9 import failed")
        from farmland_mpc.mpc_plan import run

        return run

    def _load_paper9_prepare_run(self):
        info = self._import_paper9()
        if not info["importable"]:
            raise WorldModelV21UnavailableError(info["error"] or "Paper9 import failed")
        from farmland_mpc.prepare import run

        return run

    def _load_paper9_sample_run(self):
        info = self._import_paper9()
        if not info["importable"]:
            raise WorldModelV21UnavailableError(info["error"] or "Paper9 import failed")
        from farmland_mpc.sample import run

        return run

    def _load_paper9_train_run(self):
        info = self._import_paper9()
        if not info["importable"]:
            raise WorldModelV21UnavailableError(info["error"] or "Paper9 import failed")
        from farmland_mpc.train_ensemble import run

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
            "baimu_count_change": first.get("baimu_count_change"),
            "cultivated_area_change_ha": first.get("cultivated_area_change_ha"),
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
            import numpy as np
            import pandas as pd

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

            def jsonable(value: Any) -> Any:
                if pd.isna(value):
                    return None
                if hasattr(value, "item"):
                    return value.item()
                return value

            features = []
            for idx, row in attrs.iterrows():
                r = int(row["row"])
                c = int(row["col"])
                min_lng = origin_lng + c * cell_lng
                max_lng = min_lng + cell_lng
                min_lat = origin_lat + (max_row - r) * cell_lat
                max_lat = min_lat + cell_lat
                is_selected = int(selected[idx]) == 1
                properties = {
                    str(key): jsonable(value)
                    for key, value in row.to_dict().items()
                }
                properties.update({
                    "selected": 1 if is_selected else 0,
                    "selected_label": "selected" if is_selected else "not_selected",
                    "OPT_DLBM": "031" if is_selected else "011",
                })
                features.append({
                    "type": "Feature",
                    "properties": properties,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [min_lng, min_lat],
                            [max_lng, min_lat],
                            [max_lng, max_lat],
                            [min_lng, max_lat],
                            [min_lng, min_lat],
                        ]],
                    },
                })

            out_path = out_dir / "restoration_mpc_units.geojson"
            payload = {
                "type": "FeatureCollection",
                "name": "restoration_mpc_units",
                "crs": {
                    "type": "name",
                    "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
                },
                "features": features,
            }
            out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
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
                "category_column": "CHG_FLAG",
                "category_labels": {
                    "0": "保持不变",
                    "1": "耕地 -> 林地",
                    "2": "林地 -> 耕地",
                },
                "style_map": {
                    "0": {
                        "fillColor": "#CBD5E1",
                        "color": "#94A3B8",
                        "fillOpacity": 0.12,
                        "weight": 0.1,
                    },
                    "1": {
                        "fillColor": "#DC2626",
                        "color": "#991B1B",
                        "fillOpacity": 0.88,
                        "weight": 0.75,
                    },
                    "2": {
                        "fillColor": "#16A34A",
                        "color": "#166534",
                        "fillOpacity": 0.88,
                        "weight": 0.75,
                    },
                },
                "legend_title": "耕地空间布局优化",
                "tooltip_fields": [
                    "CHG_FLAG",
                    "ORIG_DLBM",
                    "DLBM",
                    "DLMC",
                    "OPT_DLBM",
                    "OPT_DLMC",
                    "slope_mean",
                    "TBMJ",
                ],
                "tooltip_labels": {
                    "CHG_FLAG": "变化",
                    "ORIG_DLBM": "原地类码",
                    "DLBM": "当前地类码",
                    "DLMC": "当前地类名",
                    "OPT_DLBM": "优化后地类码",
                    "OPT_DLMC": "优化后地类名",
                    "slope_mean": "平均坡度",
                    "TBMJ": "图斑面积",
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
                "legend_title": "生态修复单元",
            }
        return {
            "layers": [
                {
                    "name": "World Model v2.1 优化结果",
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

    def _required_existing_file(self, payload: dict[str, Any], key: str) -> Path:
        raw = str(payload.get(key, "")).strip()
        if not raw:
            raise WorldModelV21ValidationError(f"{key} is required")
        path = Path(raw)
        if not path.is_file():
            raise WorldModelV21ValidationError(f"{key} not found: {path}")
        return path

    def _optional_output_dir(
        self,
        payload: dict[str, Any],
        key: str,
        user_id: str,
        default_leaf: str,
    ) -> Path:
        raw = str(payload.get(key, "")).strip()
        if raw:
            path = Path(raw)
            path.mkdir(parents=True, exist_ok=True)
            return path
        out_dir = self._new_output_dir(user_id) / default_leaf
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _relative_to(self, path: str | Path, root: str | Path) -> str:
        try:
            return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
        except Exception:
            return str(path)

    def _prepared_ready(self, prepared_dir: Path) -> bool:
        return (
            prepared_dir.is_dir()
            and (prepared_dir / "dem_slope_analysis" / "output" / "DLTB_with_slope.shp").exists()
            and (prepared_dir / "townships.json").exists()
        )

    def _sample_ready(self, prepared_dir: Path) -> bool:
        tool2 = prepared_dir / "tool2"
        return (
            tool2.is_dir()
            and (tool2 / "transitions.npz").exists()
            and (tool2 / "pairwise.npz").exists()
        )

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

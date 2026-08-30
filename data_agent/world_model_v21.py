"""World Model v2.1 adapter for Paper9 arcgis-farmland-mpc.

This module intentionally keeps Paper9 as the algorithm source of truth. It
loads the local Paper9 checkout lazily so GIS Data Agent can still start when
the Paper9 repo or its optional dependencies are absent.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
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
SUPPORTED_PAPER9_RELEASES = {
    (EXPECTED_PACKAGE_VERSION, EXPECTED_ALGORITHM_VERSION),
    ("0.4.0", "2.3.0"),
}

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
        import_info = (
            self._import_paper9()
            if repo_exists
            else {
                "importable": False,
                "package_version": None,
                "error": "Paper9 repository not found",
            }
        )
        defaults = {
            "prepared_dir": os.environ.get("PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR", ""),
            "ensemble_dir": os.environ.get("PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR", ""),
            "out_dir_policy": "per-user timestamped uploads directory",
        }
        onnx_count = 0
        if defaults["ensemble_dir"]:
            onnx_count = len(self.find_onnx_members(defaults["ensemble_dir"]))

        ready = repo_exists and import_info["importable"]
        version_compatible = bool(
            ready
            and (
                import_info.get("package_version"),
                import_info.get("algorithm_version"),
            )
            in SUPPORTED_PAPER9_RELEASES
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
                "governed_input_catalog": True,
            },
            "finals": {
                "expected_package_version": EXPECTED_PACKAGE_VERSION,
                "expected_algorithm_version": EXPECTED_ALGORITHM_VERSION,
                "supported_releases": [
                    {
                        "package_version": package_version,
                        "algorithm_version": algorithm_version,
                    }
                    for package_version, algorithm_version in sorted(
                        SUPPORTED_PAPER9_RELEASES
                    )
                ],
                "version_compatible": version_compatible,
                "ready": version_compatible,
            },
            "runtime": {
                "proj_data_dir": proj_data_dir,
            },
            "onnx_member_count": onnx_count,
        }

    def list_governed_inputs(self) -> dict[str, Any]:
        """List phase-1 products that are eligible for Paper9 input selection."""

        from .offline_ingest import OfflineIngestStore

        lake = OfflineIngestStore().root
        handoff_dir = lake / "paper9_handoffs"
        derived_catalog = self._read_json(lake / "derived" / "paper9" / "catalog.json")
        derived_by_handoff: dict[str, list[dict[str, Any]]] = {}
        for raw_entry in derived_catalog.get("items") or []:
            if not isinstance(raw_entry, dict):
                continue
            derived_handoff_id = str(raw_entry.get("handoff_id") or "").strip()
            if not derived_handoff_id:
                continue
            manifest_path = str(raw_entry.get("manifest_path") or "").strip()
            available = False
            if manifest_path:
                resolved_manifest = Path(manifest_path).expanduser().resolve()
                try:
                    resolved_manifest.relative_to(lake)
                    available = resolved_manifest.is_file()
                except ValueError:
                    available = False
            derived_by_handoff.setdefault(derived_handoff_id, []).append(
                {**raw_entry, "available": available}
            )
        for entries in derived_by_handoff.values():
            entries.sort(key=lambda entry: str(entry.get("created_at") or ""), reverse=True)
        items: list[dict[str, Any]] = []
        for path in sorted(handoff_dir.glob("*.json")) if handoff_dir.is_dir() else []:
            if path.name == "catalog.json":
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(item, dict):
                continue
            products = item.get("products") or {}
            normalized_products: dict[str, Any] = {}
            for role in ("dltb", "dem", "administrative_units"):
                product = products.get(role)
                if not isinstance(product, dict):
                    normalized_products[role] = None
                    continue
                product_path = str(product.get("path") or "").strip()
                available = False
                if product_path:
                    resolved = Path(product_path).expanduser().resolve()
                    try:
                        resolved.relative_to(lake)
                        available = resolved.exists()
                    except ValueError:
                        available = False
                normalized_products[role] = {**product, "available": available}
            handoff_id = str(item.get("handoff_id") or path.stem)
            derived_runs = derived_by_handoff.get(handoff_id, [])
            items.append(
                {
                    **item,
                    "handoff_id": handoff_id,
                    "products": normalized_products,
                    "suggested_prepared_dir": str(lake / "paper9_runs" / handoff_id / "prepared"),
                    "suggested_ensemble_dir": str(
                        lake / "paper9_runs" / handoff_id / "prepared" / "tool3_smoke"
                    ),
                    "derived_runs": derived_runs,
                    "latest_derived_run": derived_runs[0] if derived_runs else None,
                }
            )
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return {
            "status": "ok",
            "lake_root": str(lake),
            "count": len(items),
            "items": items,
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
                "onnx_member_count": len(self.find_onnx_members(ensemble)) if ensemble else 0,
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
            input_dltb = prepared / "dem_slope_analysis" / "output" / "DLTB_with_slope.shp"
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

    def recall_verified_episodes(self, *, dataset: str = "", limit: int = 3) -> dict[str, Any]:
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
        # FileGDB is a directory dataset.  The open-source Paper9 preparation
        # path reads it through GeoPandas/pyogrio, so a plain Windows install
        # does not need ArcPy or an intermediate export before Tool 1.
        dltb_path = self._required_existing_dataset(payload, "dltb_path")
        dem_path = self._required_existing_file(payload, "dem_path")
        prepared_dir = self._optional_output_dir(
            payload,
            "prepared_dir",
            user_id,
            "prepared",
        )
        input_snapshot_dir = prepared_dir / "input_snapshot"
        dltb_algorithm_path, dltb_resolution = self._adapt_vector_for_paper9(
            dltb_path,
            input_snapshot_dir,
            role="dltb",
            layer="DLTB",
        )
        self._verify_expected_sha256(
            payload, "dltb_expected_sha256", dltb_resolution["source_sha256"]
        )
        dem_sha256 = self._sha256_dataset(dem_path)
        self._verify_expected_sha256(payload, "dem_expected_sha256", dem_sha256)
        dem_resolution = self._inspect_raster_for_paper9(dem_path, dem_sha256)
        xzq_path = None
        xzq_resolution = None
        if str(payload.get("xzq_path") or "").strip():
            xzq_source = self._required_existing_dataset(payload, "xzq_path")
            xzq_path, xzq_resolution = self._adapt_vector_for_paper9(
                xzq_source,
                input_snapshot_dir,
                role="administrative_units",
                layer="ADMINISTRATIVE_UNITS",
            )
            self._verify_expected_sha256(
                payload,
                "xzq_expected_sha256",
                xzq_resolution["source_sha256"],
            )
        analysis_crs = str(payload.get("proj_crs") or "EPSG:32648")
        administrative_reference_mode = str(
            payload.get("administrative_reference_mode") or "auto"
        ).strip().casefold()
        if administrative_reference_mode not in {"auto", "code", "spatial"}:
            raise WorldModelV21ValidationError(
                "administrative_reference_mode must be auto, code, or spatial"
            )
        if administrative_reference_mode == "auto":
            admin_columns = {
                str(column).casefold()
                for column in (xzq_resolution or {}).get("columns") or []
            }
            code_candidates = {
                "xzqdm",
                "xzqhdm",
                "qsdwdm",
                "zldwdm",
                "town_code",
                "adcode",
                "code",
                "dm",
            }
            administrative_reference_mode = (
                "code" if admin_columns.intersection(code_candidates) else "spatial"
            )
        if administrative_reference_mode == "spatial":
            administrative_code_contract = self._administrative_spatial_alignment(
                dltb_algorithm_path,
                xzq_path,
                dltb_resolution=dltb_resolution,
                administrative_resolution=xzq_resolution,
                administrative_name_field=str(
                    payload.get("reference_name_field") or "XZQMC"
                ),
            )
        else:
            administrative_code_contract = self._administrative_code_alignment(
                dltb_algorithm_path,
                xzq_path,
                dltb_resolution=dltb_resolution,
                administrative_resolution=xzq_resolution,
                dltb_field=str(
                    payload.get("dltb_admin_code_field")
                    or payload.get("qsdwdm_field")
                    or "QSDWDM"
                ),
                administrative_field=str(
                    payload.get("administrative_code_field") or ""
                ).strip()
                or None,
            )
        spatial_reference_contract = self._spatial_reference_contract(
            {
                "dltb": dltb_resolution,
                "dem": dem_resolution,
                "administrative_units": xzq_resolution,
            },
            analysis_crs=analysis_crs,
        )
        requested_slope_method = str(payload.get("slope_method") or "auto").strip().casefold()
        if requested_slope_method not in {
            "auto",
            "from_field",
            "gradient_geographic",
            "horn_projected",
        }:
            raise WorldModelV21ValidationError(
                "slope_method must be auto, from_field, gradient_geographic, or horn_projected"
            )
        dltb_columns_by_key = {
            str(column).casefold(): str(column)
            for column in (dltb_resolution.get("columns") or [])
        }
        slope_field = str(payload.get("slope_field") or "slope_mean").strip()
        resolved_slope_method = requested_slope_method
        slope_resolution_reason = "operator_supplied"
        if requested_slope_method == "auto":
            source_slope_field = dltb_columns_by_key.get(slope_field.casefold())
            if source_slope_field:
                # Governed DLTB_with_slope products already carry the
                # upstream zonal slope contract. Recomputing from DEM would
                # discard that contract and can lower apparent coverage at
                # the raster edge. Raw DLTB without the field still follows
                # the DEM-derived path in Paper9.
                resolved_slope_method = "from_field"
                slope_field = source_slope_field
                slope_resolution_reason = "complete_existing_slope_field"
            else:
                resolved_slope_method = "auto"
                slope_resolution_reason = "slope_field_missing_use_dem"
        elif requested_slope_method == "from_field":
            source_slope_field = dltb_columns_by_key.get(slope_field.casefold())
            if not source_slope_field:
                raise WorldModelV21ValidationError(
                    f"slope_method='from_field' but field {slope_field!r} is missing from DLTB"
                )
            slope_field = source_slope_field
        kwargs = {
            "dltb_path": str(dltb_algorithm_path),
            "dem_path": str(dem_path),
            "prepared_dir": str(prepared_dir),
            "proj_crs": analysis_crs,
            "dlbm_field": str(payload.get("dlbm_field") or "DLBM"),
            "qsdwdm_field": str(payload.get("qsdwdm_field") or "QSDWDM"),
            "bsm_field": str(payload.get("bsm_field") or "BSM"),
            "slope_method": resolved_slope_method,
            "slope_field": slope_field,
            "run_phase_bc": bool(payload.get("run_phase_bc", True)),
            "min_parcels": self._int_range(payload, "min_parcels", 3, 1, 1000),
            "min_area_ha": self._optional_float(payload, "min_area_ha") or 0.5,
            "max_parcels": self._int_range(payload, "max_parcels", 30, 1, 5000),
            "min_parcels_per_township": self._int_range(
                payload, "min_parcels_per_township", 50, 1, 100000
            ),
            "xzq_path": str(xzq_path) if xzq_path else None,
            "reference_layer": (
                str(xzq_path)
                if xzq_path and administrative_reference_mode == "spatial"
                else payload.get("reference_layer") or None
            ),
            "reference_name_field": str(payload.get("reference_name_field") or "XZQMC"),
        }
        try:
            output_path = prepare_run(**kwargs)
        except Exception as exc:
            raise WorldModelV21UnavailableError(str(exc)) from exc

        summary = self._read_json(prepared_dir / "prepare_data_summary.json")
        input_quality = self._prepare_input_quality(
            summary,
            administrative_units_present=xzq_resolution is not None,
            minimum_dem_coverage=self._optional_float(payload, "minimum_dem_coverage_fraction")
            or 0.98,
            slope_source=(
                "existing_slope_field"
                if resolved_slope_method == "from_field"
                else "dem_zonal_sampling"
            ),
            slope_field=slope_field if resolved_slope_method == "from_field" else None,
            spatial_reference_contract=spatial_reference_contract,
            administrative_code_contract=administrative_code_contract,
            reference_years={
                "dltb": self._optional_int(payload, "dltb_reference_year"),
                "dem": self._optional_int(payload, "dem_reference_year"),
                "administrative_units": self._optional_int(
                    payload, "administrative_reference_year"
                ),
            },
            reference_year_sources=dict(payload.get("reference_year_sources") or {}),
            reference_year_authority={
                str(role): bool(authoritative)
                for role, authoritative in dict(
                    payload.get("reference_year_authority") or {}
                ).items()
            },
            require_reference_years=bool(payload.get("require_reference_years", False)),
            require_authoritative_reference_years=bool(
                payload.get("require_authoritative_reference_years", False)
            ),
            maximum_reference_year_gap=self._int_range(
                payload, "maximum_reference_year_gap", 1, 0, 100
            ),
            minimum_admin_code_match=self._optional_float(
                payload, "minimum_admin_code_match_fraction"
            )
            or 0.98,
        )
        input_resolution = {
            "dltb": dltb_resolution,
            "dem": dem_resolution,
            "administrative_units": xzq_resolution,
        }
        input_manifest = {
            "schema": "gda.paper9-input-snapshot.v1",
            "created_at": datetime.now().astimezone().isoformat(),
            "input_resolution": input_resolution,
            "input_quality": input_quality,
            "spatial_reference_contract": spatial_reference_contract,
            "administrative_code_contract": administrative_code_contract,
            "administrative_reference_mode": administrative_reference_mode,
            "slope_contract": {
                "requested_method": requested_slope_method,
                "resolved_method": resolved_slope_method,
                "field": slope_field if resolved_slope_method == "from_field" else None,
                "resolution_reason": slope_resolution_reason,
            },
        }
        input_manifest_path = prepared_dir / "paper9_input_snapshot.json"
        input_manifest_path.write_text(
            json.dumps(input_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "status": "ok",
            "version": VERSION,
            "source": "arcgis-farmland-mpc",
            "mode": "tool1_prepare",
            "prepared_dir": str(prepared_dir),
            "output_path": str(output_path),
            "summary": summary,
            "input_quality": input_quality,
            "slope_contract": {
                "requested_method": requested_slope_method,
                "resolved_method": resolved_slope_method,
                "field": slope_field if resolved_slope_method == "from_field" else None,
                "resolution_reason": slope_resolution_reason,
            },
            "input_resolution": input_resolution,
            "artifacts": {
                "dltb_with_slope": self._relative_to(output_path, prepared_dir),
                "prepare_summary": "prepare_data_summary.json"
                if (prepared_dir / "prepare_data_summary.json").exists()
                else None,
                "townships": "townships.json"
                if (prepared_dir / "townships.json").exists()
                else None,
                "input_snapshot": "paper9_input_snapshot.json",
            },
        }

    def _adapt_vector_for_paper9(
        self,
        source: Path,
        snapshot_dir: Path,
        *,
        role: str,
        layer: str,
    ) -> tuple[Path, dict[str, Any]]:
        """Resolve a governed vector product to a format Paper9 can read."""

        source = source.expanduser().resolve()
        source_sha256 = self._sha256_dataset(source)
        suffix = source.suffix.casefold()
        resolution: dict[str, Any] = {
            "role": role,
            "source_path": str(source),
            "source_sha256": source_sha256,
            "algorithm_path": str(source),
            "adapter": "pass_through",
        }
        if suffix not in {".parquet", ".geoparquet", ".parq"}:
            try:
                from .local_gis_runtime import inspect_vector

                layers = inspect_vector(source)
                selected = next(
                    (
                        item
                        for item in layers
                        if str(item.get("name") or "").casefold() == layer.casefold()
                    ),
                    layers[0] if layers else None,
                )
                if selected:
                    resolution.update(
                        {
                            "source_layer": selected.get("name"),
                            "algorithm_layer": selected.get("name"),
                            "feature_count": selected.get("feature_count"),
                            "crs": selected.get("crs_name")
                            or (
                                f"EPSG:{selected['srid']}" if selected.get("srid") else None
                            ),
                            "bbox": selected.get("extent"),
                            "geometry_types": [selected.get("geometry_type")]
                            if selected.get("geometry_type")
                            else [],
                            "columns": [
                                str(field.get("name"))
                                for field in selected.get("fields") or []
                                if field.get("name")
                            ],
                        }
                    )
            except Exception:
                pass
            return source, resolution

        try:
            import geopandas as gpd

            frame = gpd.read_parquet(source)
            if frame.geometry.name not in frame.columns:
                raise ValueError("GeoParquet has no active geometry column")
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            target = snapshot_dir / f"{role}.gpkg"
            if target.exists():
                target.unlink()
            frame.to_file(target, layer=layer, driver="GPKG", index=False)
        except Exception as exc:
            raise WorldModelV21ValidationError(
                f"failed to adapt governed {role} GeoParquet for Paper9: {exc}"
            ) from exc

        geometry_types = sorted(
            str(value) for value in frame.geometry.geom_type.dropna().unique().tolist()
        )
        resolution.update(
            {
                "algorithm_path": str(target),
                "algorithm_layer": layer,
                "algorithm_sha256": self._sha256_dataset(target),
                "adapter": "geoparquet_to_gpkg",
                "feature_count": int(len(frame)),
                "crs": frame.crs.to_string() if frame.crs is not None else None,
                "bbox": [float(value) for value in frame.total_bounds.tolist()]
                if not frame.empty
                else None,
                "columns": [
                    str(column) for column in frame.columns if column != frame.geometry.name
                ],
                "geometry_types": geometry_types,
                "note": "The GPKG is an algorithm workspace snapshot, not a second lake ingest.",
            }
        )
        return target, resolution

    def _inspect_raster_for_paper9(self, source: Path, source_sha256: str) -> dict[str, Any]:
        resolution: dict[str, Any] = {
            "role": "dem",
            "source_path": str(source),
            "source_sha256": source_sha256,
            "algorithm_path": str(source),
            "adapter": "pass_through",
        }
        try:
            import rasterio

            with rasterio.open(source) as dataset:
                bounds = dataset.bounds
                resolution.update(
                    {
                        "crs": dataset.crs.to_string() if dataset.crs else None,
                        "bbox": [
                            float(bounds.left),
                            float(bounds.bottom),
                            float(bounds.right),
                            float(bounds.top),
                        ],
                        "width": int(dataset.width),
                        "height": int(dataset.height),
                        "band_count": int(dataset.count),
                    }
                )
        except Exception as exc:
            resolution["inspection_error"] = str(exc)
        return resolution

    def _spatial_reference_contract(
        self,
        inputs: dict[str, dict[str, Any] | None],
        *,
        analysis_crs: str,
    ) -> dict[str, Any]:
        roles: dict[str, Any] = {}
        try:
            from pyproj import CRS, Transformer

            target = CRS.from_user_input(analysis_crs)
            target_name = target.to_string()
            target_error = None
        except Exception as exc:
            CRS = None  # type: ignore[assignment]
            Transformer = None  # type: ignore[assignment]
            target = None
            target_name = analysis_crs
            target_error = str(exc)

        for role, resolution in inputs.items():
            if not resolution:
                roles[role] = {"present": False, "crs": None, "transformable": False}
                continue
            raw_crs = str(resolution.get("crs") or "").strip()
            detail = {
                "present": True,
                "crs": raw_crs or None,
                "bbox": resolution.get("bbox"),
                "transformable": False,
            }
            if target_error:
                detail["error"] = f"analysis CRS is invalid: {target_error}"
            elif not raw_crs:
                detail["error"] = "source CRS metadata is missing"
            else:
                try:
                    source_crs = CRS.from_user_input(raw_crs)
                    Transformer.from_crs(source_crs, target, always_xy=True)
                    detail.update(
                        {
                            "normalized_crs": source_crs.to_string(),
                            "transformable": True,
                            "requires_reprojection": source_crs != target,
                        }
                    )
                except Exception as exc:
                    detail["error"] = str(exc)
            roles[role] = detail
        required = ["dltb", "dem"]
        if inputs.get("administrative_units"):
            required.append("administrative_units")
        return {
            "analysis_crs": target_name,
            "roles": roles,
            "required_roles": required,
            "all_required_transformable": all(
                bool((roles.get(role) or {}).get("transformable")) for role in required
            ),
        }

    def _administrative_code_alignment(
        self,
        dltb_path: Path,
        administrative_path: Path | None,
        *,
        dltb_resolution: dict[str, Any],
        administrative_resolution: dict[str, Any] | None,
        dltb_field: str,
        administrative_field: str | None,
    ) -> dict[str, Any]:
        if not administrative_path or not administrative_resolution:
            return {
                "status": "missing",
                "dltb_field": dltb_field,
                "administrative_field": administrative_field,
                "exact_match_fraction": 0.0,
            }

        def resolve_field(columns: list[str], requested: str | None, candidates: tuple[str, ...]):
            by_key = {column.casefold(): column for column in columns}
            if requested:
                return by_key.get(requested.casefold())
            for candidate in candidates:
                if candidate.casefold() in by_key:
                    return by_key[candidate.casefold()]
            return None

        dltb_columns = [str(value) for value in dltb_resolution.get("columns") or []]
        admin_columns = [
            str(value) for value in administrative_resolution.get("columns") or []
        ]
        resolved_dltb_field = resolve_field(dltb_columns, dltb_field, (dltb_field,))
        resolved_admin_field = resolve_field(
            admin_columns,
            administrative_field,
            (
                "XZQDM",
                "XZQHDM",
                "QSDWDM",
                "ZLDWDM",
                "TOWN_CODE",
                "ADCODE",
                "CODE",
                "DM",
            ),
        )
        if not resolved_dltb_field or not resolved_admin_field:
            return {
                "status": "review",
                "dltb_field": resolved_dltb_field or dltb_field,
                "administrative_field": resolved_admin_field or administrative_field,
                "dltb_columns": dltb_columns,
                "administrative_columns": admin_columns,
                "exact_match_fraction": 0.0,
                "error": "administrative code fields could not be resolved",
            }

        try:
            import geopandas as gpd

            def read_codes(path: Path, field: str, layer: str | None):
                if path.suffix.casefold() in {".parquet", ".geoparquet", ".parq"}:
                    import pandas as pd

                    frame = pd.read_parquet(path, columns=[field])
                else:
                    kwargs = {"columns": [field], "ignore_geometry": True}
                    if layer:
                        kwargs["layer"] = layer
                    frame = gpd.read_file(path, **kwargs)
                values = frame[field].astype("string").str.strip().fillna("")
                return values.str.replace(r"\.0$", "", regex=True).str.upper()

            dltb_codes = read_codes(
                dltb_path,
                resolved_dltb_field,
                dltb_resolution.get("algorithm_layer"),
            )
            admin_codes = read_codes(
                administrative_path,
                resolved_admin_field,
                administrative_resolution.get("algorithm_layer"),
            )
            dltb_codes = dltb_codes[dltb_codes != ""]
            admin_set = {value for value in admin_codes.tolist() if value}
            counts = dltb_codes.value_counts()
            matched = sum(int(count) for code, count in counts.items() if code in admin_set)
            prefix_matched = sum(
                int(count)
                for code, count in counts.items()
                if any(code.startswith(admin) or admin.startswith(code) for admin in admin_set)
            )
            total = int(counts.sum())
            exact_fraction = matched / total if total else 0.0
            prefix_fraction = prefix_matched / total if total else 0.0
            return {
                "status": "pass" if total and exact_fraction == 1.0 else "review",
                "dltb_field": resolved_dltb_field,
                "administrative_field": resolved_admin_field,
                "dltb_nonempty_count": total,
                "dltb_unique_code_count": int(len(counts)),
                "administrative_unique_code_count": int(len(admin_set)),
                "exact_match_count": matched,
                "exact_match_fraction": exact_fraction,
                "hierarchical_prefix_match_fraction": prefix_fraction,
                "unmatched_code_examples": [
                    str(code) for code in counts.index if code not in admin_set
                ][:20],
            }
        except Exception as exc:
            return {
                "status": "review",
                "dltb_field": resolved_dltb_field,
                "administrative_field": resolved_admin_field,
                "exact_match_fraction": 0.0,
                "error": str(exc),
            }

    def _administrative_spatial_alignment(
        self,
        dltb_path: Path,
        administrative_path: Path | None,
        *,
        dltb_resolution: dict[str, Any],
        administrative_resolution: dict[str, Any] | None,
        administrative_name_field: str,
    ) -> dict[str, Any]:
        """Measure parcel coverage by a name-only administrative reference layer."""

        if not administrative_path or not administrative_resolution:
            return {
                "status": "missing",
                "alignment_mode": "spatial_reference",
                "spatial_match_fraction": 0.0,
            }
        try:
            import geopandas as gpd

            dltb = gpd.read_file(
                dltb_path,
                layer=dltb_resolution.get("algorithm_layer"),
            )
            administrative = gpd.read_file(
                administrative_path,
                layer=administrative_resolution.get("algorithm_layer"),
            )
            if dltb.crs is None or administrative.crs is None:
                raise ValueError("DLTB and administrative reference must both declare a CRS")
            if administrative_name_field not in administrative.columns:
                raise ValueError(
                    f"administrative name field {administrative_name_field!r} is missing"
                )
            administrative = administrative.to_crs(dltb.crs)
            points = gpd.GeoDataFrame(
                geometry=dltb.geometry.representative_point(),
                crs=dltb.crs,
                index=dltb.index,
            )
            joined = gpd.sjoin(
                points,
                administrative[[administrative_name_field, "geometry"]],
                how="left",
                predicate="within",
            )
            matched_rows = joined[joined["index_right"].notna()]
            matched_indexes = set(matched_rows.index.tolist())
            total = int(len(points))
            matched = int(len(matched_indexes))
            fraction = matched / total if total else 0.0
            selected_reference_indexes = {
                int(value) for value in matched_rows["index_right"].dropna().tolist()
            }
            selected_names = sorted(
                {
                    str(administrative.loc[index, administrative_name_field]).strip()
                    for index in selected_reference_indexes
                    if index in administrative.index
                }
            )
            return {
                "status": "pass" if total and fraction >= 0.98 else "review",
                "alignment_mode": "spatial_reference",
                "administrative_name_field": administrative_name_field,
                "dltb_feature_count": total,
                "spatial_match_count": matched,
                "spatial_match_fraction": fraction,
                "reference_feature_count": int(len(administrative)),
                "selected_reference_feature_count": len(selected_reference_indexes),
                "selected_reference_names": selected_names,
                "code_authority": False,
                "note": (
                    "The layer supplies township names by spatial overlap; it does not "
                    "claim an exact administrative-code contract."
                ),
            }
        except Exception as exc:
            return {
                "status": "review",
                "alignment_mode": "spatial_reference",
                "administrative_name_field": administrative_name_field,
                "spatial_match_fraction": 0.0,
                "error": str(exc),
            }

    def _prepare_input_quality(
        self,
        summary: dict[str, Any],
        *,
        administrative_units_present: bool,
        minimum_dem_coverage: float,
        slope_source: str = "dem_zonal_sampling",
        slope_field: str | None = None,
        spatial_reference_contract: dict[str, Any] | None = None,
        administrative_code_contract: dict[str, Any] | None = None,
        reference_years: dict[str, int | None] | None = None,
        reference_year_sources: dict[str, str] | None = None,
        reference_year_authority: dict[str, bool] | None = None,
        require_reference_years: bool = False,
        require_authoritative_reference_years: bool = False,
        maximum_reference_year_gap: int = 1,
        minimum_admin_code_match: float = 0.98,
    ) -> dict[str, Any]:
        if not 0.0 <= minimum_dem_coverage <= 1.0:
            raise WorldModelV21ValidationError(
                "minimum_dem_coverage_fraction must be between 0 and 1"
            )
        if not 0.0 <= minimum_admin_code_match <= 1.0:
            raise WorldModelV21ValidationError(
                "minimum_admin_code_match_fraction must be between 0 and 1"
            )
        total = int(summary.get("n_parcels") or 0)
        unmatched = int(summary.get("n_parcels_unmatched") or 0)
        matched = max(0, total - unmatched)
        coverage = (matched / total) if total else 0.0
        if slope_source not in {"dem_zonal_sampling", "existing_slope_field"}:
            raise WorldModelV21ValidationError(
                "slope_source must be dem_zonal_sampling or existing_slope_field"
            )
        findings: list[str] = []
        if total <= 0:
            findings.append("DLTB preparation produced no parcels")
        elif coverage < minimum_dem_coverage:
            if slope_source == "existing_slope_field":
                findings.append(
                    "existing slope-field coverage is below the production threshold: "
                    f"{coverage:.4%} < {minimum_dem_coverage:.2%}"
                )
            else:
                findings.append(
                    "DEM direct coverage is below the production threshold: "
                    f"{coverage:.4%} < {minimum_dem_coverage:.2%}"
                )
        if not administrative_units_present:
            findings.append("governed administrative-unit product is missing")
        if spatial_reference_contract and not spatial_reference_contract.get(
            "all_required_transformable", False
        ):
            for role in spatial_reference_contract.get("required_roles") or []:
                detail = (spatial_reference_contract.get("roles") or {}).get(role) or {}
                if not detail.get("transformable"):
                    findings.append(
                        f"{role} CRS cannot be transformed to the analysis CRS: "
                        f"{detail.get('error') or 'unknown CRS'}"
                    )
        if administrative_units_present and administrative_code_contract:
            alignment_mode = str(
                administrative_code_contract.get("alignment_mode") or "code"
            )
            fraction_field = (
                "spatial_match_fraction"
                if alignment_mode == "spatial_reference"
                else "exact_match_fraction"
            )
            match_fraction = float(administrative_code_contract.get(fraction_field) or 0.0)
            if match_fraction < minimum_admin_code_match:
                label = (
                    "spatial coverage"
                    if alignment_mode == "spatial_reference"
                    else "code exact-match coverage"
                )
                findings.append(
                    f"administrative {label} is below the production threshold: "
                    f"{match_fraction:.4%} < {minimum_admin_code_match:.2%}"
                )
        reference_years = reference_years or {}
        reference_year_sources = reference_year_sources or {}
        reference_year_authority = reference_year_authority or {}
        required_year_roles = ["dltb", "dem"]
        if administrative_units_present:
            required_year_roles.append("administrative_units")
        missing_years = [role for role in required_year_roles if reference_years.get(role) is None]
        if require_reference_years and missing_years:
            findings.append("reference year is missing for: " + ", ".join(missing_years))
        non_authoritative_years = [
            role
            for role in required_year_roles
            if reference_years.get(role) is not None
            and not reference_year_authority.get(role, False)
        ]
        if require_authoritative_reference_years and non_authoritative_years:
            details = ", ".join(
                f"{role} ({reference_year_sources.get(role) or 'unspecified'})"
                for role in non_authoritative_years
            )
            findings.append("reference year is not authoritative for: " + details)
        known_years = [int(value) for value in reference_years.values() if value is not None]
        reference_year_gap = (
            max(known_years) - min(known_years) if len(known_years) >= 2 else None
        )
        if reference_year_gap is not None and reference_year_gap > maximum_reference_year_gap:
            findings.append(
                "input reference-year gap exceeds the production threshold: "
                f"{reference_year_gap} > {maximum_reference_year_gap}"
            )
        return {
            "status": "pass" if not findings else "review",
            "parcel_count": total,
            "dem_matched_parcel_count": matched,
            "dem_unmatched_parcel_count": unmatched,
            # Keep the historical key for API compatibility. For a governed
            # precomputed slope field it is null because DEM was not sampled.
            "dem_direct_coverage_fraction": coverage
            if slope_source == "dem_zonal_sampling"
            else None,
            "slope_source": slope_source,
            "slope_field": slope_field,
            "slope_coverage_fraction": coverage,
            "minimum_dem_coverage_fraction": minimum_dem_coverage,
            "administrative_units_present": administrative_units_present,
            "administrative_code_contract": administrative_code_contract,
            "minimum_admin_code_match_fraction": minimum_admin_code_match,
            "spatial_reference_contract": spatial_reference_contract,
            "reference_years": reference_years,
            "reference_year_sources": reference_year_sources,
            "reference_year_authority": reference_year_authority,
            "reference_year_gap": reference_year_gap,
            "maximum_reference_year_gap": maximum_reference_year_gap,
            "reference_years_required": require_reference_years,
            "authoritative_reference_years_required": (
                require_authoritative_reference_years
            ),
            "production_gate_passed": not findings,
            "findings": findings,
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
            "n_pairwise_states": self._int_range(payload, "n_pairwise_states", 1000, 1, 200000),
            "n_pairwise_actions": self._int_range(payload, "n_pairwise_actions", 50, 1, 10000),
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
            "n_pairs_per_state": self._int_range(payload, "n_pairs_per_state", 10, 1, 10000),
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

        prepared_dir = (
            Path(str(payload.get("prepared_dir") or "").strip())
            if payload.get("prepared_dir")
            else None
        )
        if run_prepare:
            if reuse_existing and prepared_dir and self._prepared_ready(prepared_dir):
                snapshot = self._validate_reused_prepared_inputs(payload, prepared_dir)
                steps.append(
                    {
                        "step": "prepare",
                        "status": "skipped_reused",
                        "prepared_dir": str(prepared_dir),
                        "input_resolution": snapshot.get("input_resolution"),
                        "input_quality": snapshot.get("input_quality"),
                    }
                )
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
                steps.append(
                    {
                        "step": "sample",
                        "status": "skipped_reused",
                        "prepared_dir": str(prepared_dir),
                    }
                )
            else:
                sample_payload = dict(payload)
                sample_payload["prepared_dir"] = str(prepared_dir)
                steps.append({"step": "sample", **self.run_sample(sample_payload, user_id=user_id)})

        ensemble_dir = (
            Path(str(payload.get("ensemble_dir") or "").strip())
            if payload.get("ensemble_dir")
            else None
        )
        if run_train:
            if reuse_existing and ensemble_dir and self.find_onnx_members(ensemble_dir):
                steps.append(
                    {
                        "step": "train",
                        "status": "skipped_reused",
                        "ensemble_dir": str(ensemble_dir),
                    }
                )
            else:
                train_payload = dict(payload)
                train_payload["prepared_dir"] = str(prepared_dir)
                train_result = self.run_train(train_payload, user_id=user_id)
                steps.append({"step": "train", **train_result})
                ensemble_dir = Path(train_result["ensemble_dir"])
        elif ensemble_dir is None:
            raise WorldModelV21ValidationError("ensemble_dir is required when run_train=false")

        plan_result = None
        audit_result = None
        derived_publication = None
        if run_plan:
            if ensemble_dir is None:
                raise WorldModelV21ValidationError("ensemble_dir is required for run_plan")
            plan_payload = dict(payload)
            plan_payload["prepared_dir"] = str(prepared_dir)
            plan_payload["ensemble_dir"] = str(ensemble_dir)
            plan_result = self.run_plan(plan_payload, user_id=user_id)
            steps.append({"step": "plan", **plan_result})

            governed_handoff_id = str(payload.get("governed_handoff_id") or "").strip()
            if governed_handoff_id:
                try:
                    audit_result = self.audit_run(
                        out_dir=plan_result["out_dir"],
                        attempt=0,
                        cultivated_area_floor_delta_ha=(
                            self._optional_float(payload, "cultivated_area_floor_delta_ha") or 0.0
                        ),
                    )
                    prepare_step = next(
                        (
                            step
                            for step in steps
                            if step.get("step") == "prepare" and step.get("input_quality")
                        ),
                        {},
                    )
                    derived_publication = self._publish_governed_result(
                        handoff_id=governed_handoff_id,
                        prepared_dir=prepared_dir,
                        ensemble_dir=ensemble_dir,
                        plan_result=plan_result,
                        audit=audit_result,
                        input_quality=prepare_step.get("input_quality") or {},
                        user_id=user_id,
                    )
                except WorldModelV21Error:
                    raise
                except Exception as exc:
                    raise WorldModelV21UnavailableError(
                        f"Paper9 audit or Derived publication failed: {exc}"
                    ) from exc

        return {
            "status": "ok",
            "version": VERSION,
            "source": "arcgis-farmland-mpc",
            "mode": "pipeline_a_to_d",
            "prepared_dir": str(prepared_dir),
            "ensemble_dir": str(ensemble_dir) if ensemble_dir else None,
            "steps": steps,
            "plan_result": plan_result,
            "audit_result": audit_result,
            "derived_publication": derived_publication,
        }

    def _publish_governed_result(
        self,
        *,
        handoff_id: str,
        prepared_dir: Path,
        ensemble_dir: Path | None,
        plan_result: dict[str, Any],
        audit: dict[str, Any],
        input_quality: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        """Freeze an audited Tool 4 result under the file lake Derived zone."""

        from .offline_ingest import OfflineIngestStore

        lake = OfflineIngestStore().root
        handoff_path = (lake / "paper9_handoffs" / f"{handoff_id}.json").resolve()
        try:
            handoff_path.relative_to(lake)
        except ValueError as exc:
            raise WorldModelV21ValidationError("invalid governed_handoff_id") from exc
        if not handoff_path.is_file():
            raise WorldModelV21ValidationError(
                f"governed handoff does not exist in the active lake: {handoff_id}"
            )
        handoff = self._read_json(handoff_path)

        source_out = Path(str(plan_result.get("out_dir") or "")).expanduser().resolve()
        if not source_out.is_dir():
            raise WorldModelV21ValidationError("Paper9 output directory does not exist")
        run_id = source_out.name
        destination = lake / "derived" / "paper9" / handoff_id / run_id
        if destination.exists():
            raise WorldModelV21ValidationError(
                f"Derived Paper9 run already exists: {destination}"
            )
        destination.mkdir(parents=True)

        artifacts: list[dict[str, Any]] = []
        for source in sorted(path for path in source_out.rglob("*") if path.is_file()):
            relative = source.relative_to(source_out)
            target = destination / "artifacts" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            artifacts.append(
                {
                    "name": relative.as_posix(),
                    "path": str(target),
                    "sha256": self._sha256_dataset(target),
                    "size": target.stat().st_size,
                }
            )

        status = self.status()
        production_eligible = bool(
            handoff.get("production_eligible")
            and input_quality.get("production_gate_passed")
            and audit.get("hard_constraint_passed")
            and audit.get("all_expected_outputs_exist")
            and (status.get("finals") or {}).get("version_compatible")
        )
        created_at = datetime.now().astimezone().isoformat()
        manifest = {
            "schema": "gda.paper9-derived-run.v1",
            "run_id": run_id,
            "handoff_id": handoff_id,
            "created_at": created_at,
            "actor": user_id,
            "status": "approved" if production_eligible else "review",
            "production_eligible": production_eligible,
            "lineage": {
                "phase1_handoff": str(handoff_path),
                "phase1_report": handoff.get("phase1_report"),
                "input_products": handoff.get("products") or {},
                "prepared_dir": str(prepared_dir),
                "prepared_input_snapshot": str(prepared_dir / "paper9_input_snapshot.json"),
                "ensemble_dir": str(ensemble_dir) if ensemble_dir else None,
                "ensemble_sha256": self._sha256_dataset(ensemble_dir)
                if ensemble_dir and ensemble_dir.exists()
                else None,
                "source_output_dir": str(source_out),
            },
            "input_quality": input_quality,
            "paper9": status.get("paper9"),
            "finals": status.get("finals"),
            "plan_summary": plan_result.get("summary") or {},
            "audit": audit,
            "artifacts": artifacts,
        }
        manifest_path = destination / "result_manifest.json"
        self._write_json_atomic(manifest_path, manifest)

        catalog_path = lake / "derived" / "paper9" / "catalog.json"
        catalog = self._read_json(catalog_path) if catalog_path.exists() else {}
        items = [
            item
            for item in catalog.get("items") or []
            if isinstance(item, dict)
            and not (
                item.get("handoff_id") == handoff_id and item.get("run_id") == run_id
            )
        ]
        entry = {
            "run_id": run_id,
            "handoff_id": handoff_id,
            "created_at": created_at,
            "status": manifest["status"],
            "production_eligible": production_eligible,
            "manifest_path": str(manifest_path),
            "artifact_count": len(artifacts),
        }
        items.append(entry)
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        self._write_json_atomic(
            catalog_path,
            {
                "schema": "gda.paper9-derived-run-catalog.v1",
                "updated_at": created_at,
                "items": items[:100],
            },
        )
        return {**entry, "catalog_path": str(catalog_path)}

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

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
            raise WorldModelV21ValidationError("continuation must be 'random' or 'greedy'")

        scoring = str(payload.get("scoring", "reward")).strip().lower()
        if scoring == "slope_only":
            scoring = "slope"
        if scoring not in {"reward", "slope"}:
            raise WorldModelV21ValidationError("scoring must be 'reward' or 'slope'")

        env_kind = str(payload.get("env_kind", "county")).strip().lower()
        if env_kind not in {"county", "restoration"}:
            raise WorldModelV21ValidationError("env_kind must be 'county' or 'restoration'")

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
            "baimu_area_floor_delta_ha": self._optional_float(payload, "baimu_area_floor_delta_ha"),
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
            str(output_fc) if cfg["env_kind"] == "county" and input_dltb_fc.exists() else None
        )
        land_use_contract = (
            self._detect_land_use_code_contract(input_dltb_fc) if output_fc_arg else None
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
                cultivated_area_floor_delta_ha=cfg["cultivated_area_floor_delta_ha"],
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
            "summary_json": "mpc_summary.json" if (out_dir / "mpc_summary.json").exists() else None,
            "land_use_npy": "mpc_land_use.npy" if (out_dir / "mpc_land_use.npy").exists() else None,
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

            dltb = gpd.read_file(input_dltb_fc, columns=["DLBM"])
            values = dltb["DLBM"].astype("string").str.strip().fillna("")
            code_counts = {str(key): int(value) for key, value in values.value_counts().items()}
            try:
                from farmland_mpc.landuse import (
                    CURRENT_LAND_USE_SCHEME,
                    LEGACY_LAND_USE_SCHEME,
                    analyse_land_use_codes,
                )

                report = analyse_land_use_codes(values, require_farmland=True, require_forest=True)
                scheme = str(report.scheme)
                code_counts = report.code_counts
                if scheme == CURRENT_LAND_USE_SCHEME:
                    farm_dlbm, forest_dlbm = "0101", "0301"
                elif scheme == LEGACY_LAND_USE_SCHEME:
                    farm_dlbm, forest_dlbm = "011", "031"
                else:
                    raise ValueError(f"unsupported Paper9 land-use scheme: {scheme}")
            except ImportError:
                # Paper9 0.2.x predates the shared landuse helper. Keep the
                # adapter usable by validating the same prefixes locally.
                has_current = (
                    values.str.startswith(("0101", "0102", "0103")).any()
                    and values.str.startswith(("0301", "0302", "0303")).any()
                )
                has_legacy = (
                    values.str.startswith(("011", "012", "013")).any()
                    and values.str.startswith(("031", "032", "033")).any()
                )
                if has_current:
                    scheme, farm_dlbm, forest_dlbm = "current", "0101", "0301"
                elif has_legacy:
                    scheme, farm_dlbm, forest_dlbm = "legacy", "011", "031"
                else:
                    raise ValueError("no supported farmland and forest DLBM prefixes") from None
        except Exception as exc:
            raise WorldModelV21ValidationError(
                f"Unable to validate DLBM code scheme for {input_dltb_fc}: {exc}"
            ) from exc
        return {
            "compatible": True,
            "scheme": scheme,
            "farm_dlbm": farm_dlbm,
            "forest_dlbm": forest_dlbm,
            "code_counts": code_counts,
        }

    def _import_paper9(self) -> dict[str, Any]:
        source_root = (
            self.repo_path / "src" if (self.repo_path / "src").is_dir() else self.repo_path
        )
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
        candidates.extend(
            [
                Path.home() / "miniconda3" / "envs" / "farmland-mpc" / "share" / "proj",
                Path.home() / "miniconda3" / "share" / "proj",
            ]
        )

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
            Path(__file__).resolve().parent / "uploads" / safe_user / "world_model_v21" / stamp
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
            "slope_change_pct": first.get("slope_change_pct", aggregate.get("slope_pct_mean")),
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
                properties = {str(key): jsonable(value) for key, value in row.to_dict().items()}
                properties.update(
                    {
                        "selected": 1 if is_selected else 0,
                        "selected_label": "selected" if is_selected else "not_selected",
                        "OPT_DLBM": "031" if is_selected else "011",
                    }
                )
                features.append(
                    {
                        "type": "Feature",
                        "properties": properties,
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [min_lng, min_lat],
                                    [max_lng, min_lat],
                                    [max_lng, max_lat],
                                    [min_lng, max_lat],
                                    [min_lng, min_lat],
                                ]
                            ],
                        },
                    }
                )

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

    def _required_existing_dataset(self, payload: dict[str, Any], key: str) -> Path:
        raw = str(payload.get(key, "")).strip()
        if not raw:
            raise WorldModelV21ValidationError(f"{key} is required")
        path = Path(raw)
        if not path.exists() or (not path.is_file() and not path.is_dir()):
            raise WorldModelV21ValidationError(f"{key} not found: {path}")
        return path

    def _sha256_dataset(self, path: Path) -> str:
        """Hash a file or directory dataset using stable relative member names."""

        digest = hashlib.sha256()
        if path.is_file():
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        if not path.is_dir():
            raise WorldModelV21ValidationError(f"dataset not found: {path}")
        for member in sorted(item for item in path.rglob("*") if item.is_file()):
            digest.update(member.relative_to(path).as_posix().encode("utf-8"))
            with member.open("rb") as source:
                for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()

    def _verify_expected_sha256(self, payload: dict[str, Any], key: str, actual: str) -> None:
        expected = str(payload.get(key) or "").strip().casefold()
        if expected and expected != actual.casefold():
            raise WorldModelV21ValidationError(f"{key} mismatch")

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

    def _validate_reused_prepared_inputs(
        self, payload: dict[str, Any], prepared_dir: Path
    ) -> dict[str, Any]:
        manifest_path = prepared_dir / "paper9_input_snapshot.json"
        expected_keys = {
            "dltb": "dltb_expected_sha256",
            "dem": "dem_expected_sha256",
            "administrative_units": "xzq_expected_sha256",
        }
        expected_present = any(
            str(payload.get(key) or "").strip() for key in expected_keys.values()
        )
        if not manifest_path.exists():
            if expected_present:
                raise WorldModelV21ValidationError(
                    "prepared_dir has no Paper9 input snapshot for governed-product reuse"
                )
            summary = self._read_json(prepared_dir / "prepare_data_summary.json")
            return {
                "input_resolution": None,
                "input_quality": self._prepare_input_quality(
                    summary,
                    administrative_units_present=bool(payload.get("xzq_path")),
                    minimum_dem_coverage=self._optional_float(
                        payload, "minimum_dem_coverage_fraction"
                    )
                    or 0.98,
                    reference_years={
                        "dltb": self._optional_int(payload, "dltb_reference_year"),
                        "dem": self._optional_int(payload, "dem_reference_year"),
                        "administrative_units": self._optional_int(
                            payload, "administrative_reference_year"
                        ),
                    },
                    reference_year_sources=dict(
                        payload.get("reference_year_sources") or {}
                    ),
                    reference_year_authority={
                        str(role): bool(authoritative)
                        for role, authoritative in dict(
                            payload.get("reference_year_authority") or {}
                        ).items()
                    },
                    require_reference_years=bool(
                        payload.get("require_reference_years", False)
                    ),
                    require_authoritative_reference_years=bool(
                        payload.get("require_authoritative_reference_years", False)
                    ),
                ),
            }
        snapshot = self._read_json(manifest_path)
        resolution = snapshot.get("input_resolution") or {}
        for role, expected_key in expected_keys.items():
            expected = str(payload.get(expected_key) or "").strip().casefold()
            if not expected:
                continue
            actual = str((resolution.get(role) or {}).get("source_sha256") or "").casefold()
            if actual != expected:
                raise WorldModelV21ValidationError(
                    f"prepared_dir input snapshot does not match {role} governed product"
                )
        summary = self._read_json(prepared_dir / "prepare_data_summary.json")
        existing_quality = snapshot.get("input_quality") or {}
        reference_years = {
            "dltb": self._optional_int(payload, "dltb_reference_year")
            or (existing_quality.get("reference_years") or {}).get("dltb"),
            "dem": self._optional_int(payload, "dem_reference_year")
            or (existing_quality.get("reference_years") or {}).get("dem"),
            "administrative_units": self._optional_int(
                payload, "administrative_reference_year"
            )
            or (existing_quality.get("reference_years") or {}).get(
                "administrative_units"
            ),
        }
        payload_year_sources = dict(payload.get("reference_year_sources") or {})
        existing_year_sources = dict(existing_quality.get("reference_year_sources") or {})
        reference_year_sources = {
            role: str(
                payload_year_sources.get(role)
                or existing_year_sources.get(role)
                or "missing"
            )
            for role in ("dltb", "dem", "administrative_units")
        }
        payload_year_authority = dict(payload.get("reference_year_authority") or {})
        existing_year_authority = dict(existing_quality.get("reference_year_authority") or {})
        reference_year_authority = {
            role: bool(
                payload_year_authority[role]
                if role in payload_year_authority
                else existing_year_authority.get(role, False)
            )
            for role in ("dltb", "dem", "administrative_units")
        }
        snapshot["input_quality"] = self._prepare_input_quality(
            summary,
            administrative_units_present=bool(resolution.get("administrative_units")),
            minimum_dem_coverage=self._optional_float(
                payload, "minimum_dem_coverage_fraction"
            )
            or float(existing_quality.get("minimum_dem_coverage_fraction") or 0.98),
            spatial_reference_contract=snapshot.get("spatial_reference_contract")
            or existing_quality.get("spatial_reference_contract"),
            administrative_code_contract=snapshot.get("administrative_code_contract")
            or existing_quality.get("administrative_code_contract"),
            reference_years=reference_years,
            reference_year_sources=reference_year_sources,
            reference_year_authority=reference_year_authority,
            require_reference_years=bool(payload.get("require_reference_years", False)),
            require_authoritative_reference_years=bool(
                payload.get("require_authoritative_reference_years", False)
            ),
            maximum_reference_year_gap=self._int_range(
                payload,
                "maximum_reference_year_gap",
                int(existing_quality.get("maximum_reference_year_gap") or 1),
                0,
                100,
            ),
            minimum_admin_code_match=self._optional_float(
                payload, "minimum_admin_code_match_fraction"
            )
            or float(existing_quality.get("minimum_admin_code_match_fraction") or 0.98),
        )
        return snapshot

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
            raise WorldModelV21ValidationError(f"{key} must be between {min_value} and {max_value}")
        return value

    def _optional_float(self, payload: dict[str, Any], key: str) -> float | None:
        raw = payload.get(key)
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise WorldModelV21ValidationError(f"{key} must be numeric") from exc

    def _optional_int(self, payload: dict[str, Any], key: str) -> int | None:
        raw = payload.get(key)
        if raw is None or raw == "":
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise WorldModelV21ValidationError(f"{key} must be an integer") from exc
        if not 1900 <= value <= 2100:
            raise WorldModelV21ValidationError(f"{key} must be between 1900 and 2100")
        return value

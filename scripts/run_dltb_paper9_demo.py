#!/usr/bin/env python3
"""Run phase 2 of the DLTB demo: Paper9 World Model v2.1 A -> D.

The script uses the same service methods as the GIS Data Agent "世界模型
v2.1" tab. It accepts the raw DLTB FileGDB and DEM, can run all four stages,
or can reuse prepared/sample/ONNX artifacts for a shorter live demonstration.
It never promotes the Chongqing rehearsal to Ningxia authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from data_agent.dltb_demo_identity import (
    DATASET_IDS,
    build_dataset_identity,
    dataset_descriptor,
    require_matching_identity,
    require_upstream_dataset_id,
)
from data_agent.world_model_v21 import WorldModelV21Service


def _safe_extract(archive_path: Path, destination: Path, max_bytes: int) -> int:
    """Extract a sample archive without allowing path traversal."""

    destination.mkdir(parents=True, exist_ok=True)
    written = 0
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(destination.resolve())
            except ValueError as exc:
                raise ValueError(f"unsafe archive member: {member.filename}") from exc
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.file_size < 0 or written + member.file_size > max_bytes:
                raise ValueError("archive exceeds configured uncompressed size limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
            written += member.file_size
    return written


def _find_dltb(root: Path) -> Path:
    candidates = sorted(root.rglob("*.gdb")) + sorted(root.rglob("*.gpkg"))
    if not candidates:
        raise FileNotFoundError("no DLTB FileGDB or GeoPackage found")
    for candidate in candidates:
        try:
            from data_agent.local_gis_runtime import inspect_vector

            names = {str(layer.get("name", "")).casefold() for layer in inspect_vector(candidate)}
            if names.intersection({"dltb", "jqdltb", "地类图斑"}):
                return candidate
        except Exception:
            pass
    return candidates[0]


def _find_dem(root: Path) -> Path | None:
    candidates = sorted(root.rglob("*.tif")) + sorted(root.rglob("*.tiff"))
    for candidate in candidates:
        if any(
            token in candidate.name.casefold() for token in ("dem", "elevation", "高程", "gdem")
        ):
            return candidate
    return candidates[0] if candidates else None


def _sha256_path(path: Path) -> str:
    """Hash a file or directory while retaining directory member names."""

    digest = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    if not path.is_dir():
        raise FileNotFoundError(str(path))
    for member in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(member.relative_to(path).as_posix().encode("utf-8"))
        with member.open("rb") as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _profile(name: str) -> dict[str, Any]:
    if name == "smoke":
        return {
            "n_transition_episodes": 3,
            "n_pairwise_states": 50,
            "n_pairwise_actions": 10,
            "n_members": 1,
            "epochs": 2,
            "patience": 1,
            "torch_threads": 2,
            "out_subdir": "tool3_smoke",
        }
    return {
        "n_transition_episodes": 60,
        "n_pairwise_states": 1000,
        "n_pairwise_actions": 50,
        "n_members": 3,
        "epochs": 30,
        "patience": 8,
        "torch_threads": 0,
        "out_subdir": "tool3",
    }


def _read_upstream(path: Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _upstream_product(upstream: dict[str, Any] | None, role: str) -> dict[str, Any] | None:
    if not upstream:
        return None
    product = ((upstream.get("paper9_handoff") or {}).get("products") or {}).get(role)
    return product if isinstance(product, dict) else None


def _explicit_product(path: Path | None, role: str) -> dict[str, Any] | None:
    if not path:
        return None
    resolved = path.expanduser().resolve()
    return {
        "role": role,
        "status": "succeeded",
        "path": str(resolved),
        "sha256": _sha256_path(resolved) if resolved.exists() else None,
        "origin": "explicit_governed_product",
    }


def _resolve_product(product: dict[str, Any] | None, role: str) -> tuple[Path, dict[str, Any]]:
    if not product:
        raise ValueError(f"governed {role} product is missing")
    if product.get("status") != "succeeded":
        raise ValueError(f"governed {role} product is not succeeded: {product.get('status')}")
    raw_path = str(product.get("path") or "").strip()
    if not raw_path:
        raise ValueError(f"governed {role} product has no local path")
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))
    actual = _sha256_path(path)
    expected = str(product.get("sha256") or "").strip().casefold()
    if expected and expected != actual:
        raise ValueError(f"governed {role} product SHA-256 mismatch")
    return path, {**product, "path": str(path), "verified_sha256": actual}


def _reference_year_contract(
    explicit_year: int | None,
    product: dict[str, Any] | None,
) -> dict[str, Any]:
    if explicit_year is not None:
        return {
            "year": explicit_year,
            "source": "operator_supplied",
            "authoritative": True,
        }
    product = product or {}
    year = product.get("reference_year")
    source = str(product.get("reference_year_source") or ("unspecified" if year else "missing"))
    return {
        "year": year,
        "source": source,
        "authoritative": bool(product.get("reference_year_authoritative", False)),
    }


def _production_blockers(
    *,
    mode: str,
    sample_input: bool,
    status: dict[str, Any],
    upstream: dict[str, Any] | None,
    pipeline: dict[str, Any] | None,
    audit: dict[str, Any] | None,
    error: str | None,
    input_quality: dict[str, Any] | None = None,
    input_mode: str = "direct_files",
    governed_roles: set[str] | None = None,
) -> list[str]:
    if mode != "production":
        return []
    blockers: list[str] = []
    if sample_input:
        blockers.append("sample_scope: engineering demo data is not Ningxia authority data")
    governed_roles = governed_roles or set()
    if input_mode != "governed_lake_products":
        blockers.append("paper9_inputs: production requires governed lake products")
    for role in ("dltb", "dem", "administrative_units"):
        if role not in governed_roles:
            blockers.append(f"paper9_inputs: governed {role} product is required")
    if not status.get("finals", {}).get("version_compatible", False):
        blockers.append("paper9_version: approved package/algorithm version is not compatible")
    if upstream is None:
        blockers.append("phase1_report: production requires the phase-1 semantic report")
    else:
        if not upstream.get("production_eligible", False):
            blockers.append("phase1_gate: upstream semantic data is not production eligible")
        if not (upstream.get("quality_gate") or {}).get("production_gate_passed", False):
            blockers.append("phase1_quality: upstream quality gate did not pass")
    if not input_quality:
        blockers.append("paper9_input_quality: Tool 1 input-quality evidence is missing")
    elif not input_quality.get("production_gate_passed", False):
        for finding in input_quality.get("findings") or ["input-quality gate did not pass"]:
            blockers.append(f"paper9_input_quality: {finding}")
    if error:
        blockers.append(f"pipeline:{error}")
    elif not pipeline or pipeline.get("status") != "ok":
        blockers.append("pipeline: A/B/C/D did not complete")
    if not audit:
        blockers.append("paper9_audit: audit evidence is missing")
    elif not audit.get("hard_constraint_passed", False):
        blockers.append("paper9_audit: hard constraints did not pass")
    if audit and not audit.get("all_expected_outputs_exist", False):
        blockers.append("paper9_audit: expected spatial output artifacts are incomplete")
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-id",
        required=True,
        choices=DATASET_IDS,
        help="must match the phase-1 dataset identity when governed products are used",
    )
    source_group = parser.add_mutually_exclusive_group(required=False)
    source_group.add_argument("--source", type=Path, help="DLTB.gdb or a directory containing it")
    source_group.add_argument("--zip", type=Path, help="sample ZIP containing DLTB.gdb and DEM")
    source_group.add_argument(
        "--dltb-product",
        type=Path,
        help="governed DLTB GeoParquet/GPKG product from phase 1",
    )
    parser.add_argument(
        "--dem", type=Path, help="DEM TIFF; required when it is not found beside --source"
    )
    parser.add_argument("--dem-product", type=Path, help="governed DEM COG/GeoTIFF product")
    parser.add_argument("--admin", type=Path, help="direct administrative-boundary dataset")
    parser.add_argument(
        "--admin-product",
        type=Path,
        help="governed administrative-boundary GeoParquet/GPKG product",
    )
    parser.add_argument(
        "--input-mode",
        choices=("auto", "governed", "direct"),
        default="auto",
        help="prefer phase-1 products, require them, or bypass them with direct files",
    )
    parser.add_argument("--dltb-year", type=int, help="DLTB reference year override")
    parser.add_argument("--dem-year", type=int, help="DEM reference year override")
    parser.add_argument("--admin-year", type=int, help="administrative reference year override")
    parser.add_argument("--administrative-code-field", help="administrative-unit code field")
    parser.add_argument(
        "--administrative-reference-mode",
        choices=("auto", "code", "spatial"),
        default="auto",
        help="use an administrative code contract or a spatial township-name reference",
    )
    parser.add_argument("--dltb-admin-code-field", default="QSDWDM")
    parser.add_argument("--maximum-reference-year-gap", type=int, default=1)
    parser.add_argument("--paper9-repo", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--prepared-dir", type=Path)
    parser.add_argument("--ensemble-dir", type=Path)
    parser.add_argument("--upstream-report", type=Path, help="phase-1 semantic report JSON")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("rehearsal", "production"), default="rehearsal")
    parser.add_argument("--profile", choices=("smoke", "standard"), default="smoke")
    parser.add_argument(
        "--reuse-existing", action="store_true", help="reuse A/B/C artifacts and run D"
    )
    parser.add_argument(
        "--no-replan", action="store_true", help="do not perform the single bounded Tool 4 retry"
    )
    parser.add_argument("--horizon", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument("--n-episodes", type=int, default=1)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--proj-crs", default="EPSG:32648")
    parser.add_argument(
        "--slope-method",
        choices=("auto", "from_field", "gradient_geographic", "horn_projected"),
        default="auto",
        help=(
            "slope source for Paper9 Tool 1; auto uses an existing slope_mean "
            "field when present, otherwise derives slope from DEM"
        ),
    )
    parser.add_argument("--slope-field", default="slope_mean")
    parser.add_argument("--keep-extracted", action="store_true")
    parser.add_argument("--max-uncompressed-gb", type=float, default=20.0)
    args = parser.parse_args()

    work_dir = args.work_dir.expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    output = args.output.expanduser().resolve()
    archive = args.zip.expanduser().resolve() if args.zip else None
    temporary: Path | None = None
    extracted_bytes = None
    pipeline: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    input_quality: dict[str, Any] | None = None
    error: str | None = None
    upstream_path = args.upstream_report.expanduser().resolve() if args.upstream_report else None
    upstream = _read_upstream(upstream_path)
    try:
        upstream_identity = require_upstream_dataset_id(
            upstream,
            args.dataset_id,
            required=args.input_mode == "governed" or upstream_path is not None,
        )
    except ValueError as exc:
        parser.error(str(exc))
    input_mode = "direct_files"
    governed_roles: set[str] = set()
    input_products: dict[str, dict[str, Any] | None] = {
        "dltb": None,
        "dem": None,
        "administrative_units": None,
    }

    try:
        dltb_product = _explicit_product(args.dltb_product, "dltb") or _upstream_product(
            upstream, "dltb"
        )
        dem_product = _explicit_product(args.dem_product, "dem") or _upstream_product(
            upstream, "dem"
        )
        admin_product = _explicit_product(
            args.admin_product, "administrative_units"
        ) or _upstream_product(upstream, "administrative_units")
        prefer_governed = args.input_mode == "governed" or (
            args.input_mode == "auto" and bool(dltb_product)
        )

        root: Path | None = None
        if prefer_governed:
            try:
                dltb, input_products["dltb"] = _resolve_product(dltb_product, "dltb")
                governed_roles.add("dltb")
            except (FileNotFoundError, ValueError) as exc:
                if args.input_mode == "governed":
                    parser.error(str(exc))
                prefer_governed = False

        if not prefer_governed:
            if archive:
                if not archive.is_file():
                    parser.error(f"sample ZIP does not exist: {archive}")
                extraction = (
                    work_dir / "input_snapshot"
                    if args.keep_extracted
                    else Path(tempfile.mkdtemp(prefix="gda-paper9-"))
                )
                extracted_bytes = _safe_extract(
                    archive,
                    extraction,
                    max(1, int(args.max_uncompressed_gb * 1024**3)),
                )
                if not args.keep_extracted:
                    temporary = extraction
                root = extraction
            elif args.source:
                root = args.source.expanduser().resolve()
                if not root.exists():
                    parser.error(f"source does not exist: {root}")
            else:
                parser.error(
                    "provide --upstream-report/--dltb-product for governed input, "
                    "or --source/--zip for direct input"
                )
            dltb = (
                root
                if root.name.casefold().endswith((".gdb", ".gpkg"))
                else _find_dltb(root)
            )

        if args.input_mode == "governed" and not dem_product:
            parser.error("governed DEM product is missing")
        if args.input_mode != "direct" and dem_product:
            try:
                dem, input_products["dem"] = _resolve_product(dem_product, "dem")
                governed_roles.add("dem")
            except (FileNotFoundError, ValueError) as exc:
                if args.input_mode == "governed":
                    parser.error(str(exc))
                dem = (
                    args.dem.expanduser().resolve()
                    if args.dem
                    else _find_dem(root)
                    if root
                    else None
                )
        else:
            dem = args.dem.expanduser().resolve() if args.dem else _find_dem(root) if root else None
        if not dem or not dem.is_file():
            parser.error("DEM TIFF is required for Paper9 A / Tool 1")
        if (
            args.input_mode != "direct"
            and admin_product
            and admin_product.get("status") != "missing"
        ):
            try:
                admin, input_products["administrative_units"] = _resolve_product(
                    admin_product, "administrative_units"
                )
                governed_roles.add("administrative_units")
            except (FileNotFoundError, ValueError) as exc:
                if args.input_mode == "governed":
                    parser.error(str(exc))
                admin = args.admin.expanduser().resolve() if args.admin else None
        else:
            admin = args.admin.expanduser().resolve() if args.admin else None
        if admin and not admin.exists():
            parser.error(f"administrative dataset does not exist: {admin}")
        if {"dltb", "dem"}.issubset(governed_roles):
            input_mode = "governed_lake_products"
        elif governed_roles:
            input_mode = "mixed_governed_and_direct"
        phase2_identity = build_dataset_identity(
            dataset_id=args.dataset_id,
            dltb=dltb,
            dem=dem,
            administrative_units=admin,
            reference_years={
                "dltb": args.dltb_year,
                "dem": args.dem_year,
                "administrative_units": args.admin_year,
            },
            input_mode=input_mode,
            validate_known_sources=input_mode == "direct_files",
        )
        if input_mode == "direct_files":
            try:
                require_matching_identity(phase2_identity)
            except ValueError as exc:
                parser.error(str(exc))
        elif upstream_identity:
            phase2_identity.update(
                {
                    "upstream_manifest_sha256": upstream_identity.get("manifest_sha256"),
                    "upstream_verification_status": upstream_identity.get(
                        "verification_status"
                    ),
                    "verification_status": "verified_from_phase1",
                    "identity_verified": bool(upstream_identity.get("identity_verified")),
                }
            )
        repo = args.paper9_repo.expanduser().resolve()
        prepared = (
            args.prepared_dir.expanduser().resolve() if args.prepared_dir else work_dir / "prepared"
        )
        profile = _profile(args.profile)
        ensemble = (
            args.ensemble_dir.expanduser().resolve()
            if args.ensemble_dir
            else prepared / profile["out_subdir"]
        )
        status = WorldModelV21Service(repo_path=repo).status()
        sample_input = args.dataset_id != "ningxia"
        reference_year_contract = {
            "dltb": _reference_year_contract(args.dltb_year, input_products["dltb"]),
            "dem": _reference_year_contract(args.dem_year, input_products["dem"]),
            "administrative_units": _reference_year_contract(
                args.admin_year, input_products["administrative_units"]
            ),
        }
        reference_years = {
            role: contract.get("year") for role, contract in reference_year_contract.items()
        }
        reference_year_sources = {
            role: str(contract.get("source") or "missing")
            for role, contract in reference_year_contract.items()
        }
        reference_year_authority = {
            role: bool(contract.get("authoritative", False))
            for role, contract in reference_year_contract.items()
        }
        phase2_identity["reference_years"] = reference_years
        governed_handoff_id = str(
            ((upstream or {}).get("paper9_handoff") or {})
            .get("catalog_entry", {})
            .get("handoff_id")
            or ""
        ).strip()
        handoff_entry_path = str(
            ((upstream or {}).get("paper9_handoff") or {})
            .get("catalog_entry", {})
            .get("entry_path")
            or ""
        ).strip()
        if governed_handoff_id and handoff_entry_path:
            handoff_entry = Path(handoff_entry_path).expanduser().resolve()
            if handoff_entry.parent.name == "paper9_handoffs":
                os.environ["GDA_FILE_LAKE_ROOT"] = str(handoff_entry.parent.parent)

        report: dict[str, Any] = {
            "schema": "gda.dltb-paper9-demo-report.v1",
            "stage": "phase2_paper9_world_model_v21",
            "dataset_identity": phase2_identity,
            "sample_scope": dataset_descriptor(args.dataset_id)["sample_scope"],
            "production_eligible": False,
            "inputs": {
                "dltb": {"path": str(dltb), "sha256": _sha256_path(dltb)},
                "dem": {"path": str(dem), "sha256": _sha256_path(dem)},
                "administrative_units": (
                    {"path": str(admin), "sha256": _sha256_path(admin)} if admin else None
                ),
                "input_mode": input_mode,
                "governed_products": input_products,
                "archive": str(archive) if archive else None,
                "extracted_bytes": extracted_bytes,
            },
            "upstream_phase1": {
                "path": str(upstream_path) if upstream_path else None,
                "report": upstream,
            },
            "configuration": {
                "profile": args.profile,
                "reuse_existing": args.reuse_existing,
                "prepared_dir": str(prepared),
                "ensemble_dir": str(ensemble),
                "env_kind": "county",
                "horizon": args.horizon,
                "top_k": args.top_k,
                "n_episodes": args.n_episodes,
                "threads": args.threads,
                "proj_crs": args.proj_crs,
                "slope_method": args.slope_method,
                "slope_field": args.slope_field,
                "reference_years": reference_years,
                "reference_year_contract": reference_year_contract,
                "administrative_reference_mode": args.administrative_reference_mode,
                "maximum_reference_year_gap": args.maximum_reference_year_gap,
                **profile,
            },
            "paper9_status": status,
        }
        if args.mode == "production" and not status.get("finals", {}).get(
            "version_compatible", False
        ):
            error = "approved Paper9 package/algorithm version is not compatible"
        else:
            service = WorldModelV21Service(repo_path=repo)
            payload = {
                "dltb_path": str(dltb),
                "dem_path": str(dem),
                "prepared_dir": str(prepared),
                "ensemble_dir": str(ensemble) if args.reuse_existing else "",
                "reuse_existing": args.reuse_existing,
                "run_prepare": True,
                "run_sample": True,
                "run_train": True,
                "run_plan": True,
                "run_phase_bc": True,
                "env_kind": "county",
                "horizon": args.horizon,
                "top_k": args.top_k,
                "n_episodes": args.n_episodes,
                "continuation": "greedy",
                "scoring": "reward",
                "threads": args.threads,
                "proj_crs": args.proj_crs,
                "slope_method": args.slope_method,
                "slope_field": args.slope_field,
                "governed_handoff_id": governed_handoff_id
                if input_mode == "governed_lake_products"
                else None,
                "dltb_reference_year": reference_years["dltb"],
                "dem_reference_year": reference_years["dem"],
                "administrative_reference_year": reference_years[
                    "administrative_units"
                ],
                "require_reference_years": (
                    input_mode == "governed_lake_products" and args.mode == "production"
                ),
                "require_authoritative_reference_years": (
                    input_mode == "governed_lake_products" and args.mode == "production"
                ),
                "reference_year_sources": reference_year_sources,
                "reference_year_authority": reference_year_authority,
                "maximum_reference_year_gap": args.maximum_reference_year_gap,
                "administrative_code_field": args.administrative_code_field,
                "administrative_reference_mode": args.administrative_reference_mode,
                "reference_layer": (
                    str(admin)
                    if admin
                    and (
                        args.administrative_reference_mode == "spatial"
                        or (
                            args.administrative_reference_mode == "auto"
                            and args.dataset_id in {"bishan", "dongxing"}
                        )
                    )
                    else ""
                ),
                "reference_name_field": "XZQMC",
                "dltb_admin_code_field": args.dltb_admin_code_field,
                "dataset_id": args.dataset_id,
                "cultivated_area_floor_delta_ha": 0.0,
                "xzq_path": str(admin) if admin else "",
                "dltb_expected_sha256": (
                    (input_products["dltb"] or {}).get("verified_sha256")
                    if "dltb" in governed_roles
                    else None
                ),
                "dem_expected_sha256": (
                    (input_products["dem"] or {}).get("verified_sha256")
                    if "dem" in governed_roles
                    else None
                ),
                "xzq_expected_sha256": (
                    (input_products["administrative_units"] or {}).get("verified_sha256")
                    if "administrative_units" in governed_roles
                    else None
                ),
                **profile,
            }
            started = time.monotonic()
            try:
                pipeline = service.run_pipeline(payload, user_id="dltb-paper9-demo")
            except Exception as exc:
                error = str(exc)
            report["pipeline_elapsed_seconds"] = round(time.monotonic() - started, 3)
            report["pipeline"] = pipeline
            prepare_step = next(
                (
                    step
                    for step in (pipeline or {}).get("steps", [])
                    if isinstance(step, dict) and step.get("step") == "prepare"
                ),
                None,
            )
            input_quality = (
                prepare_step.get("input_quality") if isinstance(prepare_step, dict) else None
            )
            report["input_quality_gate"] = input_quality
            report["derived_publication"] = (pipeline or {}).get("derived_publication")
            plan_result = pipeline.get("plan_result") if pipeline else None
            audit = (pipeline or {}).get("audit_result")
            if not audit and isinstance(plan_result, dict) and plan_result.get("out_dir"):
                try:
                    audit = service.audit_run(
                        out_dir=plan_result["out_dir"],
                        attempt=0,
                        cultivated_area_floor_delta_ha=0.0,
                    )
                except Exception as exc:
                    audit = {"status": "error", "error": str(exc)}
            report["audit_attempts"] = [audit] if audit else []
            if not args.no_replan and audit and audit.get("next_action") == "replan_once":
                replan_payload = {
                    "prepared_dir": str(prepared),
                    "ensemble_dir": str((pipeline or {}).get("ensemble_dir") or ensemble),
                    "env_kind": "county",
                    "horizon": min(20, max(2, args.horizon + 1)),
                    "top_k": min(500, max(5, args.top_k)),
                    "n_episodes": args.n_episodes,
                    "continuation": "greedy",
                    "scoring": "reward",
                    "threads": args.threads,
                    "seed_offset": 1,
                    "proj_crs": args.proj_crs,
                    "cultivated_area_floor_delta_ha": 0.0,
                }
                try:
                    report["replan"] = service.run_plan(replan_payload, user_id="dltb-paper9-demo")
                    audit = service.audit_run(
                        out_dir=report["replan"]["out_dir"],
                        attempt=1,
                        cultivated_area_floor_delta_ha=0.0,
                    )
                    report["audit_attempts"].append(audit)
                except Exception as exc:
                    report["replan"] = {"status": "error", "error": str(exc)}
                    audit = {"status": "error", "error": str(exc), "attempt": 1}
                    report["audit_attempts"].append(audit)
            report["final_audit"] = audit

        blockers = _production_blockers(
            mode=args.mode,
            sample_input=sample_input,
            status=status,
            upstream=upstream,
            pipeline=pipeline,
            audit=audit,
            error=error,
            input_quality=input_quality,
            input_mode=input_mode,
            governed_roles=governed_roles,
        )
        report["error"] = error
        report["production_blockers"] = blockers
        report["production_eligible"] = args.mode == "production" and not blockers
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "output": str(output),
                    "dataset_id": args.dataset_id,
                    "pipeline_status": pipeline.get("status") if pipeline else "blocked",
                    "steps": [
                        {"step": step.get("step"), "status": step.get("status", "ok")}
                        for step in (pipeline or {}).get("steps", [])
                    ],
                    "audit": (audit or {}).get("hard_constraint_passed") if audit else None,
                    "production_eligible": report["production_eligible"],
                    "production_blockers": blockers,
                },
                ensure_ascii=False,
            )
        )
        if error:
            return 1
        return 2 if args.mode == "production" and blockers else 0
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run phase 1 of the DLTB demo: governed ingest through semantic query.

Examples::

    python scripts/run_dltb_vertical_demo.py \
      --zip D:\\NX_INCOMING\\DLTB.gdb.zip --lake D:\\GDA_DATA\\file_lake \
      --output D:\\GDA_DATA\\reports\\dltb.json --mode production

This phase intentionally stops after governed semantic query. Paper9 belongs
to scripts/run_dltb_paper9_demo.py and consumes this phase's report as lineage
and production-gate evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.dltb_demo_identity import (
    DATASET_IDS,
    build_dataset_identity,
    require_matching_identity,
)
from data_agent.dltb_llm_query import query_dltb_with_llm
from data_agent.dltb_multi_engine_query import query_dltb
from data_agent.dltb_vertical_demo import DLTBVerticalDemo
from data_agent.offline_ingest import OfflineIngestStore


def _safe_extract(archive_path: Path, destination: Path, max_bytes: int) -> int:
    """Diagnostic-only extraction using the same ZIP security contract as the API."""
    destination.mkdir(parents=True, exist_ok=True)
    written = 0
    limits = OfflineIngestStore._archive_limits()
    limits["max_uncompressed_bytes"] = max_bytes
    limits["max_file_bytes"] = max_bytes
    with zipfile.ZipFile(archive_path) as archive:
        entries, summary = OfflineIngestStore._validated_zip_entries(archive, limits=limits)
        if summary["uncompressed_bytes"] > max_bytes:
            raise ValueError("archive exceeds configured uncompressed size limit")
        for member, relative in entries:
            target = destination.joinpath(*relative.parts)
            if member.is_dir() or member.filename.endswith(("/", "\\")):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, target.open("wb") as output:
                while block := source.read(8 * 1024 * 1024):
                    written += len(block)
                    if written > max_bytes:
                        raise ValueError("archive exceeds configured uncompressed size limit")
                    output.write(block)
    return written


def _find_dltb(root: Path) -> Path:
    candidates = sorted(root.rglob("*.gdb")) + sorted(root.rglob("*.gpkg"))
    if not candidates:
        raise FileNotFoundError("no DLTB FileGDB or GeoPackage found")
    for candidate in candidates:
        try:
            from data_agent.local_gis_runtime import inspect_vector

            if any(
                str(layer.get("name", "")).casefold() in {"dltb", "jqdltb", "地类图斑"}
                for layer in inspect_vector(candidate)
            ):
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
    return None


def _stage_asset(source: Path, inbox: Path) -> Path:
    """Copy one dataset into the controlled inbox, preserving bundles."""

    target = inbox / source.name
    if target.exists():
        raise FileExistsError(f"controlled inbox name collision: {target.name}")
    if source.is_dir():
        shutil.copytree(source, target)
        return target
    if source.suffix.casefold() == ".shp":
        for part in sorted(source.parent.glob(f"{source.stem}.*")):
            if part.is_file():
                shutil.copy2(part, inbox / part.name)
        return target
    shutil.copy2(source, target)
    return target


def _materialized_outputs(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list(((result or {}).get("materialization") or {}).get("outputs") or [])


def _infer_reference_year(*values: str | Path | None) -> int | None:
    """Infer a four-digit data year from operator paths when no year is supplied."""

    for value in values:
        if value is None:
            continue
        matches = re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", str(value))
        if matches:
            return int(matches[-1])
    return None


def _reference_year_metadata(
    explicit_year: int | None,
    *inference_values: str | Path | None,
) -> dict[str, Any]:
    if explicit_year is not None:
        return {
            "year": explicit_year,
            "source": "operator_supplied",
            "authoritative": True,
        }
    inferred_year = _infer_reference_year(*inference_values)
    if inferred_year is not None:
        return {
            "year": inferred_year,
            "source": "path_inferred",
            "authoritative": False,
        }
    return {"year": None, "source": "missing", "authoritative": False}


def _product_reference(
    output: dict[str, Any] | None,
    role: str,
    *,
    reference_year: int | None = None,
    reference_year_source: str = "missing",
    reference_year_authoritative: bool = False,
) -> dict[str, Any]:
    if not output:
        return {
            "role": role,
            "status": "missing",
            "reference_year": reference_year,
            "reference_year_source": reference_year_source,
            "reference_year_authoritative": reference_year_authoritative,
        }
    mapping = output.get("mapping") or {}
    profile = output.get("materialization_profile") or {}
    crs = profile.get("crs")
    bbox = profile.get("bbox")
    stac_path = str(output.get("stac_item_path") or "").strip()
    if stac_path:
        try:
            stac = json.loads(Path(stac_path).read_text(encoding="utf-8"))
            properties = stac.get("properties") or {}
            crs = crs or properties.get("proj:epsg")
            bbox = bbox or stac.get("bbox")
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "role": role,
        "status": output.get("execution_status"),
        "product_id": output.get("target_id"),
        "canonical_dataset": output.get("canonical_dataset"),
        "path": output.get("target_path"),
        "locator": output.get("target_locator"),
        "format": output.get("target_format"),
        "sha256": output.get("target_sha256"),
        "source_asset_id": output.get("source_asset_id"),
        "source_layer": output.get("source_layer"),
        "mapping_status": mapping.get("status"),
        "contract_authority": mapping.get("contract_authority"),
        "crs": crs,
        "bbox": bbox,
        "feature_count": profile.get("feature_count"),
        "columns": profile.get("columns"),
        "geometry_types": profile.get("geometry_types"),
        "reference_year": reference_year,
        "reference_year_source": reference_year_source,
        "reference_year_authoritative": reference_year_authoritative,
    }


def _paper9_product_handoff(
    materialization: dict[str, Any] | None,
    *,
    dem_name: str | None,
    admin_name: str | None,
    reference_years: dict[str, int | None] | None = None,
    reference_year_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reference_years = reference_years or {}
    reference_year_metadata = reference_year_metadata or {}
    outputs = _materialized_outputs(materialization)
    dltb = next(
        (
            item
            for item in outputs
            if item.get("canonical_dataset") == "DLTB"
            or str(item.get("source_layer") or "").casefold() in {"dltb", "jqdltb", "地类图斑"}
        ),
        None,
    )

    def by_source_name(name: str | None, *, kind: str) -> dict[str, Any] | None:
        if not name:
            return None
        needle = name.casefold()
        return next(
            (
                item
                for item in outputs
                if kind == str(item.get("target_kind") or "")
                and needle in str(item.get("source_raw_path") or "").casefold()
            ),
            None,
        )

    dem = by_source_name(dem_name, kind="cog_stac")
    admin_candidates = [
        item
        for item in outputs
        if str(item.get("target_kind") or "") == "postgis_or_geoparquet"
        and (
            not admin_name
            or str(item.get("source_raw_path") or "")
            .casefold()
            .find(admin_name.casefold())
            >= 0
        )
    ]
    # A FileGDB may contain multiple boundary layers. Prefer the layer that
    # exposes the standard XZQDM code; CJDCQ is a township detail layer and
    # cannot satisfy the Paper9 administrative-unit contract by itself.
    admin = next(
        (
            item
            for item in admin_candidates
            if "XZQDM"
            in {
                str(column)
                for column in (item.get("materialization_profile") or {}).get("columns")
                or []
            }
            or str(item.get("source_layer") or "").casefold() == "xzq"
        ),
        admin_candidates[0] if admin_candidates else None,
    )
    products = {
        "dltb": _product_reference(
            dltb,
            "dltb",
            reference_year=reference_years.get("dltb"),
            reference_year_source=str(
                (reference_year_metadata.get("dltb") or {}).get("source") or "missing"
            ),
            reference_year_authoritative=bool(
                (reference_year_metadata.get("dltb") or {}).get("authoritative", False)
            ),
        ),
        "dem": _product_reference(
            dem,
            "dem",
            reference_year=reference_years.get("dem"),
            reference_year_source=str(
                (reference_year_metadata.get("dem") or {}).get("source") or "missing"
            ),
            reference_year_authoritative=bool(
                (reference_year_metadata.get("dem") or {}).get("authoritative", False)
            ),
        ),
        "administrative_units": _product_reference(
            admin,
            "administrative_units",
            reference_year=reference_years.get("administrative_units"),
            reference_year_source=str(
                (reference_year_metadata.get("administrative_units") or {}).get("source")
                or "missing"
            ),
            reference_year_authoritative=bool(
                (reference_year_metadata.get("administrative_units") or {}).get(
                    "authoritative", False
                )
            ),
        ),
    }
    return {
        "products": products,
        "governed_input_ready": all(
            products[role].get("status") == "succeeded" and products[role].get("path")
            for role in ("dltb", "dem")
        ),
        "administrative_units_ready": (
            products["administrative_units"].get("status") == "succeeded"
            and bool(products["administrative_units"].get("path"))
        ),
    }


def _publish_paper9_handoff(
    lake: Path,
    handoff: dict[str, Any],
    *,
    phase1_report: Path,
    source: Path,
    quality_status: str,
    production_eligible: bool,
    plan_id: str | None,
) -> dict[str, Any]:
    """Publish one discoverable phase-1 to Paper9 handoff inside the lake."""

    handoff_id = plan_id or f"scan-{source.stem}"
    handoff_dir = lake / "paper9_handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC).isoformat()
    entry = {
        "schema": "gda.paper9-governed-input.v1",
        "handoff_id": handoff_id,
        "created_at": created_at,
        "phase1_report": str(phase1_report),
        "source": str(source),
        "quality_status": quality_status,
        "production_eligible": production_eligible,
        **handoff,
    }
    entry_path = handoff_dir / f"{handoff_id}.json"
    entry_path.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    catalog_path = handoff_dir / "catalog.json"
    catalog = {"schema": "gda.paper9-governed-input-catalog.v1", "items": []}
    if catalog_path.exists():
        try:
            existing = json.loads(catalog_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                catalog = existing
        except (OSError, json.JSONDecodeError):
            pass
    items = [
        item
        for item in catalog.get("items") or []
        if isinstance(item, dict) and item.get("handoff_id") != handoff_id
    ]
    items.append(entry)
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    catalog.update({"updated_at": created_at, "items": items[:100]})
    catalog_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return {
        "handoff_id": handoff_id,
        "entry_path": str(entry_path),
        "catalog_path": str(catalog_path),
    }


def _quality_gate_summary(deep_quality: dict[str, Any]) -> dict[str, Any]:
    """Turn the durable deep-quality payload into operator-facing reasons."""

    payload = deep_quality.get("deep_quality") or {}
    items = payload.get("items") or []
    findings: list[dict[str, Any]] = []
    for item in items:
        if item.get("status") == "pass":
            continue
        checks = item.get("checks") or {}
        reasons: list[str] = []
        mapping_status = item.get("semantic_mapping_status")
        if mapping_status and mapping_status != "accepted":
            reasons.append(f"semantic_mapping:{mapping_status}")
        for key, label in (
            ("invalid_geometry_count", "invalid_geometry"),
            ("empty_geometry_count", "empty_geometry"),
            ("null_geometry_count", "null_geometry"),
            ("duplicate_key_count", "duplicate_key"),
        ):
            value = checks.get(key)
            if isinstance(value, (int, float)) and value:
                reasons.append(f"{label}:{value}")
        fraction = checks.get("sample_valid_fraction")
        if isinstance(fraction, (int, float)) and fraction < 1:
            reasons.append(f"raster_sample_valid_fraction:{fraction:.6f}")
        if not reasons:
            reasons.append(f"quality_status:{item.get('status', 'unknown')}")
        findings.append(
            {
                "asset_id": item.get("asset_id"),
                "asset_name": item.get("asset_name"),
                "layer": item.get("layer"),
                "status": item.get("status"),
                "reasons": reasons,
                "checks": checks,
            }
        )
    return {
        "status": deep_quality.get("status") or payload.get("status") or "unknown",
        "counts": deep_quality.get("counts") or payload.get("counts") or {},
        "findings": findings,
        "production_gate_passed": not findings and (deep_quality.get("status") == "pass"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-id",
        required=True,
        choices=DATASET_IDS,
        help="explicit dataset identity; it is never inferred from a file name",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--source", type=Path, help="DLTB.gdb, DLTB.gpkg, or an extracted incoming directory"
    )
    source_group.add_argument(
        "--zip", type=Path, help="sample/incoming ZIP containing a DLTB FileGDB or GeoPackage"
    )
    parser.add_argument("--dem", type=Path, help="optional DEM TIFF to govern for Paper9 phase 2")
    parser.add_argument(
        "--admin",
        type=Path,
        help="optional administrative-boundary GDB/SHP/GPKG for Paper9 phase 2",
    )
    parser.add_argument("--dltb-year", type=int, help="DLTB reference year")
    parser.add_argument("--dem-year", type=int, help="DEM reference year")
    parser.add_argument("--admin-year", type=int, help="administrative-boundary reference year")
    parser.add_argument("--lake", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("rehearsal", "production"), default="rehearsal")
    parser.add_argument(
        "--semantic-query-mode",
        choices=("llm", "deterministic"),
        default="llm",
        help="semantic planner; llm calls configured Qwen, deterministic is diagnostic-only",
    )
    parser.add_argument(
        "--semantic-execution-engine",
        choices=("postgis", "lake", "geopandas"),
        default="postgis",
        help="query executor; PostGIS is the production default, lake is the offline SQL path",
    )
    parser.add_argument("--keep-extracted", action="store_true")
    parser.add_argument("--max-uncompressed-gb", type=float, default=20.0)
    args = parser.parse_args()

    lake = args.lake.expanduser().resolve()
    output = args.output.expanduser().resolve()
    archive = args.zip.expanduser().resolve() if args.zip else None
    temporary: Path | None = None
    extracted_bytes = None
    try:
        if archive:
            if not archive.is_file():
                parser.error(f"sample ZIP does not exist: {archive}")
            extraction = (
                lake / "dltb_sample_extracted"
                if args.keep_extracted
                else Path(tempfile.mkdtemp(prefix="gda-dltb-"))
            )
            extracted_bytes = _safe_extract(
                archive, extraction, max(1, int(args.max_uncompressed_gb * 1024**3))
            )
            if not args.keep_extracted:
                temporary = extraction
            root = extraction
        else:
            root = args.source.expanduser().resolve()
            if not root.exists():
                parser.error(f"source does not exist: {root}")
        dltb = (
            root
            if root.name.casefold().endswith((".gdb", ".gpkg"))
            else _find_dltb(root)
        )
        dem = args.dem.expanduser().resolve() if args.dem else _find_dem(root)
        admin = args.admin.expanduser().resolve() if args.admin else None
        if dem and not dem.is_file():
            parser.error(f"DEM does not exist: {dem}")
        if admin and not admin.exists():
            parser.error(f"administrative dataset does not exist: {admin}")
        reference_year_metadata = {
            "dltb": _reference_year_metadata(args.dltb_year, dltb, root),
            "dem": _reference_year_metadata(args.dem_year, dem),
            "administrative_units": _reference_year_metadata(args.admin_year, admin),
        }
        reference_years = {
            role: metadata.get("year") for role, metadata in reference_year_metadata.items()
        }
        for role, year in reference_years.items():
            if year is not None and not 1900 <= year <= 2100:
                parser.error(f"{role} reference year must be between 1900 and 2100")
        dataset_identity = build_dataset_identity(
            dataset_id=args.dataset_id,
            dltb=dltb,
            dem=dem,
            administrative_units=admin,
            reference_years=reference_years,
            input_mode="browser_zip" if archive else "direct_local_diagnostic",
        )
        try:
            require_matching_identity(dataset_identity)
        except ValueError as exc:
            parser.error(str(exc))
        # A controlled inbox prevents unrelated sample layers from entering
        # this single-dataset demonstration.
        inbox = lake / "dltb_semantic_inbox"
        if inbox.exists():
            shutil.rmtree(inbox)
        inbox.mkdir(parents=True)
        _stage_asset(dltb, inbox)
        staged_dem = _stage_asset(dem, inbox) if dem else None
        staged_admin = _stage_asset(admin, inbox) if admin else None
        os.environ["GDA_LOCAL_INGEST_DIRS"] = str(inbox)
        store = OfflineIngestStore(lake)
        scan = store.scan_local_path(inbox, actor="dltb-semantic-demo")
        deep_quality = store.run_deep_quality(scan["run_id"], actor="dltb-semantic-demo")
        quality_gate = _quality_gate_summary(deep_quality)
        plan = None
        plan_error = None
        try:
            plan = store.create_standardization_plan(
                scan["run_id"],
                actor="dltb-semantic-demo",
                allow_review=args.mode == "rehearsal",
            )
        except ValueError as exc:
            plan_error = str(exc)
        materialization = None
        if plan:
            materialization = store.execute_standardization_plan(
                plan["run_id"], actor="dltb-semantic-demo", vector_format="Parquet"
            )
        binding = None
        binding_error = None
        if plan:
            try:
                binding = store.create_ontology_binding(
                    plan["run_id"],
                    actor="dltb-semantic-demo",
                    ontology_version="2.3.0",
                    binding_mode=args.mode,
                )
            except ValueError as exc:
                binding_error = str(exc)
        elif plan_error:
            binding_error = f"not attempted: standardization plan blocked ({plan_error})"
        projection = None
        projection_error = None
        if plan:
            try:
                projection = DLTBVerticalDemo(store).build_projection(
                    plan["run_id"],
                    actor="dltb-semantic-demo",
                    mode=args.mode,
                    publish_postgis=args.semantic_execution_engine == "postgis",
                )
            except Exception as exc:
                projection_error = str(exc)
        elif plan_error:
            projection_error = f"not attempted: standardization plan blocked ({plan_error})"
        queries = []
        semantic_query_errors: list[str] = []
        if projection:
            projection_path = projection["projection"]["projection_id"]
            projection_file = (
                lake / "semantic_products" / projection_path / "semantic_projection.json"
            )
            for question in (
                "各地类图斑数量和面积是多少？",
                "列出面积属性与几何面积差异较大的图斑",
            ):
                try:
                    if args.semantic_execution_engine in {"postgis", "lake"}:
                        if args.semantic_query_mode != "llm":
                            raise ValueError(
                                "deterministic semantic queries require "
                                "--semantic-execution-engine geopandas"
                            )
                        queries.append(
                            query_dltb(
                                projection_file,
                                question,
                                execution_engine=args.semantic_execution_engine,
                            )
                        )
                    elif args.semantic_query_mode == "llm":
                        queries.append(query_dltb_with_llm(projection_file, question))
                    else:
                        queries.append(DLTBVerticalDemo.query(projection_file, question))
                except Exception as exc:
                    semantic_query_errors.append(f"{question}: {exc}")
        sample_input = args.dataset_id != "ningxia"
        production_blockers = []
        if args.mode == "production":
            if sample_input:
                production_blockers.append(
                    f"dataset_scope:{dataset_identity['sample_scope']}"
                )
            if plan_error:
                production_blockers.append(f"standardization:{plan_error}")
            if binding_error:
                production_blockers.append(f"ontology_binding:{binding_error}")
            if projection_error:
                production_blockers.append(f"semantic_projection:{projection_error}")
            production_blockers.extend(
                f"quality:{finding['layer']}:{reason}"
                for finding in quality_gate["findings"]
                for reason in finding["reasons"]
            )
        handoff = _paper9_product_handoff(
            materialization,
            dem_name=staged_dem.name if staged_dem else None,
            admin_name=staged_admin.name if staged_admin else None,
            reference_years=reference_years,
            reference_year_metadata=reference_year_metadata,
        )
        handoff["dataset_identity"] = {
            "dataset_id": dataset_identity["dataset_id"],
            "dataset_name": dataset_identity["dataset_name"],
            "manifest_sha256": dataset_identity["manifest_sha256"],
            "verification_status": dataset_identity["verification_status"],
        }
        report = {
            "schema": "gda.dltb-semantic-demo-report.v2",
            "dataset_identity": dataset_identity,
            "sample_scope": dataset_identity["sample_scope"],
            "production_eligible": bool(
                args.mode == "production"
                and args.dataset_id == "ningxia"
                and projection
                and projection["projection"].get("production_eligible")
                and binding
                and binding.get("ontology_binding", {}).get("production_eligible")
            ),
            "source": str(archive or dltb),
            "extracted_bytes": extracted_bytes,
            "dltb_source": str(dltb),
            "paper9_context_sources": {
                "dem": str(dem) if dem else None,
                "administrative_units": str(admin) if admin else None,
            },
            "data_time_contract": {
                "reference_years": reference_years,
                "reference_year_metadata": reference_year_metadata,
                "authority": "operator_supplied_or_path_inferred_with_provenance",
            },
            "scan": scan,
            "deep_quality": deep_quality,
            "quality_gate": quality_gate,
            "standardization_plan": plan,
            "standardization_plan_error": plan_error,
            "materialization": materialization,
            "ontology_binding": binding,
            "ontology_binding_error": binding_error,
            "semantic_projection": projection,
            "semantic_projection_error": projection_error,
            "semantic_queries": queries,
            "semantic_query_errors": semantic_query_errors,
            "semantic_query_mode": args.semantic_query_mode,
            "semantic_execution_engine": args.semantic_execution_engine,
            "paper9_handoff": {
                "next_stage": "world_model_v21_a_to_d",
                "dltb_source": str(dltb),
                "phase1_quality_status": quality_gate["status"],
                "phase1_production_gate_passed": quality_gate["production_gate_passed"],
                "requires_dem": True,
                **handoff,
                "note": (
                    "Paper9 is executed by the phase 2 script or World Model v2.1 tab; "
                    "no algorithm output is created in phase 1."
                ),
            },
            "production_blockers": production_blockers,
        }
        execution_errors = [
            error
            for error in [projection_error, *semantic_query_errors]
            if error
        ]
        report["semantic_execution_errors"] = execution_errors
        if args.mode == "production":
            production_blockers.extend(f"semantic_execution:{error}" for error in execution_errors)
        output.parent.mkdir(parents=True, exist_ok=True)
        report["paper9_handoff"]["catalog_entry"] = _publish_paper9_handoff(
            lake,
            handoff,
            phase1_report=output,
            source=dltb,
            quality_status=quality_gate["status"],
            production_eligible=report["production_eligible"],
            plan_id=(materialization or {}).get("plan_id"),
        )
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "output": str(output),
                    "dataset_id": args.dataset_id,
                    "dataset_identity": dataset_identity["verification_status"],
                    "scan_status": scan["status"],
                    "deep_quality_status": deep_quality["status"],
                    "materialization_status": materialization["status"]
                    if materialization
                    else "not_attempted",
                    "binding_status": binding.get("status") if binding else "blocked",
                    "semantic_projection": bool(projection),
                    "semantic_execution_engine": args.semantic_execution_engine,
                    "semantic_query_count": len(queries),
                    "semantic_query_errors": semantic_query_errors,
                    "paper9_handoff_ready": handoff["governed_input_ready"],
                    "production_eligible": report["production_eligible"],
                    "production_blockers": production_blockers,
                },
                ensure_ascii=False,
            )
        )
        if execution_errors:
            return 1
        return 2 if args.mode == "production" and production_blockers else 0
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

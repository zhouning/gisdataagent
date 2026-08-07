#!/usr/bin/env python3
"""Run the DLTB-only vertical flow on an isolated Windows host.

Examples::

    python scripts/run_dltb_vertical_demo.py \
      --source D:\\NX_INCOMING\\DLTB.gdb --lake D:\\GDA_DATA\\file_lake \
      --output D:\\GDA_DATA\\reports\\dltb.json --mode production

For the local rehearsal, pass the Chongqing sample ZIP.  The report keeps the
sample boundary explicit and never marks it as Ningxia production evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from data_agent.dltb_vertical_demo import DLTBVerticalDemo
from data_agent.offline_ingest import OfflineIngestStore


def _safe_extract(archive_path: Path, destination: Path, max_bytes: int) -> int:
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
    candidates = sorted(root.rglob("*.gdb"))
    if not candidates:
        raise FileNotFoundError("no FileGDB found")
    for candidate in candidates:
        try:
            from data_agent.local_gis_runtime import inspect_vector

            if any(str(layer.get("name", "")).casefold() in {"dltb", "jqdltb", "地类图斑"} for layer in inspect_vector(candidate)):
                return candidate
        except Exception:
            pass
    return candidates[0]


def _find_dem(root: Path) -> Path | None:
    candidates = sorted(root.rglob("*.tif")) + sorted(root.rglob("*.tiff"))
    for candidate in candidates:
        if any(token in candidate.name.casefold() for token in ("dem", "elevation", "高程", "gdem")):
            return candidate
    return candidates[0] if candidates else None


def _paper9_readiness(dltb: Path, dem: Path | None) -> dict[str, Any]:
    return {
        "required_inputs": ["DLTB", "DEM"],
        "inputs": {
            "DLTB": {"present": dltb.exists(), "path": str(dltb)},
            "DEM": {"present": bool(dem and dem.exists()), "path": str(dem) if dem else None},
        },
        "ready_for_tool_1": dltb.exists() and bool(dem and dem.exists()),
        "production_ready": False,
        "blockers": [] if dem and dltb.exists() else ["DEM" if not dem else "DLTB"],
        "note": "DLTB-only supports governed query/visualisation; Paper9 Tool 1 additionally requires DEM."
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
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source", type=Path, help="DLTB.gdb or an extracted incoming directory")
    source_group.add_argument("--zip", type=Path, help="sample/incoming ZIP containing a DLTB.gdb")
    parser.add_argument("--dem", type=Path, help="optional DEM TIFF for Paper9 Tool 1 readiness")
    parser.add_argument("--lake", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("rehearsal", "production"), default="rehearsal")
    parser.add_argument("--paper9-repo", type=Path, help="local Paper9 checkout for Tool 1 preparation")
    parser.add_argument("--run-paper9-tool1", action="store_true", help="run Paper9 Tool 1 when DLTB and DEM are available")
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
            extraction = lake / "dltb_sample_extracted" if args.keep_extracted else Path(tempfile.mkdtemp(prefix="gda-dltb-"))
            extracted_bytes = _safe_extract(archive, extraction, max(1, int(args.max_uncompressed_gb * 1024**3)))
            if not args.keep_extracted:
                temporary = extraction
            root = extraction
        else:
            root = args.source.expanduser().resolve()
            if not root.exists():
                parser.error(f"source does not exist: {root}")
        dltb = root if root.name.casefold().endswith(".gdb") else _find_dltb(root)
        dem = args.dem.expanduser().resolve() if args.dem else _find_dem(root)
        if dem and not dem.exists():
            raise FileNotFoundError(str(dem))
        # A controlled inbox prevents unrelated sample layers from entering
        # this single-dataset demonstration.
        inbox = lake / "dltb_vertical_inbox"
        if inbox.exists():
            shutil.rmtree(inbox)
        inbox.mkdir(parents=True)
        staged_dltb = inbox / dltb.name
        shutil.copytree(dltb, staged_dltb)
        staged_dem = None
        if dem:
            staged_dem = inbox / dem.name
            shutil.copy2(dem, staged_dem)
        os.environ["GDA_LOCAL_INGEST_DIRS"] = str(inbox)
        store = OfflineIngestStore(lake)
        scan = store.scan_local_path(inbox, actor="dltb-vertical-demo")
        deep_quality = store.run_deep_quality(scan["run_id"], actor="dltb-vertical-demo")
        quality_gate = _quality_gate_summary(deep_quality)
        plan = None
        plan_error = None
        try:
            plan = store.create_standardization_plan(
                scan["run_id"],
                actor="dltb-vertical-demo",
                allow_review=args.mode == "rehearsal",
            )
        except ValueError as exc:
            plan_error = str(exc)
        materialization = None
        if plan:
            materialization = store.execute_standardization_plan(
                plan["run_id"], actor="dltb-vertical-demo", vector_format="Parquet"
            )
        binding = None
        binding_error = None
        if plan:
            try:
                binding = store.create_ontology_binding(plan["run_id"], actor="dltb-vertical-demo", ontology_version="2.3.0", binding_mode=args.mode)
            except ValueError as exc:
                binding_error = str(exc)
        elif plan_error:
            binding_error = f"not attempted: standardization plan blocked ({plan_error})"
        projection = None
        projection_error = None
        if plan:
            try:
                projection = DLTBVerticalDemo(store).build_projection(plan["run_id"], actor="dltb-vertical-demo", mode=args.mode)
            except (FileNotFoundError, ValueError, RuntimeError) as exc:
                projection_error = str(exc)
        elif plan_error:
            projection_error = f"not attempted: standardization plan blocked ({plan_error})"
        queries = []
        if projection:
            projection_path = projection["projection"]["projection_id"]
            projection_file = lake / "semantic_products" / projection_path / "semantic_projection.json"
            for question in ("各地类图斑数量和面积是多少？", "列出面积属性与几何面积差异较大的图斑"):
                queries.append(DLTBVerticalDemo.query(projection_file, question))
        paper9_tool1 = None
        paper9_error = None
        if args.run_paper9_tool1:
            if not args.paper9_repo:
                paper9_error = "--paper9-repo is required with --run-paper9-tool1"
            elif not staged_dem:
                paper9_error = "DEM is required for Paper9 Tool 1"
            else:
                try:
                    from data_agent.world_model_v21 import WorldModelV21Service

                    paper9_tool1 = WorldModelV21Service(args.paper9_repo.expanduser().resolve()).run_prepare(
                        {
                            "dltb_path": str(staged_dltb),
                            "dem_path": str(staged_dem),
                            "prepared_dir": str(lake / "paper9" / "prepared"),
                            "proj_crs": "EPSG:32648",
                            "run_phase_bc": False,
                        },
                        user_id="dltb-vertical-demo",
                    )
                except Exception as exc:
                    paper9_error = str(exc)
        sample_input = bool(archive or "规划院" in str(dltb) or "chongqing" in str(dltb).casefold() or "重庆" in str(dltb))
        production_blockers = []
        if args.mode == "production":
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
        report = {
            "schema": "gda.dltb-vertical-demo-report.v1",
            "sample_scope": "Chongqing rehearsal sample; not Ningxia authority data" if sample_input else "incoming source; authority determined by configured contract",
            "production_eligible": bool(args.mode == "production" and projection and projection["projection"].get("production_eligible") and binding and binding.get("ontology_binding", {}).get("production_eligible")),
            "source": str(archive or dltb),
            "extracted_bytes": extracted_bytes,
            "dltb_source": str(dltb),
            "dem_source": str(dem) if dem else None,
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
            "paper9_readiness": _paper9_readiness(dltb, dem),
            "paper9_tool1": paper9_tool1,
            "paper9_tool1_error": paper9_error,
            "production_blockers": production_blockers,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(output),
            "scan_status": scan["status"],
            "deep_quality_status": deep_quality["status"],
            "materialization_status": materialization["status"] if materialization else "not_attempted",
            "binding_status": binding.get("status") if binding else "blocked",
            "semantic_projection": bool(projection),
            "paper9_tool1_ready": report["paper9_readiness"]["ready_for_tool_1"],
            "production_eligible": report["production_eligible"],
            "production_blockers": production_blockers,
        }, ensure_ascii=False))
        return 2 if args.mode == "production" and production_blockers else 0
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the built-in GIS/Data Agent rehearsal with the Chongqing sample.

The archive is treated as an arriving batch from an isolated Windows site.
It remains explicitly Chongqing evidence; this script never promotes it to
Ningxia authority.  No ArcPy, ArcGIS Pro, MCP, container or network service is
needed for the data-lake stages.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from data_agent.offline_ingest import OfflineIngestStore
from data_agent.ontology.service import OntologyService


def _safe_extract(archive_path: Path, destination: Path, max_bytes: int) -> int:
    """Extract with Zip Slip and uncompressed-size protection."""

    import zipfile

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


def _find_paper9_inputs(root: Path) -> tuple[Path, Path]:
    dltb_candidates = sorted(root.glob("**/现状用地数据/*.gdb"))
    if not dltb_candidates:
        dltb_candidates = sorted(root.glob("**/*.gdb"))
    dem_candidates = sorted(root.glob("**/*DEM*/*.tif"))
    if not dem_candidates:
        dem_candidates = sorted(root.glob("**/*.tif"))
    if not dltb_candidates or not dem_candidates:
        raise FileNotFoundError("could not locate a DLTB FileGDB and DEM TIFF in the sample")
    return dltb_candidates[0], dem_candidates[0]


def _ontology_evidence() -> dict[str, Any]:
    os.environ["ONTOLOGY_RUNTIME_BACKEND"] = "package"
    service = OntologyService()
    evidence: dict[str, Any] = {"status": service.status()}
    for term in ("地类图斑", "数字高程模型", "生态保护红线", "土地地块"):
        found = service.search_concepts(query=term, limit=5)
        rows = []
        for concept in found.get("items", [])[:5]:
            concept_id = concept.get("concept_id")
            rows.append(
                {
                    "concept": service.get_concept(concept_id),
                    "properties": service.get_properties(
                        concept_id, limit=100, include_effective=True
                    ),
                    "relations": service.get_relations(concept_id, limit=100),
                }
            )
        evidence[term] = rows
    return evidence


def _paper9_rehearsal(
    repo: Path,
    extracted: Path,
    lake: Path,
    *,
    run_all: bool,
    phase_bc: bool,
) -> dict[str, Any]:
    from data_agent.world_model_v21 import WorldModelV21Service

    dltb, dem = _find_paper9_inputs(extracted)
    service = WorldModelV21Service(repo_path=repo)
    prepared = lake / "paper9" / "prepared"
    result: dict[str, Any] = {
        "inputs": {"dltb": str(dltb), "dem": str(dem)},
        "status": service.status(),
    }
    result["prepare"] = service.run_prepare(
        {
            "dltb_path": str(dltb),
            "dem_path": str(dem),
            "prepared_dir": str(prepared),
            "proj_crs": "EPSG:32648",
            "run_phase_bc": phase_bc,
        },
        user_id="chongqing_rehearsal",
    )
    if not run_all:
        return result
    result["sample"] = service.run_sample(
        {
            "prepared_dir": str(prepared),
            "n_transition_episodes": 60,
            "n_pairwise_states": 1000,
            "n_pairwise_actions": 50,
            "seed": 0,
            "proj_crs": "EPSG:32648",
        },
        user_id="chongqing_rehearsal",
    )
    # A one-member, two-epoch run is a deterministic offline smoke test. A
    # production deployment must use the approved Paper9 training parameters.
    result["train_smoke"] = service.run_train(
        {
            "prepared_dir": str(prepared),
            "n_members": 1,
            "epochs": 2,
            "patience": 1,
            "torch_threads": 2,
            "out_subdir": "tool3_smoke",
        },
        user_id="chongqing_rehearsal",
    )
    try:
        result["plan_attempt"] = service.run_plan(
            {
                "prepared_dir": str(prepared),
                "ensemble_dir": str(prepared / "tool3_smoke"),
                "out_dir": str(prepared / "tool4_smoke"),
                "county": "chongqing_rehearsal",
                "goal": "offline rehearsal only",
            },
            user_id="chongqing_rehearsal",
        )
    except Exception as exc:
        result["plan_attempt"] = {"status": "blocked", "reason": str(exc)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--lake", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--paper9-repo", type=Path)
    parser.add_argument("--paper9-all", action="store_true")
    parser.add_argument("--paper9-phase-bc", action="store_true")
    parser.add_argument("--keep-extracted", action="store_true")
    parser.add_argument("--max-uncompressed-gb", type=float, default=20.0)
    args = parser.parse_args()

    archive = args.zip.expanduser().resolve()
    lake = args.lake.expanduser().resolve()
    if not archive.is_file():
        parser.error(f"sample ZIP does not exist: {archive}")
    extraction = lake / "sample_extracted"
    temporary = False
    if not args.keep_extracted:
        extraction = Path(tempfile.mkdtemp(prefix="gda-chongqing-flow-"))
        temporary = True
    try:
        extracted_bytes = _safe_extract(
            archive,
            extraction,
            max_bytes=max(1, int(args.max_uncompressed_gb * 1024**3)),
        )
        os.environ["GDA_LOCAL_INGEST_DIRS"] = str(extraction)
        store = OfflineIngestStore(lake)
        scan = store.scan_local_path(extraction, actor="chongqing-rehearsal")
        deep_quality = store.run_deep_quality(scan["run_id"], actor="chongqing-rehearsal")
        plan = store.create_standardization_plan(
            scan["run_id"], actor="chongqing-rehearsal", allow_review=True
        )
        materialization = store.execute_standardization_plan(
            plan["run_id"], actor="chongqing-rehearsal", vector_format="Parquet"
        )
        binding = store.create_ontology_binding(
            plan["run_id"], actor="chongqing-rehearsal", binding_mode="rehearsal"
        )
        report: dict[str, Any] = {
            "sample_scope": "Chongqing demo package; not Ningxia authority data",
            "production_eligible": False,
            "archive": str(archive),
            "extracted_bytes": extracted_bytes,
            "extraction_root": str(extraction),
            "scan": scan,
            "deep_quality": deep_quality,
            "standardization_plan": plan,
            "materialization": materialization,
            "ontology_binding": binding,
            "ontology_evidence": _ontology_evidence(),
        }
        if args.paper9_repo:
            report["paper9"] = _paper9_rehearsal(
                args.paper9_repo.expanduser().resolve(),
                extraction,
                lake,
                run_all=args.paper9_all,
                phase_bc=args.paper9_phase_bc,
            )
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "output": str(output),
            "scan_run_id": scan["run_id"],
            "quality_status": deep_quality["status"],
            "assets": scan.get("asset_count", 0),
            "materialization_status": materialization["status"],
            "ontology_status": binding["status"],
            "production_eligible": False,
        }, ensure_ascii=False))
        return 0
    finally:
        if temporary:
            shutil.rmtree(extraction, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Assess whether bounded Stage 13 metadata contains usable validation data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPO_ROOT / ".tmp/geotransport/stage13_confluence_evidence"
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage13_confluence_evidence_assessment.json"
)
SCHEMA = "gwm.geotransport.stage13_confluence_evidence_assessment.v1"

FROZEN_ARTIFACTS = {
    "crossref_open_channel_junction_catalog.json": (
        2330,
        "fb4c8b7fdc540d4e2b1f9b1dda20c684b2bf278e5a72392043452a5a1c234734",
    ),
    "openalex_shumate_junction_thesis.json": (
        6920,
        "e5c780d0ae54f7678f2dfe9c8d709de926ee8523f94d0b4b87d6d675a5f6ce05",
    ),
    "zenodo_confluence_angle_record.json": (
        7403,
        "85cc02086037425f8cc71ac1a032743ec80be8100eef1b627779aaefeafc00ff",
    ),
    "github_confluence_data_repository_search.json": (
        55,
        "4af480b8ee5b87b369a76c49bd22c9a783908272ebffbe97898f8ab0f0772a5f",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=EVIDENCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = assess(Path(args.evidence_root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def assess(evidence_root: Path = EVIDENCE_ROOT) -> dict[str, Any]:
    root = Path(evidence_root)
    artifacts = {
        name: _artifact(root / name, expected_size, expected_hash)
        for name, (expected_size, expected_hash) in FROZEN_ARTIFACTS.items()
    }
    manifest = _read_json(root / "acquisition_manifest.json")
    crossref = _read_json(root / "crossref_open_channel_junction_catalog.json")
    openalex = _read_json(root / "openalex_shumate_junction_thesis.json")
    zenodo = _read_json(root / "zenodo_confluence_angle_record.json")
    github = _read_json(
        root / "github_confluence_data_repository_search.json"
    )

    thesis = {
        "title": openalex["title"],
        "doi": openalex["doi"],
        "open_access": openalex["open_access"],
        "has_fulltext": openalex["has_fulltext"],
        "pdf_urls": [
            location["pdf_url"]
            for location in openalex["locations"]
            if location.get("pdf_url")
        ],
        "assessment": (
            "not_usable: public metadata identifies a relevant experimental "
            "thesis but provides neither an open full text nor a PDF URL; no "
            "machine-readable geometry, discharge, stage, or velocity data "
            "is available from this source snapshot"
        ),
    }
    zenodo_files = zenodo["files"]
    zenodo_file_names = [value["key"] for value in zenodo_files]
    zenodo_is_numeric_dataset = any(
        Path(value).suffix.lower() in {".csv", ".json", ".nc", ".parquet"}
        for value in zenodo_file_names
    )
    publication = {
        "record_id": zenodo["id"],
        "title": zenodo["metadata"]["title"],
        "resource_type": zenodo["metadata"]["resource_type"],
        "license": zenodo["metadata"]["license"],
        "files": [
            {
                "key": value["key"],
                "size_bytes": value["size"],
                "checksum": value["checksum"],
            }
            for value in zenodo_files
        ],
        "machine_readable_numeric_dataset": zenodo_is_numeric_dataset,
        "assessment": (
            "not_usable: a CC-BY article PDF is a useful scientific context "
            "source, but its record exposes no raw numeric measurement file; "
            "the article was not treated as a validation data table"
        ),
    }
    catalog_dois = [
        value.get("DOI")
        for value in crossref["message"]["items"]
        if value.get("DOI")
    ]
    repository_search = {
        "query_total_count": github["total_count"],
        "returned_repository_count": len(github["items"]),
        "assessment": (
            "no exact public repository match in this query snapshot; this is "
            "a bounded discovery result, not a claim that no such repository "
            "exists"
        ),
    }
    artifact_identity = all(value["identity_matches"] for value in artifacts.values())
    boundary_valid = (
        manifest.get("schema")
        == "gwm.geotransport.stage13_confluence_evidence_acquisition.v1"
        and manifest.get("artifact_count") == 4
        and manifest.get("total_downloaded_bytes") == 16_708
        and manifest.get("request_boundary", {}).get(
            "workspace_or_private_data_sent"
        )
        is False
    )
    gates = {
        "public_snapshot_identities_frozen": artifact_identity,
        "acquisition_boundary_respected": boundary_valid,
        "literature_catalog_identifies_known_experimental_lineage": (
            "10.1061/(asce)0733-9429(2001)127:5(340)" in catalog_dois
        ),
        "relevant_thesis_not_misrepresented_as_open_data": (
            thesis["open_access"]["is_oa"] is False
            and thesis["has_fulltext"] is False
            and not thesis["pdf_urls"]
        ),
        "publication_not_misrepresented_as_numeric_dataset": (
            publication["resource_type"]["type"] == "publication"
            and publication["machine_readable_numeric_dataset"] is False
        ),
        "repository_search_not_misrepresented_as_negative_proof": (
            repository_search["query_total_count"] == 0
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "no_independent_open_machine_readable_confluence_validation_"
            "dataset_identified_in_bounded_search"
        ),
        "evidence_scope": {
            "sources": ["Crossref", "OpenAlex", "Zenodo", "GitHub"],
            "search_is_exhaustive": False,
            "workspace_or_private_data_sent": False,
            "public_metadata_used_to_define_native_law": False,
        },
        "artifacts": artifacts,
        "literature_catalog": {
            "item_count": len(catalog_dois),
            "dois": catalog_dois,
        },
        "relevant_experimental_thesis": thesis,
        "open_confluence_angle_publication": publication,
        "github_repository_search": repository_search,
        "admission_requirements": {
            "all_required": [
                "publicly accessible machine-readable values",
                "terminal or cross-section geometry",
                "branch flow or velocity state",
                "stage or water-surface observation",
                "reusable terms or permission",
            ],
            "admitted_dataset": None,
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "public_confluence_validation_completed": False,
            "reaction_independently_observed": False,
            "literature_metadata_treated_as_observation": False,
            "article_pdf_treated_as_raw_dataset": False,
            "search_result_is_global_negative_proof": False,
            "candidate_operator_admitted": False,
        },
    }


def _artifact(path: Path, expected_size: int, expected_hash: str) -> dict[str, object]:
    body = path.read_bytes()
    actual_hash = hashlib.sha256(body).hexdigest()
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(body),
        "sha256": actual_hash,
        "expected_size_bytes": expected_size,
        "expected_sha256": expected_hash,
        "identity_matches": (
            len(body) == expected_size and actual_hash == expected_hash
        ),
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())

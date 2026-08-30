#!/usr/bin/env python3
"""Rebuild the curated layer over a verified immutable ontology package."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from data_agent.ontology.compiler import CompiledOntology, write_package
from data_agent.ontology.contracts import (
    ConceptRecord,
    MappingRecord,
    PropertyRecord,
    RelationRecord,
    SourceRecord,
)
from data_agent.ontology.domain_model import (
    CURATED_MODEL_VERSION,
    compile_curated_domain_ontology,
)
from data_agent.ontology.package_reader import OntologyPackageReader

RecordT = TypeVar("RecordT", bound=BaseModel)


def _records(path: Path, model_type: type[RecordT]) -> list[RecordT]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [model_type.model_validate_json(line) for line in stream if line.strip()]


def build(source_package: Path, output_root: Path, version: str) -> dict[str, object]:
    reader = OntologyPackageReader(source_package, verify=True)
    source = reader.package_dir
    validation = json.loads((source / "validation-report.json").read_text(encoding="utf-8"))
    flat = CompiledOntology(
        sources=_records(source / "sources.jsonl.gz", SourceRecord),
        concepts=_records(source / "concepts.jsonl.gz", ConceptRecord),
        properties=_records(source / "properties.jsonl.gz", PropertyRecord),
        relations=_records(source / "relations.jsonl.gz", RelationRecord),
        mappings=_records(source / "mappings.jsonl.gz", MappingRecord),
        issues=list(validation.get("issues") or []),
    )
    compiled = compile_curated_domain_ontology(flat)
    manifest = write_package(compiled, output_root / version, semantic_version=version)
    return {
        "source_package": reader.manifest.package_id,
        "package_dir": str((output_root / version).resolve()),
        "package_id": manifest.package_id,
        "semantic_version": manifest.semantic_version,
        "content_sha256": manifest.content_sha256,
        "stats": manifest.stats,
        "validation": manifest.validation_summary,
        "active_pointer_updated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-package",
        type=Path,
        default=Path("data_agent/ontology/packages/natural_resource_one_map/2.1.0"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data_agent/ontology/packages/natural_resource_one_map"),
    )
    parser.add_argument("--version", default=CURATED_MODEL_VERSION)
    args = parser.parse_args()
    print(json.dumps(build(args.source_package, args.output_root, args.version), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Expand the 0804 attachment seeds through EA and standard evidence.

The attachment is a minimum acceptance catalog, not the ontology source of
truth. This audit resolves each listed source layer to immutable EA/standard
schema artifacts, expands every field owned by those artifacts, and reports
whether the field has a curated domain-semantic disposition.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from data_agent.ontology.compiler import CompiledOntology
from data_agent.ontology.contracts import (
    ConceptRecord,
    MappingRecord,
    PropertyRecord,
    RelationRecord,
    SourceRecord,
)
from data_agent.ontology.domain_model import (
    CURATED_SOURCE_ID,
    _schema_binding_targets,
    compile_curated_domain_ontology,
)

DEFAULT_COVERAGE = Path("docs/analysis/natural-resource-ontology-attachment-coverage-0804.json")
DEFAULT_PACKAGE = Path("data_agent/ontology/packages/natural_resource_one_map/2.2.0")
DEFAULT_OUTPUT = Path("docs/analysis/natural-resource-ontology-evidence-expansion-0804")

CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")

# The attachment uses GYSS, while the standard feature code is GYSSA.
CODE_ALIASES: dict[str, tuple[str, ...]] = {
    "GYSS": ("GYSSA",),
    "ZXCQCSSX": (
        "CZKFBJFWCSLX",
        "CZKFBJFWCSLVX",
        "CZKFBJFWCSHX",
        "CZKFBJFWCSZX",
    ),
}

LAYER_TARGET_CLASSES: dict[str, str] = {
    "PLAPT": "Courtyard",
    "HYDA": "SurfaceWaterBody",
    "HYDL": "SurfaceWaterBody",
    "ZXCQCSSX": "UrbanFourLine",
    "ZXCQGHFQ": "PlanningZone",
    "ZXCQGHYDYH": "PlannedLandUseArea",
    "JTFWCZA": "TransportStation",
    "JTYSYDA": "TransportStation",
    "TYHDA": "SportsFacility",
    "GYYLDA": "GreenOpenSpace",
    "GYSS": "UtilityFacility",
    "GYSSA": "UtilityFacility",
    "YLJGA": "MedicalFacility",
    "GSHYQZDDBZS": "CadastralParcel",
    "DLTB": "LandParcel",
    "CQNFWJZA": "Building",
    "FWJZ": "Building",
    "XXA": "EducationalFacility",
    "YJBNA": "EmergencyShelter",
    "WHHDA": "CulturalFacility",
    "WYCGA": "CulturalFacility",
    "BZSSA": "Cemetery",
    "SQCPG": "Community",
    "FLJGA": "WelfareFacility",
    "ZRZ": "Building",
    "GHDKPG": "Courtyard",
}

ENTITY_TARGET_CLASSES: dict[str, str] = {
    "H_RIV_A": "RiverSegment",
    "H_CAN_A": "Canal",
    "H_LAK_A": "SurfaceWaterBody",
    "H_RES_A": "Reservoir",
    "R_BLD_A": "Building",
    "R_GRO_A": "SportsFacility",
    "Y_TSP_A": "TransportStation",
    "Y_SPE_A": "Cemetery",
    "Y_LIV_A": "ResidentialCompound",
}

RecordT = TypeVar("RecordT", bound=BaseModel)


def _normalized(value: Any) -> str:
    return "".join(
        character for character in str(value or "").casefold().strip() if character.isalnum()
    )


def _load_records(path: Path, model_type: type[RecordT]) -> list[RecordT]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [model_type.model_validate_json(line) for line in stream if line.strip()]


def _compile_package(package: Path) -> CompiledOntology:
    validation = json.loads((package / "validation-report.json").read_text(encoding="utf-8"))
    flat = CompiledOntology(
        sources=_load_records(package / "sources.jsonl.gz", SourceRecord),
        concepts=_load_records(package / "concepts.jsonl.gz", ConceptRecord),
        properties=_load_records(package / "properties.jsonl.gz", PropertyRecord),
        relations=_load_records(package / "relations.jsonl.gz", RelationRecord),
        mappings=_load_records(package / "mappings.jsonl.gz", MappingRecord),
        issues=list(validation.get("issues") or []),
    )
    return compile_curated_domain_ontology(flat)


def _layer_seeds(coverage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in coverage:
        key = (str(row.get("source_layer") or ""), str(row.get("source_layer_code") or ""))
        item = grouped.setdefault(
            key,
            {
                "source_layer": key[0],
                "source_layer_code": key[1],
                "source_data": set(),
                "entity_codes": set(),
                "entity_labels": set(),
                "attachment_field_count": 0,
            },
        )
        item["source_data"].add(str(row.get("source_data") or ""))
        item["entity_codes"].add(str(row.get("entity_code") or ""))
        item["entity_labels"].add(str(row.get("entity_label") or ""))
        item["attachment_field_count"] += 1

    seeds: list[dict[str, Any]] = []
    for item in grouped.values():
        raw_codes = set()
        for value in (item["source_layer"], item["source_layer_code"]):
            raw_codes.update(token.upper() for token in CODE_RE.findall(value))
        codes = set(raw_codes)
        for code in raw_codes:
            codes.update(CODE_ALIASES.get(code, ()))
        target_class = next(
            (LAYER_TARGET_CLASSES[code] for code in sorted(codes) if code in LAYER_TARGET_CLASSES),
            next(
                (
                    ENTITY_TARGET_CLASSES[code]
                    for value in item["entity_codes"]
                    for code in CODE_RE.findall(value.upper())
                    if code in ENTITY_TARGET_CLASSES
                ),
                "NaturalResourceEntity",
            ),
        )
        seeds.append(
            {
                **item,
                "source_data": sorted(value for value in item["source_data"] if value),
                "entity_codes": sorted(value for value in item["entity_codes"] if value),
                "entity_labels": sorted(value for value in item["entity_labels"] if value),
                "lookup_codes": sorted(codes),
                "target_class": target_class,
            }
        )
    return sorted(seeds, key=lambda row: (row["source_layer_code"], row["source_layer"]))


def _schema_candidates(
    seed: dict[str, Any],
    concepts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    code_set = set(seed["lookup_codes"])
    label_set = {
        _normalized(seed["source_layer"]),
        *(_normalized(label) for label in seed["entity_labels"]),
    }
    exact_code = [
        row
        for row in concepts
        if row.get("kind") == "SchemaArtifact" and str(row.get("code") or "").upper() in code_set
    ]
    if exact_code:
        return sorted(
            exact_code,
            key=lambda row: (
                0 if str(row.get("source_id") or "").startswith("std-doc-") else 1,
                str(row.get("source_id") or ""),
                str(row.get("concept_id") or ""),
            ),
        )
    if "GSHYQZDDBZS" in code_set:
        return sorted(
            (
                row
                for row in concepts
                if row.get("kind") == "SchemaArtifact"
                and row.get("source_id") == "ea-repository"
                and "030202国有建设用地使用权" in str(row.get("package_path") or "")
                and str(row.get("pref_label") or "") in {"宗地", "JSYDSYQ表"}
            ),
            key=lambda row: str(row.get("concept_id") or ""),
        )

    def comparable_label(value: Any) -> str:
        normalized = _normalized(value)
        for suffix in ("属性结构描述表", "属性结构", "面层", "点层", "线层", "层"):
            normalized = normalized.removesuffix(_normalized(suffix))
        return normalized

    comparable_labels = {comparable_label(value) for value in label_set if value}
    return sorted(
        (
            row
            for row in concepts
            if row.get("kind") == "SchemaArtifact"
            and comparable_label(row.get("pref_label")) in comparable_labels
            and comparable_label(row.get("pref_label"))
        ),
        key=lambda row: (
            0 if str(row.get("source_id") or "").startswith("std-doc-") else 1,
            str(row.get("source_id") or ""),
            str(row.get("concept_id") or ""),
        ),
    )


def analyze(coverage_path: Path, package: Path) -> dict[str, Any]:
    coverage_payload = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage = list(coverage_payload["coverage"])
    compiled = _compile_package(package)
    concepts = [record.model_dump(mode="json") for record in compiled.concepts]
    properties = [
        record.model_dump(mode="json")
        for record in compiled.properties
        if record.source_id != CURATED_SOURCE_ID
    ]
    fields_by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for field in properties:
        fields_by_owner[str(field["owner_concept_id"])].append(field)

    schema_targets = _schema_binding_targets(compiled.concepts)
    layers: list[dict[str, Any]] = []
    expanded_fields: list[dict[str, Any]] = []
    for layer_number, seed in enumerate(_layer_seeds(coverage), start=1):
        candidates = _schema_candidates(seed, concepts)
        selected = candidates
        schema_ids = {str(row["concept_id"]) for row in selected}
        bound_target_classes = tuple(
            dict.fromkeys(
                target_class
                for schema_id in schema_ids
                for target_class in schema_targets.get(schema_id, ())
            )
        )
        raw_fields = [field for owner in schema_ids for field in fields_by_owner.get(owner, ())]
        unique_fields: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for field in raw_fields:
            signature = (
                str(field.get("source_id") or ""),
                str(field.get("owner_concept_id") or ""),
                _normalized(field.get("code")),
                _normalized(field.get("pref_label")),
            )
            unique_fields.setdefault(signature, field)

        layer_status = "matched" if selected else "no_ea_or_standard_schema_match"
        layers.append(
            {
                "layer_number": layer_number,
                **seed,
                "status": layer_status,
                "schema_candidate_count": len(candidates),
                "expanded_field_count": len(unique_fields),
                "bound_target_classes": list(bound_target_classes),
                "schema_candidates": [
                    {
                        "concept_id": row["concept_id"],
                        "source_id": row["source_id"],
                        "code": row.get("code"),
                        "label": row.get("pref_label"),
                        "package_path": row.get("package_path"),
                    }
                    for row in selected
                ],
            }
        )
        schema_by_id = {str(row["concept_id"]): row for row in selected}
        for field in sorted(
            unique_fields.values(),
            key=lambda row: (
                str(row.get("source_id") or ""),
                str(row.get("owner_concept_id") or ""),
                int(row.get("ordinal") or 0),
                str(row.get("property_id") or ""),
            ),
        ):
            semantic = dict(field.get("provenance") or {})
            status = str(semantic.get("semantic_disposition") or "unresolved_domain_field")
            target_property = str(semantic.get("semantic_target_property_id") or "").removeprefix(
                "gda:nr:property:"
            )
            target_relation = str(semantic.get("semantic_target_relation") or "")
            schema = schema_by_id[str(field["owner_concept_id"])]
            expanded_fields.append(
                {
                    "layer_number": layer_number,
                    "attachment_layer": seed["source_layer"],
                    "attachment_layer_code": seed["source_layer_code"],
                    "target_class": seed["target_class"],
                    "schema_concept_id": schema["concept_id"],
                    "schema_source_id": schema["source_id"],
                    "schema_code": schema.get("code"),
                    "schema_label": schema.get("pref_label"),
                    "source_property_id": field["property_id"],
                    "field_code": field.get("code"),
                    "field_label": field.get("pref_label"),
                    "datatype": field.get("datatype"),
                    "required": int(field.get("min_count") or 0) > 0,
                    "value_domain": field.get("value_domain"),
                    "semantic_status": status,
                    "target_property": target_property,
                    "target_relation": target_relation,
                    "target_class_ids": semantic.get(
                        "semantic_target_class_ids",
                        [semantic["semantic_target_class_id"]]
                        if semantic.get("semantic_target_class_id")
                        else [],
                    ),
                    "semantic_mapping_basis": semantic.get(
                        "semantic_mapping_basis",
                        "",
                    ),
                    "semantic_exclusion_reason": semantic.get(
                        "semantic_exclusion_reason",
                        "",
                    ),
                }
            )

    return {
        "summary": {
            "attachment_row_count": len(coverage),
            "attachment_layer_count": len(layers),
            "matched_layer_count": sum(row["status"] == "matched" for row in layers),
            "unmatched_layer_count": sum(row["status"] != "matched" for row in layers),
            "expanded_field_count": len(expanded_fields),
            "semantic_status_counts": dict(
                sorted(Counter(row["semantic_status"] for row in expanded_fields).items())
            ),
            "unresolved_or_ambiguous_field_count": sum(
                row["semantic_status"]
                in {
                    "unresolved_domain_field",
                    "ambiguous_property_mapping",
                }
                for row in expanded_fields
            ),
            "method": (
                "attachment seed -> exact code/curated alias -> "
                "EA and standard schema -> all owned fields"
            ),
            "source_package": str(package),
        },
        "layers": layers,
        "expanded_fields": expanded_fields,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )


def write_outputs(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_csv(output.with_suffix(".layers.csv"), payload["layers"])
    _write_csv(output.with_suffix(".fields.csv"), payload["expanded_fields"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = analyze(args.coverage, args.package)
    write_outputs(payload, args.output)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

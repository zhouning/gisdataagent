#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm import traditional_livability_s6_fulu_adapter as s6_adapter
from data_agent.uwm.geospatial_kernel.transition_matrix import build_transition_matrix
from data_agent.uwm.livability_s2.fulu_adapter import build_fulu_s2_inputs
from data_agent.uwm.livability_s2.product import build_s2_product_payloads
from data_agent.uwm.livability_s2.state_builder import build_fulu_s2_state_graph


def build_s2_fulu(
    *,
    source_root: Path,
    facility_product: Mapping[str, Any] | None,
    output_dir: Path,
    kernel_version: str,
    land_use_dictionary: Mapping[str, Any] | None = None,
    transition_matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build atomic, versioned S2 snapshots from real Fulu vector inputs."""

    if facility_product is None:
        return {"ready": False, "exit_code": 2, "blockers": ["facility_product_missing"]}
    inputs = build_fulu_s2_inputs(
        source_root=Path(source_root), facility_product=facility_product
    )
    if not inputs.get("ready"):
        return {
            "ready": False,
            "exit_code": 2,
            "blockers": list(inputs.get("blockers") or ["fulu_s2_inputs_not_ready"]),
        }
    graph_product = build_fulu_s2_state_graph(inputs, kernel_version=kernel_version)
    if not graph_product.get("ready"):
        return {
            "ready": False,
            "exit_code": 2,
            "blockers": list(graph_product.get("blockers") or ["state_graph_not_ready"]),
        }
    dictionary = dict(land_use_dictionary or _default_dictionary(inputs))
    matrix = dict(
        transition_matrix
        or build_transition_matrix(
            version="fulu-s2-transition-matrix-v1",
            dictionary_version=str(dictionary["version"]),
            rules=[],
        )
    )
    payloads = build_s2_product_payloads(
        inputs=inputs,
        graph_product=graph_product,
        land_use_dictionary=dictionary,
        transition_matrix=matrix,
    )
    try:
        _write_atomic(Path(output_dir), payloads)
    except (OSError, TypeError, ValueError):
        return {"ready": False, "exit_code": 2, "blockers": ["snapshot_write_failed"]}
    return {
        "ready": True,
        "exit_code": 0,
        "blockers": [],
        "output_dir": str(output_dir),
        "state_graph_snapshot_digest": graph_product["state_graph"]["snapshot_digest"],
    }


def _default_dictionary(inputs: Mapping[str, Any]) -> dict[str, Any]:
    classes = sorted(
        {
            str(value)
            for row in inputs.get("parcels") or []
            for value in [row.get("current_land_use_class"), row.get("planned_land_use_class")]
            if value not in {None, "", "unavailable"}
        }
        | {
            str(row.get("resource_domain"))
            for row in inputs.get("planning_resources") or []
            if row.get("resource_domain") not in {None, ""}
        }
    )
    return {
        "schema": "uwm.land_use_dictionary.v1",
        "version": "fulu-s2-land-use-dictionary-v1",
        "classes": classes,
        "authority_status": "controlled_source_semantics_not_complete_approval_dictionary",
        "approval_claim": False,
    }


def _write_atomic(output_dir: Path, payloads: Mapping[str, Mapping[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_paths: list[Path] = []
    try:
        for filename, payload in payloads.items():
            temporary = output_dir / f"{filename}.tmp"
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            temporary_paths.append(temporary)
        for temporary in temporary_paths:
            os.replace(temporary, output_dir / temporary.name.removesuffix(".tmp"))
    finally:
        for temporary in temporary_paths:
            if temporary.exists():
                temporary.unlink()


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("json_payload_must_be_object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--facility-product", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--kernel-version", default="0.1.0")
    args = parser.parse_args()
    result = build_s2_fulu(
        source_root=args.source_root,
        facility_product=_load_json(args.facility_product),
        output_dir=args.output_dir,
        kernel_version=args.kernel_version,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())

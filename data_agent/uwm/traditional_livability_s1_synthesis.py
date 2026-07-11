from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


SCHEMA = "uwm.traditional_livability.s1_synthesis.v1"


def synthesize_s1_dimensions(
    *, fp: Mapping[str, Any], fpp: Mapping[str, Any], matrix: Mapping[str, Any]
) -> dict[str, Any]:
    fp_copy = deepcopy(dict(fp))
    fpp_copy = deepcopy(dict(fpp))
    matrix_copy = deepcopy(dict(matrix))
    blockers = []
    if fp_copy.get("status") == "unresolved":
        blockers.append("dimension_unresolved:FP")
    if fpp_copy.get("status") == "unresolved":
        blockers.append("dimension_unresolved:FPP")
    if matrix_copy.get("status") != "valid":
        blockers.append("authoritative_synthesis_matrix_missing")
    if blockers:
        return {
            "schema": SCHEMA,
            "status": "unresolved",
            "matrix_id": matrix_copy.get("matrix_id"),
            "fp_status": fp_copy.get("status"),
            "fpp_status": fpp_copy.get("status"),
            "blockers": blockers,
            "max_claim_level": "unresolved",
        }
    pair = (fp_copy.get("status"), fpp_copy.get("status"))
    outcome = next(
        (
            row
            for row in matrix_copy.get("outcomes", [])
            if isinstance(row, Mapping)
            and (row.get("fp_status"), row.get("fpp_status")) == pair
        ),
        None,
    )
    if outcome is None:
        return {
            "schema": SCHEMA,
            "status": "unresolved",
            "matrix_id": matrix_copy.get("matrix_id"),
            "fp_status": pair[0],
            "fpp_status": pair[1],
            "blockers": ["synthesis_matrix_pair_missing"],
            "max_claim_level": "unresolved",
        }
    return {
        "schema": SCHEMA,
        "status": outcome.get("combined_status"),
        "matrix_id": matrix_copy.get("matrix_id"),
        "matrix_content_digest": matrix_copy.get("content_digest"),
        "fp_status": pair[0],
        "fpp_status": pair[1],
        "blockers": [],
        "max_claim_level": "authoritative_static_assessment",
    }

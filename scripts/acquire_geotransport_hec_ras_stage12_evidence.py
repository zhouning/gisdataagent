#!/usr/bin/env python3
"""Acquire hash-locked USACE force-semantics and junction-search evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / ".tmp/geotransport/hec_ras_stage12"
SCHEMA = "gwm.geotransport.hec_ras_stage12_acquisition.v1"
USER_AGENT = "gisdataagent-hec-ras-force-diagnostic/0.1"
MAXIMUM_TOTAL_BYTES = 320_000
USACE_API_ROOT = "https://www.hec.usace.army.mil/confluence/rest/api/content"
JUNCTION_SEARCH_CQL = (
    'type=page AND (title~"junction" OR text~"momentum based junction")'
)


REQUESTS = (
    {
        "source_id": "usace_momentum_based_junction_method",
        "url": f"{USACE_API_ROOT}/43816560?expand=body.storage,version,space",
        "output_name": "momentum_based_junction_method.json",
        "expected_size_bytes": 11_533,
        "expected_sha256": (
            "c1c8e383101863cf1d88c7eaeebad87ee2dccc0ca8440cfaaf3620ca8a89d7dd"
        ),
        "role": "authoritative_force_equation_documentation",
    },
    {
        "source_id": "usace_mixed_flow_specific_force",
        "url": f"{USACE_API_ROOT}/43816541?expand=body.storage,version,space",
        "output_name": "mixed_flow_specific_force.json",
        "expected_size_bytes": 11_446,
        "expected_sha256": (
            "fd505acdd8bfd404fa76c227e4e307729106b1920c2e8c46bbf2fc5b826dd539"
        ),
        "role": "authoritative_specific_force_documentation",
    },
    {
        "source_id": "usace_public_junction_search_snapshot",
        "url": (
            f"{USACE_API_ROOT}/search?"
            + urllib.parse.urlencode(
                {
                    "cql": JUNCTION_SEARCH_CQL,
                    "limit": 100,
                    "expand": "version,space",
                }
            )
        ),
        "output_name": "junction_search_snapshot.json",
        "expected_size_bytes": 156_673,
        "expected_canonical_sha256": (
            "255615d8257d9f721c1a501ce97c5578b7e359c48b535d767beafad139ea4326"
        ),
        "canonicalization": "remove_dynamic_searchDuration_then_sorted_compact_json",
        "role": "official_catalog_discovery_snapshot_not_hydraulic_truth",
    },
    {
        "source_id": "rivernetwork_fixed_commit_junction_source",
        "url": (
            "https://raw.githubusercontent.com/babakpst/RiverNetwork/"
            "f0f5f07ceecd416cf6a1fbe629d3e1050d6d2a74/src/Simulator/"
            "solve_network_mod.f90"
        ),
        "output_name": "rivernetwork_solve_network_mod.f90",
        "expected_size_bytes": 100_473,
        "expected_sha256": (
            "ea4846d397e5b3f2f7bfac7a486f904c671eda3c98338fc636336ee820f74148"
        ),
        "role": (
            "transparent_open_source_candidate_audit_not_reference_truth; "
            "momentum_junction_branch_is_explicitly_unimplemented"
        ),
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def compile_plan(*, values_mode: bool = False) -> dict[str, Any]:
    planned_bytes = sum(int(value["expected_size_bytes"]) for value in REQUESTS)
    if planned_bytes > MAXIMUM_TOTAL_BYTES:
        raise ValueError("hec_ras_stage12_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "purpose": (
            "audit documented specific-force semantics, force-equation ambiguity, "
            "and the availability of a second official combining-junction case"
        ),
        "request_boundary": {
            "allowed_hosts": [
                "raw.githubusercontent.com",
                "www.hec.usace.army.mil",
            ],
            "object_count": len(REQUESTS),
            "maximum_total_bytes": MAXIMUM_TOTAL_BYTES,
            "planned_exact_bytes": planned_bytes,
            "workspace_or_private_data_sent": False,
        },
        "requests": [dict(value) for value in REQUESTS],
        "claim_boundary": {
            "source_values_acquired": values_mode,
            "catalog_search_is_negative_proof": False,
            "equation_variant_selected": False,
            "calibration_authorized": False,
            "operator_admitted": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("hec_ras_stage12_positive_request_limits_required")
    output = args.output.resolve()
    ignored_root = (REPO_ROOT / ".tmp").resolve()
    if ignored_root not in output.parents:
        raise ValueError("hec_ras_stage12_output_must_be_under_ignored_tmp")
    output.mkdir(parents=True, exist_ok=True)
    manifest = compile_plan(values_mode=not args.plan_only)
    if args.plan_only:
        path = output / "acquisition_plan.json"
        _write_json(path, manifest)
        print(path)
        return 0

    opener = _opener(args.proxy)
    total_bytes = 0
    artifacts: list[dict[str, Any]] = []
    for source in REQUESTS:
        body, retrieval = _fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["expected_size_bytes"]),
        )
        _validate_body(body, source)
        if str(source["output_name"]).endswith(".json"):
            _validate_json_identity(body, str(source["source_id"]))
        total_bytes += len(body)
        if total_bytes > MAXIMUM_TOTAL_BYTES:
            raise ValueError("hec_ras_stage12_total_download_boundary_exceeded")
        path = output / str(source["output_name"])
        path.write_bytes(body)
        artifact = {
            **source,
            **retrieval,
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
        }
        if "expected_canonical_sha256" in source:
            artifact["canonical_sha256"] = _canonical_search_sha256(body)
        artifacts.append(artifact)
    manifest.update(
        {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": artifacts,
            "artifact_count": len(artifacts),
            "total_downloaded_bytes": total_bytes,
        }
    )
    path = output / "acquisition_manifest.json"
    _write_json(path, manifest)
    print(path)
    return 0


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    parsed = urllib.parse.urlparse(proxy)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("hec_ras_stage12_proxy_url_invalid")
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )


def _fetch(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    _validate_url(url)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                _validate_url(response.geturl())
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("hec_ras_stage12_object_boundary_exceeded")
                return body, {
                    "http_status": int(response.status),
                    "content_type": response.headers.get("Content-Type"),
                    "etag": response.headers.get("ETag"),
                    "final_url": response.geturl(),
                    "attempt_count": attempt,
                }
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 4))
    raise RuntimeError("hec_ras_stage12_download_failed") from last_error


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "raw.githubusercontent.com",
        "www.hec.usace.army.mil",
    }:
        raise ValueError("hec_ras_stage12_url_outside_allowlist")


def _validate_body(body: bytes, source: dict[str, object]) -> None:
    raw_identity_matches = (
        "expected_sha256" in source
        and hashlib.sha256(body).hexdigest() == source["expected_sha256"]
    )
    canonical_identity_matches = (
        "expected_canonical_sha256" in source
        and _canonical_search_sha256(body)
        == source["expected_canonical_sha256"]
    )
    if len(body) != int(source["expected_size_bytes"]) or not (
        raw_identity_matches or canonical_identity_matches
    ):
        raise ValueError("hec_ras_stage12_source_identity_mismatch")


def _canonical_search_sha256(body: bytes) -> str:
    value = json.loads(body)
    value.pop("searchDuration", None)
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_json_identity(body: bytes, source_id: str) -> None:
    value = json.loads(body)
    if source_id == "usace_momentum_based_junction_method":
        valid = value.get("id") == "43816560" and value.get("title") == (
            "Momentum Based Junction Method"
        )
    elif source_id == "usace_mixed_flow_specific_force":
        valid = value.get("id") == "43816541" and value.get("title") == (
            "Mixed Flow Regime Calculations"
        )
    else:
        valid = (
            value.get("cqlQuery") == JUNCTION_SEARCH_CQL
            and value.get("size") == 62
            and value.get("totalSize") == 62
        )
    if not valid:
        raise ValueError("hec_ras_stage12_json_identity_invalid")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())

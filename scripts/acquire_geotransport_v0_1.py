#!/usr/bin/env python3
"""Acquire bounded public metadata or values for GeoTransport v0.1."""

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

from data_agent.uwm.geospatial_kernel_v2.public_data import (
    AcquisitionRequest,
    DEFAULT_REGISTRY_PATH,
    build_metadata_requests,
    build_value_requests,
    load_public_data_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "data/geotransport_v0_1"
ACQUISITION_MANIFEST_SCHEMA = "gwm.geotransport.acquisition_manifest.v1"
USER_AGENT = "gisdataagent-geotransport-public-data/0.1"
ALLOWED_HOSTS = {
    "api.water.usgs.gov",
    "cwms-data.usace.army.mil",
    "data.usbr.gov",
    "noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com",
    "waterservices.usgs.gov",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("metadata", "plan-values", "values"),
        default="metadata",
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cohort", default="minimal")
    parser.add_argument("--system", action="append", dest="systems")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--accept-provisional", action="store_true")
    parser.add_argument("--nwm-extraction-manifest", type=Path)
    parser.add_argument("--evaluation-protocol", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = load_public_data_registry(args.registry)
    if args.mode == "metadata":
        if (
            args.start
            or args.end
            or args.accept_provisional
            or args.nwm_extraction_manifest
            or args.evaluation_protocol
        ):
            raise ValueError("metadata_mode_does_not_accept_value_arguments")
        requests = build_metadata_requests(registry, cohort=args.cohort)
        if args.systems:
            selected = set(args.systems)
            known = {system["system_id"] for system in registry.systems(args.cohort)}
            if not selected <= known:
                raise ValueError("unknown_selected_system")
            requests = tuple(
                request
                for request in requests
                if request.system_id is None or request.system_id in selected
            )
    else:
        if not args.start or not args.end:
            raise ValueError("value_mode_requires_start_and_end")
        nwm_manifest = None
        nwm_manifest_evidence = None
        evaluation_protocol_evidence = None
        evaluation_protocol = None
        if args.nwm_extraction_manifest is not None:
            body = args.nwm_extraction_manifest.read_bytes()
            nwm_manifest = json.loads(body)
            nwm_manifest_evidence = {
                "path": _display(args.nwm_extraction_manifest),
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
            }
        if args.evaluation_protocol is not None:
            protocol_body = args.evaluation_protocol.read_bytes()
            evaluation_protocol = json.loads(protocol_body)
            evaluation_protocol_evidence = {
                "path": _display(args.evaluation_protocol),
                "sha256": hashlib.sha256(protocol_body).hexdigest(),
                "size_bytes": len(protocol_body),
            }
            _validate_evaluation_protocol(
                evaluation_protocol,
                start=args.start,
                end=args.end,
                systems=args.systems,
                nwm_manifest=nwm_manifest,
                protocol_evidence=evaluation_protocol_evidence,
            )
        requests = build_value_requests(
            registry,
            start=args.start,
            end=args.end,
            cohort=args.cohort,
            system_ids=args.systems,
            nwm_extraction_manifest=nwm_manifest,
        )
        if args.mode == "values" and not args.accept_provisional:
            raise ValueError("values_mode_requires_accept_provisional")

    plan = {
        "schema": ACQUISITION_MANIFEST_SCHEMA,
        "mode": args.mode,
        "registry_path": _display(args.registry),
        "registry_sha256": registry.sha256,
        "cohort": args.cohort,
        "selected_systems": args.systems,
        "request_count": len(requests),
        "requests": [request.as_dict() for request in requests],
        "nwm_extraction_manifest": (
            nwm_manifest_evidence if args.mode != "metadata" else None
        ),
        "evaluation_protocol": (
            evaluation_protocol_evidence if args.mode != "metadata" else None
        ),
        "claim_boundary": {
            "request_plan_only": args.mode == "plan-values",
            "time_series_acquired": args.mode == "values",
            "source_values_are_provisional": args.mode == "values",
            "benchmark_validated": False,
        },
    }
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "plan-values":
        output = args.output / "value_request_plan.json"
        _write_json(output, plan)
        print(output)
        return 0

    raw_root = args.output / ("metadata" if args.mode == "metadata" else "raw")
    raw_root.mkdir(parents=True, exist_ok=True)
    opener = _opener(args.proxy)
    fetched: list[dict[str, Any]] = []
    for request in requests:
        fetched.extend(
            fetch_request(
                request,
                opener=opener,
                output_root=raw_root,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
            )
        )
    plan["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    plan["artifacts"] = fetched
    plan["artifact_count"] = len(fetched)
    manifest = args.output / (
        "metadata_manifest.json" if args.mode == "metadata" else "acquisition_manifest.json"
    )
    _write_json(manifest, plan)
    print(manifest)
    return 0


def _validate_evaluation_protocol(
    protocol: dict[str, Any],
    *,
    start: str,
    end: str,
    systems: list[str] | None,
    nwm_manifest: dict[str, Any] | None,
    protocol_evidence: dict[str, Any],
) -> None:
    split = protocol.get("temporal_split") or {}
    claims = protocol.get("claim_boundary") or {}
    if (
        protocol.get("schema")
        != "gwm.geotransport.center_hill_temporal_holdout_protocol.v1"
        or protocol.get("status")
        != "frozen_before_evaluation_outcome_acquisition"
        or protocol.get("system_id") != "center_hill"
        or systems != ["center_hill"]
        or start != split.get("acquisition_start_inclusive")
        or end != split.get("end_exclusive")
        or claims.get("protocol_frozen_before_evaluation_outcome_acquisition")
        is not True
        or claims.get("evaluation_values_acquired") is not False
    ):
        raise ValueError("evaluation_companion_frozen_protocol_invalid")
    if nwm_manifest is None:
        raise ValueError("evaluation_companion_nwm_manifest_required")
    if (
        nwm_manifest.get("schema")
        != "gwm.geotransport.center_hill_evaluation_nwm.v1"
        or nwm_manifest.get("mode") != "values"
        or nwm_manifest.get("evaluation_protocol") != protocol_evidence
        or (nwm_manifest.get("window") or {}).get("start_inclusive") != start
        or (nwm_manifest.get("window") or {}).get("end_exclusive") != end
    ):
        raise ValueError("evaluation_companion_nwm_lineage_invalid")


def fetch_request(
    request: AcquisitionRequest,
    *,
    opener: urllib.request.OpenerDirector,
    output_root: Path,
    timeout_seconds: float,
    retries: int,
) -> list[dict[str, Any]]:
    if retries <= 0:
        raise ValueError("retries_must_be_positive")
    url = request.url
    artifacts: list[dict[str, Any]] = []
    page = 1
    while url:
        _validate_url(url)
        body, response = _fetch_bytes(
            url,
            opener=opener,
            timeout_seconds=timeout_seconds,
            retries=retries,
            maximum_bytes=10_000_000 if request.kind == "metadata" else 100_000_000,
            accept=request.expected_media_type,
        )
        suffix = ".json" if "json" in request.expected_media_type else ".txt"
        page_suffix = f"-page-{page:04d}" if request.paginated else ""
        path = output_root / f"{request.request_id}{page_suffix}{suffix}"
        path.write_bytes(body)
        validation = validate_response(request, body)
        artifacts.append(
            {
                "request_id": request.request_id,
                "page": page,
                "source": request.source,
                "system_id": request.system_id,
                "variable_role": request.variable_role,
                "url": url,
                "http_status": response["status"],
                "content_type": response["content_type"],
                "retrieved_at": response["retrieved_at"],
                "path": _display(path),
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
                "validation": validation,
            }
        )
        if not request.paginated:
            break
        payload = json.loads(body)
        next_url = (payload.get("links") or {}).get("next")
        url = urllib.parse.urljoin(url, next_url) if next_url else ""
        page += 1
        if page > 1000:
            raise RuntimeError("pagination_limit_exceeded")
    return artifacts


def validate_response(
    request: AcquisitionRequest, body: bytes
) -> dict[str, object]:
    """Reject semantically wrong 200 responses before they enter a bundle."""

    parsed_url = urllib.parse.urlparse(request.url)
    query = urllib.parse.parse_qs(parsed_url.query)
    if request.kind != "metadata":
        if "json" in request.expected_media_type:
            json.loads(body)
        return {"status": "pass", "scope": "parseable_value_response"}
    if request.source == "usace_cwms":
        payload = json.loads(body)
        if "/locations/" in parsed_url.path:
            expected_location = urllib.parse.unquote(
                parsed_url.path.rstrip("/").split("/")[-1]
            )
            if payload.get("name") != expected_location:
                raise ValueError(
                    f"cwms_location_identity_mismatch:{expected_location}"
                )
            if not isinstance(payload.get("latitude"), (int, float)) or not isinstance(
                payload.get("longitude"), (int, float)
            ):
                raise ValueError(
                    f"cwms_location_coordinates_missing:{expected_location}"
                )
            return {
                "status": "pass",
                "location_id": expected_location,
                "office": payload.get("office-id"),
                "latitude": payload["latitude"],
                "longitude": payload["longitude"],
                "horizontal_datum": payload.get("horizontal-datum"),
                "location_type": payload.get("location-type"),
            }
        expected_name = query["like"][0]
        expected_office = query["office"][0]
        entries = payload.get("entries") or []
        exact = [
            entry
            for entry in entries
            if entry.get("name") == expected_name
            and entry.get("office") == expected_office
        ]
        if payload.get("total") != 1 or len(exact) != 1:
            raise ValueError(f"cwms_exact_series_metadata_mismatch:{expected_name}")
        entry = exact[0]
        if not entry.get("units") or not entry.get("interval") or not entry.get("extents"):
            raise ValueError(f"cwms_series_semantics_incomplete:{expected_name}")
        return {
            "status": "pass",
            "exact_series": expected_name,
            "office": expected_office,
            "units": entry["units"],
            "interval": entry["interval"],
        }
    if request.source == "usbr_rise":
        payload = json.loads(body)
        expected_item = int(parsed_url.path.rstrip("/").split("/")[-1])
        if payload.get("id") != expected_item:
            raise ValueError(f"rise_item_identity_mismatch:{expected_item}")
        if payload.get("dcat:accessLevel") != "public":
            raise ValueError(f"rise_item_not_public:{expected_item}")
        required = ("parameterName", "parameterUnit", "parameterTimestep", "catalogRecord")
        if any(not payload.get(key) for key in required):
            raise ValueError(f"rise_item_semantics_incomplete:{expected_item}")
        return {
            "status": "pass",
            "item_id": expected_item,
            "access_level": "public",
            "parameter_name": payload["parameterName"],
            "parameter_unit": payload["parameterUnit"],
            "parameter_timestep": payload["parameterTimestep"],
            "is_modeled": payload.get("isModeled"),
        }
    if request.source == "usgs_water_data":
        site_id = query["sites"][0]
        text = body.decode("utf-8")
        if f"USGS\t{site_id}\t" not in text:
            raise ValueError(f"usgs_site_identity_mismatch:{site_id}")
        return {"status": "pass", "site_id": site_id, "agency": "USGS"}
    if request.source == "usgs_nldi":
        payload = json.loads(body)
        expected_id = "USGS-" + request.request_id.removeprefix("nldi-link-")
        features = payload.get("features") or []
        if len(features) != 1 or features[0].get("id") != expected_id:
            raise ValueError(f"nldi_site_link_mismatch:{expected_id}")
        properties = features[0].get("properties") or {}
        if properties.get("comid") is None:
            raise ValueError(f"nldi_comid_missing:{expected_id}")
        return {
            "status": "pass",
            "site_id": expected_id,
            "comid": properties["comid"],
        }
    if request.source == "noaa_nwm_v3_retrospective":
        payload = json.loads(body)
        if request.request_id == "nwm-q-lateral-zarray":
            if payload.get("shape") != [385704, 2776734] or payload.get("dtype") != "<i4":
                raise ValueError("nwm_q_lateral_zarray_schema_mismatch")
            return {
                "status": "pass",
                "shape": payload["shape"],
                "dtype": payload["dtype"],
            }
        if request.request_id == "nwm-q-lateral-zattrs":
            if (
                payload.get("_ARRAY_DIMENSIONS") != ["time", "feature_id"]
                or payload.get("long_name") != "Runoff into channel reach"
                or payload.get("units") != "m3 s-1"
            ):
                raise ValueError("nwm_q_lateral_zattrs_schema_mismatch")
            return {
                "status": "pass",
                "dimensions": payload["_ARRAY_DIMENSIONS"],
                "long_name": payload["long_name"],
                "units": payload["units"],
                "scale_factor": payload.get("scale_factor"),
            }
        if request.request_id == "nwm-feature-id-zarray":
            if payload.get("shape") != [2776734] or payload.get("dtype") != "<i8":
                raise ValueError("nwm_feature_id_zarray_schema_mismatch")
            return {
                "status": "pass",
                "shape": payload["shape"],
                "dtype": payload["dtype"],
                "chunks": payload.get("chunks"),
            }
        if request.request_id == "nwm-feature-id-zattrs":
            if payload.get("_ARRAY_DIMENSIONS") != ["feature_id"]:
                raise ValueError("nwm_feature_id_zattrs_schema_mismatch")
            return {
                "status": "pass",
                "dimensions": payload["_ARRAY_DIMENSIONS"],
                "long_name": payload.get("long_name"),
                "comment": payload.get("comment"),
            }
        if request.request_id == "nwm-time-zarray":
            if payload.get("shape") != [385704] or payload.get("dtype") != "<i8":
                raise ValueError("nwm_time_zarray_schema_mismatch")
            return {
                "status": "pass",
                "shape": payload["shape"],
                "dtype": payload["dtype"],
                "chunks": payload.get("chunks"),
            }
        if request.request_id == "nwm-time-zattrs":
            if (
                payload.get("_ARRAY_DIMENSIONS") != ["time"]
                or payload.get("units") != "hours since 1979-02-01T01:00:00"
            ):
                raise ValueError("nwm_time_zattrs_schema_mismatch")
            return {
                "status": "pass",
                "dimensions": payload["_ARRAY_DIMENSIONS"],
                "units": payload["units"],
                "calendar": payload.get("calendar"),
            }
        raise ValueError("unknown_nwm_metadata_contract")
    raise ValueError("unsupported_metadata_source")


def _fetch_bytes(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
    accept: str,
) -> tuple[bytes, dict[str, object]]:
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={"Accept": accept, "User-Agent": USER_AGENT},
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("response_size_limit_exceeded")
                return body, {
                    "status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RuntimeError(f"non_retryable_http_error:{url}:{exc.code}") from exc
            error = exc
            if attempt < retries:
                time.sleep(float(attempt))
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(float(attempt))
    raise RuntimeError(f"request_failed:{url}:{error}")


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("request_url_outside_official_allowlist")


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())

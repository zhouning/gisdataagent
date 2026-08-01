#!/usr/bin/env python3
"""Acquire hash-locked HEC-RAS Example 10 conformance evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / ".tmp/geotransport/hec_ras_example10"
SCHEMA = "gwm.geotransport.hec_ras_example10_acquisition.v1"
USER_AGENT = "gisdataagent-hec-ras-example10-conformance/0.1"
MAXIMUM_TOTAL_BYTES = 500_000

OFFICIAL_ARCHIVE_URL = (
    "https://www.hec.usace.army.mil/confluence/download/attachments/"
    "80528340/Example%2010%20-%20Stream%20Junction.zip?version=1&"
    "modificationDate=1642646172667&api=v2"
)
OFFICIAL_TABLE_URL = (
    "https://www.hec.usace.army.mil/confluence/download/attachments/"
    "80528340/worddav48427a90af6fd779f2528e3743d30d6d.png?version=1&"
    "modificationDate=1644264027764&api=v2"
)
SECONDARY_HDF_URL = (
    "https://raw.githubusercontent.com/leixiaohui-1974/HydroClaude/"
    "99f17382ce4dea93055e8d4ecf6732d287be4cc4/reports/"
    "hecras_examples_raw/Applications%20Guide/"
    "Example%2010%20-%20Stream%20Junction/JUNCTION.p02.hdf"
)

REQUESTS = (
    {
        "source_id": "usace_example10_archive",
        "url": OFFICIAL_ARCHIVE_URL,
        "output_name": "Example 10 - Stream Junction.zip",
        "expected_size_bytes": 10_838,
        "expected_sha256": (
            "c17a7e0e48c9578ce04caa9ffbdb798b979f4f7beb1be027f543b8e45f7f98c2"
        ),
        "role": "authoritative_official_model_input",
    },
    {
        "source_id": "usace_example10_momentum_table",
        "url": OFFICIAL_TABLE_URL,
        "output_name": "momentum_standard_table_2.png",
        "expected_size_bytes": 98_515,
        "expected_sha256": (
            "e38d571214ec7c6ba842d90d5ec7368694faead75ff61e17bf61aced48d99624"
        ),
        "role": "authoritative_official_published_result_table",
    },
    {
        "source_id": "hydroclaude_hec_ras_66_recomputation",
        "url": SECONDARY_HDF_URL,
        "output_name": "secondary_JUNCTION.p02.hdf",
        "expected_size_bytes": 377_015,
        "expected_sha256": (
            "762b14a079570c2dabd2e4ffdef29bfde561a13cd0fcd09b15353f6de3efa4b6"
        ),
        "role": "secondary_recomputation_diagnostic_not_official_observation",
    },
)

REQUIRED_ARCHIVE_MEMBERS = {
    "JUNCTION.G02": (
        "a2dc3d5ee9b016d9a98bbf8f4e52af110f26d25db17d1130756854b03828e097"
    ),
    "JUNCTION.F01": (
        "c4a56991b29ea269fd64339e03df13361ba29cd53dd74eed315c6d4d5ebdc9a7"
    ),
    "JUNCTION.P02": (
        "dfacb884cb8be53ad5bcda9c78c7fabb6774d4008cd017b5e88d5dfaf250d211"
    ),
}


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
        raise ValueError("hec_ras_example10_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "purpose": (
            "conform irregular-section hydraulics and diagnose the documented "
            "projected-momentum junction equation without calibration"
        ),
        "request_boundary": {
            "allowed_hosts": sorted(
                {
                    urllib.parse.urlparse(str(value["url"])).hostname
                    for value in REQUESTS
                }
            ),
            "object_count": len(REQUESTS),
            "maximum_total_bytes": MAXIMUM_TOTAL_BYTES,
            "planned_exact_bytes": planned_bytes,
            "workspace_or_private_data_sent": False,
        },
        "requests": [dict(value) for value in REQUESTS],
        "evidence_roles": {
            "USACE_archive_and_table": "authoritative",
            "HydroClaude_fixed_commit_HDF": (
                "secondary HEC-RAS 6.6 recomputation; not a USACE original "
                "observation or independent field truth"
            ),
        },
        "claim_boundary": {
            "source_values_acquired": values_mode,
            "calibration_authorized": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("hec_ras_example10_positive_request_limits_required")
    output = args.output.resolve()
    ignored_root = (REPO_ROOT / ".tmp").resolve()
    if ignored_root not in output.parents:
        raise ValueError("hec_ras_example10_output_must_be_under_ignored_tmp")
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
        total_bytes += len(body)
        if total_bytes > MAXIMUM_TOTAL_BYTES:
            raise ValueError("hec_ras_example10_total_download_boundary_exceeded")
        path = output / str(source["output_name"])
        path.write_bytes(body)
        artifact = {
            **source,
            **retrieval,
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
        }
        if source["source_id"] == "usace_example10_archive":
            artifact["required_members"] = _audit_archive_members(body)
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
        raise ValueError("hec_ras_example10_proxy_url_invalid")
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
                    raise ValueError("hec_ras_example10_object_boundary_exceeded")
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
    raise RuntimeError("hec_ras_example10_download_failed") from last_error


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    allowed_hosts = {
        "www.hec.usace.army.mil",
        "raw.githubusercontent.com",
    }
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise ValueError("hec_ras_example10_url_outside_allowlist")


def _validate_body(body: bytes, source: dict[str, object]) -> None:
    if (
        len(body) != int(source["expected_size_bytes"])
        or hashlib.sha256(body).hexdigest() != source["expected_sha256"]
    ):
        raise ValueError("hec_ras_example10_source_identity_mismatch")


def _audit_archive_members(body: bytes) -> dict[str, dict[str, object]]:
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = tuple(archive.namelist())
        audit: dict[str, dict[str, object]] = {}
        for suffix, expected_sha256 in REQUIRED_ARCHIVE_MEMBERS.items():
            matches = [name for name in names if name.endswith(suffix)]
            if len(matches) != 1:
                raise ValueError("hec_ras_example10_archive_member_invalid")
            member_body = archive.read(matches[0])
            actual_sha256 = hashlib.sha256(member_body).hexdigest()
            if actual_sha256 != expected_sha256:
                raise ValueError("hec_ras_example10_archive_member_hash_mismatch")
            audit[suffix] = {
                "archive_path": matches[0],
                "sha256": actual_sha256,
                "size_bytes": len(member_body),
            }
    return audit


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())

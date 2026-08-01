#!/usr/bin/env python3
"""Acquire bounded public metadata for Stage 13 confluence validation audit."""

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
DEFAULT_OUTPUT = REPO_ROOT / ".tmp/geotransport/stage13_confluence_evidence"
SCHEMA = "gwm.geotransport.stage13_confluence_evidence_acquisition.v1"
USER_AGENT = "gisdataagent-stage13-confluence-audit/0.1"
MAXIMUM_TOTAL_BYTES = 300_000

REQUESTS = (
    {
        "source_id": "crossref_open_channel_junction_catalog",
        "url": (
            "https://api.crossref.org/works?"
            + urllib.parse.urlencode(
                {
                    "query.title": "open channel junction flow",
                    "rows": 10,
                    "select": "DOI,title,published,type,URL",
                }
            )
        ),
        "output_name": "crossref_open_channel_junction_catalog.json",
        "maximum_bytes": 80_000,
        "role": "literature_discovery_not_observation_data",
    },
    {
        "source_id": "openalex_shumate_junction_thesis",
        "url": (
            "https://api.openalex.org/works/"
            "https://doi.org/10.17077/etd.9q5a2qez"
        ),
        "output_name": "openalex_shumate_junction_thesis.json",
        "maximum_bytes": 100_000,
        "role": "open_access_and_repository_availability_audit",
    },
    {
        "source_id": "zenodo_confluence_angle_record",
        "url": "https://zenodo.org/api/records/14033",
        "output_name": "zenodo_confluence_angle_record.json",
        "maximum_bytes": 100_000,
        "role": "open_publication_file_type_audit_not_raw_measurement_data",
    },
    {
        "source_id": "github_confluence_data_repository_search",
        "url": (
            "https://api.github.com/search/repositories?"
            + urllib.parse.urlencode(
                {
                    "q": "open-channel confluence hydraulic data",
                    "per_page": 10,
                }
            )
        ),
        "output_name": "github_confluence_data_repository_search.json",
        "maximum_bytes": 20_000,
        "role": "public_source_code_and_data_discovery_not_negative_proof",
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
    planned_bytes = sum(int(value["maximum_bytes"]) for value in REQUESTS)
    if planned_bytes > MAXIMUM_TOTAL_BYTES:
        raise ValueError("stage13_confluence_evidence_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "purpose": (
            "find independently usable public confluence observations with "
            "geometry and hydraulic state, without defining or fitting the "
            "native Stage 13 junction law"
        ),
        "request_boundary": {
            "allowed_hosts": [
                "api.crossref.org",
                "api.github.com",
                "api.openalex.org",
                "zenodo.org",
            ],
            "object_count": len(REQUESTS),
            "maximum_total_bytes": MAXIMUM_TOTAL_BYTES,
            "planned_maximum_bytes": planned_bytes,
            "workspace_or_private_data_sent": False,
        },
        "requests": [dict(value) for value in REQUESTS],
        "claim_boundary": {
            "source_values_acquired": values_mode,
            "literature_metadata_is_hydraulic_observation": False,
            "catalog_search_is_negative_proof": False,
            "law_defined_by_public_search_result": False,
            "calibration_authorized": False,
            "operator_admitted": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("stage13_confluence_evidence_request_limits_invalid")
    output = args.output.resolve()
    ignored_root = (REPO_ROOT / ".tmp").resolve()
    if ignored_root not in output.parents:
        raise ValueError("stage13_confluence_evidence_output_must_be_ignored")
    output.mkdir(parents=True, exist_ok=True)
    manifest = compile_plan(values_mode=not args.plan_only)
    if args.plan_only:
        path = output / "acquisition_plan.json"
        _write_json(path, manifest)
        print(path)
        return 0

    opener = _opener(args.proxy)
    artifacts = []
    total_bytes = 0
    for source in REQUESTS:
        body, retrieval = _fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["maximum_bytes"]),
        )
        _validate_json_identity(body, str(source["source_id"]))
        total_bytes += len(body)
        if total_bytes > MAXIMUM_TOTAL_BYTES:
            raise ValueError(
                "stage13_confluence_evidence_total_download_boundary_exceeded"
            )
        path = output / str(source["output_name"])
        path.write_bytes(body)
        artifacts.append(
            {
                **source,
                **retrieval,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
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
        raise ValueError("stage13_confluence_evidence_proxy_url_invalid")
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
) -> tuple[bytes, dict[str, object]]:
    _validate_url(url)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                _validate_url(response.geturl())
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError(
                        "stage13_confluence_evidence_object_boundary_exceeded"
                    )
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
    raise RuntimeError("stage13_confluence_evidence_download_failed") from last_error


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "api.crossref.org",
        "api.github.com",
        "api.openalex.org",
        "zenodo.org",
    }:
        raise ValueError("stage13_confluence_evidence_url_outside_allowlist")


def _validate_json_identity(body: bytes, source_id: str) -> None:
    value = json.loads(body)
    if source_id == "crossref_open_channel_junction_catalog":
        valid = (
            value.get("status") == "ok"
            and value.get("message-type") == "work-list"
            and any(
                item.get("DOI")
                == "10.1061/(asce)0733-9429(1998)124:8(847)"
                for item in value.get("message", {}).get("items", [])
            )
        )
    elif source_id == "openalex_shumate_junction_thesis":
        valid = (
            value.get("doi") == "https://doi.org/10.17077/etd.9q5a2qez"
            and value.get("title")
            == "Experimental Description of Flow at an Open-Channel Junction"
        )
    elif source_id == "zenodo_confluence_angle_record":
        valid = (
            value.get("id") == 14033
            and value.get("metadata", {}).get("resource_type", {}).get("type")
            == "publication"
        )
    elif source_id == "github_confluence_data_repository_search":
        valid = isinstance(value.get("total_count"), int) and isinstance(
            value.get("items"), list
        )
    else:
        valid = False
    if not valid:
        raise ValueError("stage13_confluence_evidence_json_identity_invalid")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Standard-source registry helpers for MMFE semantic products.

The registry is intentionally lightweight: it records where semantic standards
come from, what authority published them, and whether a full text has been
verified or downloaded. It does not embed standard full text in fixtures.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile
import xml.etree.ElementTree as ET


STANDARD_SOURCE_REGISTRY_SCHEMA = "mmfe.standard_source_registry.v1"
STANDARD_SOURCE_INGESTION_PLAN_SCHEMA = "mmfe.standard_source_ingestion_plan.v1"
STANDARD_SOURCE_INGESTION_RUN_SCHEMA = "mmfe.standard_source_ingestion_run.v1"
STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA = "mmfe.standard_source_citation_anchors.v1"


OPENSTD_BASE_URL = "https://openstd.samr.gov.cn/bzgk/gb/"
OPENSTD_DETAIL_TEMPLATE = (
    "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={hcno}"
)
OPENSTD_SEARCH_TEMPLATE = (
    "https://openstd.samr.gov.cn/bzgk/std/std_list"
    "?p.p1=0&p.p90=circulation_date&p.p91=desc&p.p2={query}"
)


OFFICIAL_STANDARD_OVERRIDES = {
    "GB/T 21010-2017 土地利用现状分类": {
        "standard_identifier": "GB/T 21010-2017",
        "title_zh": "土地利用现状分类",
        "title_en": "Current land use classification",
        "standard_type": "推荐性国家标准",
        "status": "现行",
        "publication_date": "2017-11-01",
        "implementation_date": "2017-11-01",
        "ccs": "A76",
        "ics": "07.040",
        "authority": "国家市场监督管理总局 / 国家标准化管理委员会",
        "department": "自然资源部（国土）",
        "technical_committee": "自然资源部（国土）",
        "publisher": "中华人民共和国国家质量监督检验检疫总局、中国国家标准化管理委员会",
        "official_platform": "国家标准全文公开系统",
        "official_url": OPENSTD_DETAIL_TEMPLATE.format(
            hcno="224BF9DA69F053DA22AC758AAAADEEAA"
        ),
        "search_url": OPENSTD_SEARCH_TEMPLATE.format(query="GB/T%2021010-2017"),
        "hcno": "224BF9DA69F053DA22AC758AAAADEEAA",
        "retrieval_status": "official_fulltext_available",
        "access_mode": "online_preview_and_download",
        "retrieval_method": "official_platform_metadata_verified",
        "local_path": "",
        "can_download": True,
        "can_online_preview": True,
        "used_for": [
            "land_use_code_value_domain",
            "parcel_current_land_use_semantics",
        ],
        "evidence_note_zh": (
            "已在国家标准全文公开系统核验题录详情，详情页提供在线预览与下载标准按钮；"
            "当前测试夹具只登记官方入口和元数据，不内置标准全文。"
        ),
    },
}


NATURAL_RESOURCE_ONE_MAP_DOC_HINTS = {
    "自然资源“一张图”数据库体系结构（2）统一调查监测1126": {
        "standard_identifier": "NR-ONE-MAP-DB-ARCH-02-SURVEY-MONITORING",
        "title_zh": "自然资源“一张图”数据库体系结构（2）统一调查监测1126",
        "authority": "自然资源领域专家材料 / 待对齐自然资源主管部门公开发布源",
        "official_platform": "待核验自然资源主管部门或标准公开平台",
        "retrieval_status": "local_expert_material_available",
        "access_mode": "local_package",
        "retrieval_method": "local_source_package",
        "used_for": ["parcel_current_role_contract", "monitoring_layer_contracts"],
        "evidence_note_zh": (
            "当前来自用户提供的自然资源一张图数据库标准包，用于工程语义契约；"
            "生产前应补充公开正式发布源或主管部门标准库引用。"
        ),
    },
    "自然资源“一张图”数据库体系结构（4）统一规划1126": {
        "standard_identifier": "NR-ONE-MAP-DB-ARCH-04-PLANNING",
        "title_zh": "自然资源“一张图”数据库体系结构（4）统一规划1126",
        "authority": "自然资源领域专家材料 / 待对齐自然资源主管部门公开发布源",
        "official_platform": "待核验自然资源主管部门或标准公开平台",
        "retrieval_status": "local_expert_material_available",
        "access_mode": "local_package",
        "retrieval_method": "local_source_package",
        "used_for": ["planning_zone_contracts", "urban_boundary_contracts"],
        "evidence_note_zh": "当前来自用户提供的自然资源一张图数据库标准包，生产前需补充官方发布源。",
    },
    "自然资源“一张图”数据库体系结构（5）底线安全1126": {
        "standard_identifier": "NR-ONE-MAP-DB-ARCH-05-SAFETY-BASELINE",
        "title_zh": "自然资源“一张图”数据库体系结构（5）底线安全1126",
        "authority": "自然资源领域专家材料 / 待对齐自然资源主管部门公开发布源",
        "official_platform": "待核验自然资源主管部门或标准公开平台",
        "retrieval_status": "local_expert_material_available",
        "access_mode": "local_package",
        "retrieval_method": "local_source_package",
        "used_for": ["pbf_contracts", "ecological_redline_contracts"],
        "evidence_note_zh": "当前来自用户提供的自然资源一张图数据库标准包，生产前需补充官方发布源。",
    },
    "自然资源“一张图”数据库体系结构（6）用途管制1128V2": {
        "standard_identifier": "NR-ONE-MAP-DB-ARCH-06-USE-CONTROL",
        "title_zh": "自然资源“一张图”数据库体系结构（6）用途管制1128V2",
        "authority": "自然资源领域专家材料 / 待对齐自然资源主管部门公开发布源",
        "official_platform": "待核验自然资源主管部门或标准公开平台",
        "retrieval_status": "local_expert_material_available",
        "access_mode": "local_package",
        "retrieval_method": "local_source_package",
        "used_for": ["project_contracts", "use_control_rules"],
        "evidence_note_zh": "当前来自用户提供的自然资源一张图数据库标准包，生产前需补充官方发布源。",
    },
    "自然资源“一张图”数据库体系结构（8）执法督察0922": {
        "standard_identifier": "NR-ONE-MAP-DB-ARCH-08-LAW-ENFORCEMENT",
        "title_zh": "自然资源“一张图”数据库体系结构（8）执法督察0922",
        "authority": "自然资源领域专家材料 / 待对齐自然资源主管部门公开发布源",
        "official_platform": "待核验自然资源主管部门或标准公开平台",
        "retrieval_status": "local_expert_material_available",
        "access_mode": "local_package",
        "retrieval_method": "local_source_package",
        "used_for": ["review_tasks", "rule_evidence_contracts"],
        "evidence_note_zh": "当前来自用户提供的自然资源一张图数据库标准包，生产前需补充官方发布源。",
    },
    "自然资源“一张图”数据库体系结构（10）元数据0907": {
        "standard_identifier": "NR-ONE-MAP-DB-ARCH-10-METADATA",
        "title_zh": "自然资源“一张图”数据库体系结构（10）元数据0907",
        "authority": "自然资源领域专家材料 / 待对齐自然资源主管部门公开发布源",
        "official_platform": "待核验自然资源主管部门或标准公开平台",
        "retrieval_status": "local_expert_material_available",
        "access_mode": "local_package",
        "retrieval_method": "local_source_package",
        "used_for": ["metadata_vector", "source_lineage_contracts"],
        "evidence_note_zh": "当前来自用户提供的自然资源一张图数据库标准包，生产前需补充官方发布源。",
    },
}


def build_standard_source_registry(
    role_contracts: dict[str, Any],
    standards_dir: str | Path | None = None,
    timestamp: str | None = None,
) -> dict:
    """Build a source registry from standard contract source documents."""
    source_docs = _source_documents(role_contracts)
    entries = [
        _build_source_entry(doc_name, standards_dir=standards_dir)
        for doc_name in source_docs
    ]
    summary = build_standard_source_summary(entries)
    return {
        "schema": STANDARD_SOURCE_REGISTRY_SCHEMA,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "source_count": len(entries),
        "entries": entries,
        "summary": summary,
    }


def build_standard_source_summary(entries: list[dict]) -> dict:
    """Summarize standard-source acquisition status."""
    status_counts = Counter(entry.get("retrieval_status") or "unknown" for entry in entries)
    access_counts = Counter(entry.get("access_mode") or "unknown" for entry in entries)
    official_entries = [
        entry
        for entry in entries
        if str(entry.get("retrieval_status") or "").startswith("official_")
        or entry.get("official_url")
    ]
    fulltext_ready = [
        entry
        for entry in entries
        if entry.get("retrieval_status")
        in {"official_fulltext_available", "downloaded_fulltext"}
    ]
    pending_official = [
        entry
        for entry in entries
        if entry.get("retrieval_status")
        in {"local_expert_material_available", "official_source_pending"}
    ]
    return {
        "source_count": len(entries),
        "official_verified_count": len(official_entries),
        "fulltext_available_or_downloaded_count": len(fulltext_ready),
        "pending_official_source_count": len(pending_official),
        "retrieval_status_distribution": dict(status_counts),
        "access_mode_distribution": dict(access_counts),
        "officially_verified_identifiers": [
            entry.get("standard_identifier")
            for entry in official_entries
            if entry.get("standard_identifier")
        ],
        "production_gap_zh": (
            "当前已把标准来源纳入可审计清单。GB/T 21010-2017 已核验官方全文公开入口；"
            "自然资源一张图数据库体系结构系列当前仍以专家材料包为工程契约，"
            "生产前需要补齐主管部门公开发布源、正式版本号和全文抽取证据。"
        ),
    }


def flatten_standard_source_registry(registry: dict) -> list[dict]:
    """Return CSV-friendly rows for a standard-source registry."""
    rows = []
    for entry in registry.get("entries") or []:
        rows.append({
            "source_name": entry.get("source_name", ""),
            "standard_identifier": entry.get("standard_identifier", ""),
            "title_zh": entry.get("title_zh", ""),
            "title_en": entry.get("title_en", ""),
            "standard_type": entry.get("standard_type", ""),
            "status": entry.get("status", ""),
            "authority": entry.get("authority", ""),
            "department": entry.get("department", ""),
            "official_platform": entry.get("official_platform", ""),
            "official_url": entry.get("official_url", ""),
            "search_url": entry.get("search_url", ""),
            "retrieval_status": entry.get("retrieval_status", ""),
            "access_mode": entry.get("access_mode", ""),
            "retrieval_method": entry.get("retrieval_method", ""),
            "local_path": entry.get("local_path", ""),
            "can_download": bool(entry.get("can_download")),
            "can_online_preview": bool(entry.get("can_online_preview")),
            "publication_date": entry.get("publication_date", ""),
            "implementation_date": entry.get("implementation_date", ""),
            "ccs": entry.get("ccs", ""),
            "ics": entry.get("ics", ""),
            "used_for_json": _jsonish(entry.get("used_for") or []),
            "evidence_note_zh": entry.get("evidence_note_zh", ""),
            "not_for_production_gap": bool(entry.get("not_for_production_gap")),
        })
    return rows


def build_standard_source_ingestion_plan(
    registry: dict,
    *,
    timestamp: str | None = None,
) -> dict:
    """Build an auditable acquisition/extraction plan for standard sources."""
    if not isinstance(registry, dict):
        raise ValueError("standard source registry must be a JSON object")
    entries = [dict(entry) for entry in registry.get("entries") or [] if isinstance(entry, dict)]
    tasks = [_build_ingestion_task(entry, index) for index, entry in enumerate(entries)]
    blocking_tasks = [task for task in tasks if task["status"] != "ready"]
    return {
        "schema": STANDARD_SOURCE_INGESTION_PLAN_SCHEMA,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "registry_schema": registry.get("schema", ""),
        "source_count": len(entries),
        "task_count": len(tasks),
        "summary": {
            "ready": bool(tasks) and not blocking_tasks,
            "ready_task_count": sum(1 for task in tasks if task["status"] == "ready"),
            "blocked_task_count": len(blocking_tasks),
            "download_required_count": sum(1 for task in tasks if task.get("download_required")),
            "official_source_missing_count": sum(
                1 for task in tasks if "official_source_missing" in task.get("blocking_reasons", [])
            ),
            "checksum_missing_count": sum(
                1 for task in tasks if "checksum_missing" in task.get("blocking_reasons", [])
            ),
            "fulltext_extraction_missing_count": sum(
                1 for task in tasks if "fulltext_extraction_missing" in task.get("blocking_reasons", [])
            ),
        },
        "tasks": tasks,
    }


def validate_standard_source_ingestion_plan(payload: dict) -> dict:
    """Validate the standard-source ingestion plan contract surface."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != STANDARD_SOURCE_INGESTION_PLAN_SCHEMA:
        errors.append(f"schema must be {STANDARD_SOURCE_INGESTION_PLAN_SCHEMA}")
    if not isinstance(payload.get("tasks"), list):
        errors.append("tasks must be a list")
    summary = payload.get("summary") or {}
    if not isinstance(summary.get("ready"), bool):
        errors.append("summary.ready must be boolean")
    return {"valid": not errors, "errors": errors}


def run_standard_source_ingestion_plan(
    plan: dict,
    *,
    fetcher=None,
    archiver=None,
    extractor=None,
    timestamp: str | None = None,
) -> dict:
    """Execute standard-source ingestion tasks through injected adapters."""
    validation = validate_standard_source_ingestion_plan(plan)
    if not validation["valid"]:
        return _standard_source_ingestion_run_result(
            plan if isinstance(plan, dict) else {},
            [],
            [{"task_id": "", "errors": validation["errors"]}],
            timestamp=timestamp,
        )

    task_results = []
    errors = []
    for task in plan.get("tasks") or []:
        result = _run_standard_source_ingestion_task(
            task,
            fetcher=fetcher,
            archiver=archiver,
            extractor=extractor,
        )
        task_results.append(result)
        if not result.get("valid"):
            errors.append({"task_id": task.get("task_id"), "errors": list(result.get("errors") or [])})

    return _standard_source_ingestion_run_result(plan, task_results, errors, timestamp=timestamp)


def validate_standard_source_ingestion_run(payload: dict) -> dict:
    """Validate the standard-source ingestion run result surface."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != STANDARD_SOURCE_INGESTION_RUN_SCHEMA:
        errors.append(f"schema must be {STANDARD_SOURCE_INGESTION_RUN_SCHEMA}")
    if not isinstance(payload.get("task_results"), list):
        errors.append("task_results must be a list")
    if not isinstance(payload.get("errors"), list):
        errors.append("errors must be a list")
    return {"valid": not errors, "errors": errors}


def apply_standard_source_ingestion_run(
    registry: dict,
    ingestion_run: dict,
    *,
    timestamp: str | None = None,
) -> dict:
    """Return a registry copy enriched with successful ingestion-run evidence."""
    if not isinstance(registry, dict):
        raise ValueError("standard source registry must be a JSON object")
    validation = validate_standard_source_ingestion_run(ingestion_run)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))

    results_by_identifier = {
        str(result.get("standard_identifier") or ""): result
        for result in ingestion_run.get("task_results") or []
        if isinstance(result, dict) and result.get("valid") and result.get("standard_identifier")
    }
    updated_entries = []
    for entry in registry.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        updated = dict(entry)
        result = results_by_identifier.get(str(updated.get("standard_identifier") or ""))
        if result:
            _apply_ingestion_result_to_entry(updated, result)
        updated_entries.append(updated)

    updated_registry = dict(registry)
    updated_registry["updated_at"] = timestamp or datetime.now(timezone.utc).isoformat()
    updated_registry["source_count"] = len(updated_entries)
    updated_registry["entries"] = updated_entries
    updated_registry["summary"] = build_standard_source_summary(updated_entries)
    updated_registry["last_ingestion_run"] = {
        "schema": ingestion_run.get("schema", ""),
        "created_at": ingestion_run.get("created_at", ""),
        "valid": bool(ingestion_run.get("valid")),
        "summary": dict(ingestion_run.get("summary") or {}),
    }
    return updated_registry


def build_local_standard_source_fetcher(
    *,
    source_root: str | Path | None = None,
    sources_by_identifier: dict[str, str | Path] | None = None,
    sources_by_task_id: dict[str, str | Path] | None = None,
):
    """Build a fetcher that reads standard full text from local files.

    This is the first concrete ingestion adapter path for development and
    offline production rehearsal. It deliberately does not perform network
    fetches; official download implementations should be injected separately.
    """

    def fetcher(task: dict) -> dict[str, Any]:
        source_path = _resolve_local_standard_source_path(
            task,
            source_root=source_root,
            sources_by_identifier=sources_by_identifier,
            sources_by_task_id=sources_by_task_id,
        )
        if not source_path:
            raise ValueError(
                "local source path is required; provide task.local_path, "
                "sources_by_identifier, sources_by_task_id, or source_root"
            )
        path = Path(source_path)
        if not path.exists() or not path.is_file():
            raise ValueError(f"local source path must be an existing file: {path}")
        body = path.read_bytes()
        return {
            "body": body,
            "bytes_fetched": len(body),
            "local_path": str(path),
            "source_path": str(path),
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": _guess_source_content_type(path),
        }

    return fetcher


def build_http_standard_source_fetcher(
    *,
    allowed_domains: list[str] | tuple[str, ...] | set[str] | None = None,
    timeout_seconds: float = 30.0,
    user_agent: str = "gisdataagent-mmfe-standard-source-fetcher/1.0",
    opener=None,
):
    """Build an explicit HTTP(S) fetcher for official standard-source URLs.

    The fetcher is only used when injected into the ingestion runner. MMFE does
    not call it by default, and tests can inject ``opener`` to avoid networking.
    """
    allowed = {str(domain).lower() for domain in (allowed_domains or []) if domain}

    def fetcher(task: dict) -> dict[str, Any]:
        url = str(task.get("download_url") or task.get("official_url") or task.get("url") or "")
        if not url:
            raise ValueError("official_url or download_url is required for HTTP standard-source fetch")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("standard-source HTTP fetch requires an absolute http(s) URL")
        host = parsed.hostname or ""
        if allowed and not _domain_allowed(host, allowed):
            raise ValueError(f"standard-source host is not allowed: {host}")

        request = Request(url, headers={"User-Agent": user_agent})
        open_func = opener or urlopen
        try:
            response = open_func(request, timeout=timeout_seconds)
        except TypeError:
            response = open_func(request)
        with response:
            body = response.read()
            headers = getattr(response, "headers", {}) or {}
            status = getattr(response, "status", getattr(response, "code", 200))
            final_url = getattr(response, "url", url)
        content_type = _response_content_type(headers) or _guess_source_content_type(Path(parsed.path))
        return {
            "body": body,
            "bytes_fetched": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": content_type,
            "source_url": final_url,
            "http_status": _safe_int(status, 0),
        }

    return fetcher


def build_local_standard_source_archiver(
    archive_dir: str | Path,
    *,
    uri_prefix: str | None = None,
):
    """Build an archiver that writes fetched standards into a local directory."""
    archive_root = Path(archive_dir)

    def archiver(task: dict, body: bytes) -> dict[str, Any]:
        if not isinstance(body, bytes) or not body:
            raise ValueError("body must be non-empty bytes")
        archive_root.mkdir(parents=True, exist_ok=True)
        filename = _archive_filename(task, body)
        target_path = archive_root / filename
        target_path.write_bytes(body)
        sha256 = hashlib.sha256(body).hexdigest()
        archive_uri = _join_uri_prefix(uri_prefix, filename) if uri_prefix else target_path.as_uri()
        return {
            "archive_uri": archive_uri,
            "local_path": str(target_path),
            "bytes_written": len(body),
            "sha256": sha256,
            "content_type": _guess_source_content_type(target_path),
        }

    return archiver


def build_s3_standard_source_archiver(
    *,
    target_uri_prefix: str,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region_name: str | None = None,
):
    """Build an archiver that writes standard-source bytes to S3/MinIO."""

    def archiver(task: dict, body: bytes) -> dict[str, Any]:
        return archive_standard_source_bytes_to_s3(
            task,
            body,
            target_uri_prefix=target_uri_prefix,
            endpoint_url=endpoint_url,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region_name=region_name,
        )

    return archiver


def archive_standard_source_bytes_to_s3(
    task: dict,
    body: bytes,
    *,
    target_uri_prefix: str,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region_name: str | None = None,
) -> dict[str, Any]:
    """Archive one fetched standard-source payload to an S3-compatible store."""
    if not isinstance(body, bytes) or not body:
        raise ValueError("body must be non-empty bytes")
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except Exception as exc:  # pragma: no cover - exercised when optional deps absent.
        raise RuntimeError("S3 standard-source archiving requires optional dependency: boto3") from exc

    bucket, key_prefix = _s3_target_prefix(target_uri_prefix)
    filename = _archive_filename(task, body)
    key = f"{key_prefix.rstrip('/')}/{filename}" if key_prefix else filename
    content_type = str(task.get("content_type") or "") or _guess_source_content_type(Path(filename))
    sha256 = hashlib.sha256(body).hexdigest()

    endpoint = endpoint_url or os.environ.get("AWS_ENDPOINT_URL") or None
    client_kwargs = {
        "aws_access_key_id": access_key_id or os.environ.get("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "region_name": region_name or os.environ.get("AWS_REGION", "us-east-1"),
    }
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint
        client_kwargs["config"] = BotoConfig(s3={"addressing_style": "path"})

    client = boto3.client("s3", **client_kwargs)
    client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    return {
        "archive_uri": f"s3://{bucket}/{key}",
        "bucket": bucket,
        "key": key,
        "endpoint_url": endpoint or "",
        "bytes_written": len(body),
        "sha256": sha256,
        "content_type": content_type,
    }


def build_local_standard_source_extractor(
    sidecar_dir: str | Path,
    *,
    max_anchor_count: int = 200,
):
    """Build a lightweight local extractor that writes citation-anchor sidecars.

    The extractor handles plain text, JSON, CSV, UTF-8-readable files, and
    dependency-free DOCX text extraction. PDF and legacy DOC parsing stay
    outside MMFE core; unsupported binaries record a structured
    ``unsupported_fulltext_format`` status.
    """
    output_root = Path(sidecar_dir)

    def extractor(task: dict, body: bytes, archive: dict) -> dict[str, Any]:
        output_root.mkdir(parents=True, exist_ok=True)
        archive_uri = str(archive.get("archive_uri") or "")
        source_path = str(archive.get("local_path") or task.get("local_path") or "")
        text = _decode_standard_source_body(body, source_path=source_path)
        anchors = _extract_citation_anchors_from_text(
            task,
            text,
            max_anchor_count=max_anchor_count,
        ) if text else []
        status = "extracted" if anchors else ("unsupported_fulltext_format" if body else "empty_fulltext")
        sidecar = build_standard_source_citation_anchor_sidecar(
            task,
            anchors=anchors,
            archive_uri=archive_uri,
            source_path=source_path,
            checksum_sha256=str(archive.get("sha256") or ""),
            extraction_status=status,
            extraction_method="local_text_clause_anchor_extractor",
        )
        sidecar_path = output_root / f"{_safe_filename(task.get('standard_identifier') or task.get('task_id') or 'standard-source')}.citation_anchors.json"
        write_standard_source_citation_anchor_sidecar(sidecar, sidecar_path)
        return {
            "extraction_status": status,
            "citation_anchor_count": len(anchors),
            "anchors": anchors,
            "sidecar_path": str(sidecar_path),
            "sidecar_schema": STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA,
            "extraction_method": "local_text_clause_anchor_extractor",
        }

    return extractor


def build_standard_source_citation_anchor_sidecar(
    task: dict,
    *,
    anchors: list[dict],
    archive_uri: str = "",
    source_path: str = "",
    checksum_sha256: str = "",
    extraction_status: str = "extracted",
    extraction_method: str = "external_extractor",
    timestamp: str | None = None,
) -> dict:
    """Build the citation-anchor sidecar emitted by standard-source extraction."""
    normalized_anchors = [
        _normalize_citation_anchor(anchor, index + 1, task)
        for index, anchor in enumerate(anchors)
        if isinstance(anchor, dict)
    ]
    return {
        "schema": STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "task_id": task.get("task_id") or "",
        "standard_identifier": task.get("standard_identifier") or "",
        "source_name": task.get("source_name") or "",
        "archive_uri": archive_uri,
        "source_path": source_path,
        "checksum_sha256": checksum_sha256,
        "extraction_status": extraction_status,
        "extraction_method": extraction_method,
        "citation_anchor_count": len(normalized_anchors),
        "anchors": normalized_anchors,
    }


def validate_standard_source_citation_anchor_sidecar(payload: dict) -> dict:
    """Validate the standard-source citation-anchor sidecar contract."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA:
        errors.append(f"schema must be {STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA}")
    if not payload.get("standard_identifier"):
        errors.append("standard_identifier is required")
    anchors = payload.get("anchors")
    if not isinstance(anchors, list):
        errors.append("anchors must be a list")
    else:
        for index, anchor in enumerate(anchors):
            if not isinstance(anchor, dict):
                errors.append(f"anchors[{index}] must be an object")
                continue
            if not anchor.get("anchor_id"):
                errors.append(f"anchors[{index}].anchor_id is required")
            if not anchor.get("citation"):
                errors.append(f"anchors[{index}].citation is required")
    if _safe_int(payload.get("citation_anchor_count"), -1) != len(anchors or []):
        errors.append("citation_anchor_count must equal anchors length")
    return {"valid": not errors, "errors": errors}


def write_standard_source_citation_anchor_sidecar(sidecar: dict, output_path: str | Path) -> str:
    """Write a validated citation-anchor sidecar to JSON."""
    validation = validate_standard_source_citation_anchor_sidecar(sidecar)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2, sort_keys=True)
    return str(path)


def _source_documents(role_contracts: dict[str, Any]) -> list[str]:
    docs: list[str] = []
    top_docs = role_contracts.get("source_documents") if isinstance(role_contracts, dict) else None
    if isinstance(top_docs, list):
        docs.extend(str(item) for item in top_docs if item)
    for role in (role_contracts.get("roles") or {}).values():
        if not isinstance(role, dict):
            continue
        docs.extend(str(item) for item in role.get("source_documents") or [] if item)
    seen = set()
    ordered = []
    for doc in docs:
        if doc not in seen:
            ordered.append(doc)
            seen.add(doc)
    return ordered


def _build_ingestion_task(entry: dict, index: int) -> dict:
    retrieval_status = str(entry.get("retrieval_status") or "")
    has_official_source = bool(entry.get("official_url")) or retrieval_status.startswith("official_")
    has_fulltext = retrieval_status in {"official_fulltext_available", "downloaded_fulltext"}
    can_download = bool(entry.get("can_download"))
    local_path = str(entry.get("local_path") or "")
    checksum = str(entry.get("checksum_sha256") or entry.get("sha256") or "")
    extraction_status = str(entry.get("extraction_status") or "")
    extraction_ready = extraction_status in {"extracted", "not_required"} or bool(entry.get("clause_anchor_count"))
    blocking_reasons = []
    if not has_official_source:
        blocking_reasons.append("official_source_missing")
    if has_fulltext and can_download and not checksum and not local_path:
        blocking_reasons.append("checksum_missing")
    if has_fulltext and not extraction_ready:
        blocking_reasons.append("fulltext_extraction_missing")
    if entry.get("not_for_production_gap"):
        blocking_reasons.append("production_gap")

    return {
        "task_id": f"standard-source-ingest-{index + 1}",
        "standard_identifier": entry.get("standard_identifier") or "",
        "source_name": entry.get("source_name") or entry.get("title_zh") or "",
        "title_zh": entry.get("title_zh") or "",
        "authority": entry.get("authority") or "",
        "official_platform": entry.get("official_platform") or "",
        "official_url": entry.get("official_url") or "",
        "search_url": entry.get("search_url") or "",
        "retrieval_status": retrieval_status,
        "access_mode": entry.get("access_mode") or "",
        "required_actions": _required_ingestion_actions(
            has_official_source=has_official_source,
            has_fulltext=has_fulltext,
            can_download=can_download,
            has_checksum=bool(checksum or local_path),
            extraction_ready=extraction_ready,
        ),
        "download_required": has_fulltext and can_download and not local_path,
        "checksum_sha256": checksum,
        "local_path": local_path,
        "extraction_status": extraction_status or ("pending" if has_fulltext else "not_started"),
        "blocking_reasons": blocking_reasons,
        "status": "ready" if not blocking_reasons else "blocked",
    }


def _required_ingestion_actions(
    *,
    has_official_source: bool,
    has_fulltext: bool,
    can_download: bool,
    has_checksum: bool,
    extraction_ready: bool,
) -> list[str]:
    actions = []
    if not has_official_source:
        actions.append("find_and_verify_official_source")
    if has_official_source and has_fulltext and can_download and not has_checksum:
        actions.append("download_or_archive_fulltext_and_record_checksum")
    if has_official_source and has_fulltext and not extraction_ready:
        actions.append("extract_clauses_fields_value_domains_and_citation_anchors")
    if has_official_source and not has_fulltext:
        actions.append("record_access_constraints_or_request_authorized_fulltext")
    return actions


def _run_standard_source_ingestion_task(
    task: dict,
    *,
    fetcher=None,
    archiver=None,
    extractor=None,
) -> dict:
    errors: list[str] = []
    fetched: dict[str, Any] = {}
    archived: dict[str, Any] = {}
    extracted: dict[str, Any] = {}
    body = b""
    task_context = dict(task)

    if "find_and_verify_official_source" in task.get("required_actions", []):
        errors.append("official source verification requires a standards-platform resolver")

    if task.get("download_required"):
        if fetcher is None:
            errors.append("fetcher is required for download_required task")
        else:
            try:
                fetched = _normalise_adapter_result(fetcher(task))
                body = _body_bytes(fetched.get("body"))
                for key in ["local_path", "source_path", "content_type"]:
                    if fetched.get(key) and not task_context.get(key):
                        task_context[key] = fetched[key]
            except Exception as exc:
                errors.append(f"fetcher failed: {exc}")

        if body and archiver is not None:
            try:
                archived = _normalise_adapter_result(archiver(task_context, body))
            except Exception as exc:
                errors.append(f"archiver failed: {exc}")
        elif body and archiver is None:
            archived = {"bytes_written": len(body)}

    checksum = task.get("checksum_sha256") or fetched.get("sha256") or archived.get("sha256")
    if body and not checksum:
        checksum = hashlib.sha256(body).hexdigest()

    if "extract_clauses_fields_value_domains_and_citation_anchors" in task.get("required_actions", []):
        if extractor is None:
            errors.append("extractor is required for fulltext extraction task")
        elif body or archived.get("archive_uri") or task_context.get("local_path"):
            try:
                extracted = _normalise_adapter_result(extractor(task_context, body, archived))
            except Exception as exc:
                errors.append(f"extractor failed: {exc}")
        else:
            errors.append("extractor requires fetched body, archive_uri, or local_path")

    extraction_required = (
        "extract_clauses_fields_value_domains_and_citation_anchors"
        in task.get("required_actions", [])
    )
    extraction_status = extracted.get("extraction_status") or ("extracted" if extracted else task.get("extraction_status"))
    citation_anchor_count = _safe_int(extracted.get("citation_anchor_count"), 0)
    if extraction_required and extracted and extraction_status not in {"extracted", "not_required"}:
        errors.append(f"extractor did not complete extraction: {extraction_status}")
    valid = not errors
    return {
        "task_id": task.get("task_id"),
        "standard_identifier": task.get("standard_identifier"),
        "valid": valid,
        "status": "ingested" if valid else "error",
        "errors": errors,
        "official_url": task.get("official_url", ""),
        "archive_uri": archived.get("archive_uri") or fetched.get("archive_uri") or "",
        "local_path": archived.get("local_path") or fetched.get("local_path") or task.get("local_path") or "",
        "bytes_fetched": _safe_int(fetched.get("bytes_fetched"), len(body)),
        "bytes_archived": _safe_int(archived.get("bytes_written"), 0),
        "checksum_sha256": checksum or "",
        "extraction_status": extraction_status or "",
        "citation_anchor_count": citation_anchor_count,
        "extraction_result": extracted,
    }


def _standard_source_ingestion_run_result(
    plan: dict,
    task_results: list[dict],
    errors: list[dict],
    *,
    timestamp: str | None = None,
) -> dict:
    return {
        "schema": STANDARD_SOURCE_INGESTION_RUN_SCHEMA,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "plan_schema": plan.get("schema", ""),
        "task_count": len(plan.get("tasks") or []),
        "valid": not errors,
        "errors": errors,
        "summary": {
            "ingested_task_count": sum(1 for item in task_results if item.get("valid")),
            "failed_task_count": sum(1 for item in task_results if not item.get("valid")),
            "checksum_recorded_count": sum(1 for item in task_results if item.get("checksum_sha256")),
            "extracted_task_count": sum(1 for item in task_results if item.get("extraction_status") == "extracted"),
            "citation_anchor_count": sum(_safe_int(item.get("citation_anchor_count"), 0) for item in task_results),
        },
        "task_results": task_results,
    }


def _apply_ingestion_result_to_entry(entry: dict, result: dict) -> None:
    if result.get("archive_uri"):
        entry["archive_uri"] = result["archive_uri"]
        entry["access_mode"] = "archived_fulltext"
        entry["retrieval_status"] = "downloaded_fulltext"
        entry["retrieval_method"] = "mmfe_standard_source_ingestion_run"
    if result.get("local_path"):
        entry["local_path"] = result["local_path"]
    if result.get("checksum_sha256"):
        entry["checksum_sha256"] = result["checksum_sha256"]
    if result.get("bytes_archived"):
        entry["archived_bytes"] = _safe_int(result.get("bytes_archived"), 0)
    elif result.get("bytes_fetched"):
        entry["archived_bytes"] = _safe_int(result.get("bytes_fetched"), 0)
    if result.get("bytes_fetched"):
        entry["bytes_fetched"] = _safe_int(result.get("bytes_fetched"), 0)
    if result.get("extraction_status"):
        entry["extraction_status"] = result["extraction_status"]
    citation_anchor_count = _safe_int(result.get("citation_anchor_count"), 0)
    if citation_anchor_count:
        entry["citation_anchor_count"] = citation_anchor_count
        entry["clause_anchor_count"] = citation_anchor_count
    extraction_result = result.get("extraction_result") or {}
    if isinstance(extraction_result, dict):
        if extraction_result.get("sidecar_path"):
            entry["citation_anchor_sidecar_path"] = extraction_result["sidecar_path"]
        if extraction_result.get("sidecar_schema"):
            entry["citation_anchor_sidecar_schema"] = extraction_result["sidecar_schema"]
        if extraction_result.get("extraction_method"):
            entry["extraction_method"] = extraction_result["extraction_method"]
    if result.get("valid"):
        entry["not_for_production_gap"] = bool(
            entry.get("not_for_production_gap")
            and not (
                entry.get("official_url")
                and entry.get("checksum_sha256")
                and entry.get("extraction_status") == "extracted"
            )
        )


def _normalise_adapter_result(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _body_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return b""


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_local_standard_source_path(
    task: dict,
    *,
    source_root: str | Path | None = None,
    sources_by_identifier: dict[str, str | Path] | None = None,
    sources_by_task_id: dict[str, str | Path] | None = None,
) -> str:
    task_id = str(task.get("task_id") or "")
    identifier = str(task.get("standard_identifier") or "")
    if sources_by_task_id and task_id in sources_by_task_id:
        return str(sources_by_task_id[task_id])
    if sources_by_identifier and identifier in sources_by_identifier:
        return str(sources_by_identifier[identifier])
    if task.get("local_path"):
        return str(task.get("local_path"))
    if not source_root:
        return ""
    root = Path(source_root)
    if not root.exists():
        return ""
    needles = [
        _safe_filename(identifier),
        _safe_filename(task.get("source_name") or ""),
        _safe_filename(task.get("title_zh") or ""),
    ]
    candidates = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        haystack = _safe_filename(path.stem)
        if any(needle and (needle in haystack or haystack in needle) for needle in needles):
            candidates.append(path)
    if not candidates:
        return ""
    return str(sorted(candidates)[0])


def _archive_filename(task: dict, body: bytes) -> str:
    identifier = task.get("standard_identifier") or task.get("task_id") or "standard-source"
    source_path = str(task.get("source_path") or task.get("local_path") or "")
    suffix = Path(source_path).suffix if source_path else ""
    if not suffix:
        suffix = _suffix_from_content_type(str(task.get("content_type") or "")) or ".bin"
    digest = hashlib.sha256(body).hexdigest()[:12]
    return f"{_safe_filename(identifier)}-{digest}{suffix.lower()}"


def _safe_filename(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = (
        text.replace("/", "-")
        .replace("\\", "-")
        .replace(" ", "-")
        .replace("“", "")
        .replace("”", "")
        .replace("（", "-")
        .replace("）", "")
        .replace("(", "-")
        .replace(")", "")
    )
    text = re.sub(r"[^0-9a-zA-Z._\-\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-._")
    return text or "standard-source"


def _join_uri_prefix(uri_prefix: str | None, filename: str) -> str:
    prefix = str(uri_prefix or "")
    if not prefix:
        return filename
    return f"{prefix.rstrip('/')}/{filename}"


def _s3_target_prefix(target_uri_prefix: str) -> tuple[str, str]:
    if not str(target_uri_prefix or "").startswith("s3://"):
        raise ValueError("target_uri_prefix must start with s3://")
    rest = str(target_uri_prefix)[5:]
    bucket, _, key_prefix = rest.partition("/")
    if not bucket:
        raise ValueError("target_uri_prefix bucket is required")
    return bucket, key_prefix.strip("/")


def _domain_allowed(host: str, allowed_domains: set[str]) -> bool:
    normalized = str(host or "").lower()
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in allowed_domains)


def _response_content_type(headers: Any) -> str:
    if hasattr(headers, "get_content_type"):
        return str(headers.get_content_type() or "")
    if hasattr(headers, "get"):
        content_type = headers.get("Content-Type") or headers.get("content-type")
        if content_type:
            return str(content_type).split(";", 1)[0].strip()
    return ""


def _guess_source_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".docx", ".doc"}:
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == ".json":
        return "application/json"
    if suffix == ".csv":
        return "text/csv"
    if suffix in {".txt", ".md"}:
        return "text/plain"
    content_type, _ = mimetypes.guess_type(str(path))
    return content_type or "application/octet-stream"


def _suffix_from_content_type(content_type: str) -> str:
    if content_type == "application/pdf":
        return ".pdf"
    if content_type == "application/json":
        return ".json"
    if content_type == "text/csv":
        return ".csv"
    if content_type == "text/plain":
        return ".txt"
    return ""


def _decode_standard_source_body(body: bytes, *, source_path: str = "") -> str:
    if not body and source_path:
        path = Path(source_path)
        if path.exists() and path.is_file():
            body = path.read_bytes()
    if not body:
        return ""
    suffix = Path(source_path).suffix.lower() if source_path else ""
    if suffix == ".docx":
        return _extract_docx_text(body)
    if suffix in {".pdf", ".doc"}:
        return ""
    for encoding in ["utf-8", "utf-8-sig", "gb18030"]:
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def _extract_docx_text(body: bytes) -> str:
    try:
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(body)) as archive:
            document_xml = archive.read("word/document.xml")
    except Exception:
        return ""
    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError:
        return ""
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines = []
    for paragraph in root.iter(f"{namespace}p"):
        parts = [
            node.text or ""
            for node in paragraph.iter(f"{namespace}t")
            if node.text
        ]
        text = "".join(parts).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _extract_citation_anchors_from_text(
    task: dict,
    text: str,
    *,
    max_anchor_count: int,
) -> list[dict]:
    standard_identifier = str(task.get("standard_identifier") or "")
    source_name = str(task.get("source_name") or task.get("title_zh") or standard_identifier)
    lines = [line.strip() for line in text.splitlines()]
    anchors = []
    for line_number, line in enumerate(lines, start=1):
        if len(anchors) >= max_anchor_count:
            break
        if not line:
            continue
        clause = _clause_label(line)
        if not clause and len(line) < 12:
            continue
        anchor_index = len(anchors) + 1
        citation = _citation_text(standard_identifier, clause, anchor_index)
        anchors.append({
            "anchor_id": f"{_safe_filename(standard_identifier or source_name)}-{anchor_index}",
            "citation": citation,
            "standard_identifier": standard_identifier,
            "source_name": source_name,
            "clause": clause,
            "line_number": line_number,
            "text": line[:500],
        })
    return anchors


def _clause_label(line: str) -> str:
    match = re.match(r"^\s*(第[一二三四五六七八九十百千0-9]+[章节条款]|[0-9]+(?:\.[0-9]+){0,5})", line)
    return match.group(1) if match else ""


def _citation_text(standard_identifier: str, clause: str, anchor_index: int) -> str:
    base = standard_identifier or "standard-source"
    if clause:
        return f"{base} §{clause}"
    return f"{base} anchor {anchor_index}"


def _normalize_citation_anchor(anchor: dict, index: int, task: dict) -> dict:
    standard_identifier = str(
        anchor.get("standard_identifier") or task.get("standard_identifier") or ""
    )
    source_name = str(anchor.get("source_name") or task.get("source_name") or "")
    anchor_id = str(anchor.get("anchor_id") or f"{_safe_filename(standard_identifier)}-{index}")
    normalized = {
        "anchor_id": anchor_id,
        "citation": str(anchor.get("citation") or _citation_text(standard_identifier, "", index)),
        "standard_identifier": standard_identifier,
        "source_name": source_name,
        "clause": str(anchor.get("clause") or ""),
        "text": str(anchor.get("text") or "")[:500],
    }
    if anchor.get("line_number") is not None:
        normalized["line_number"] = _safe_int(anchor.get("line_number"), 0)
    if anchor.get("page") is not None:
        normalized["page"] = _safe_int(anchor.get("page"), 0)
    if anchor.get("field_name"):
        normalized["field_name"] = str(anchor.get("field_name"))
    if anchor.get("value_domain"):
        normalized["value_domain"] = str(anchor.get("value_domain"))
    return normalized


def _build_source_entry(doc_name: str, standards_dir: str | Path | None = None) -> dict:
    if doc_name in OFFICIAL_STANDARD_OVERRIDES:
        base = dict(OFFICIAL_STANDARD_OVERRIDES[doc_name])
    else:
        base = dict(NATURAL_RESOURCE_ONE_MAP_DOC_HINTS.get(doc_name, {}))
    if not base:
        base = {
            "standard_identifier": _fallback_identifier(doc_name),
            "title_zh": doc_name,
            "authority": "待核验",
            "official_platform": "待核验",
            "retrieval_status": "official_source_pending",
            "access_mode": "unknown",
            "retrieval_method": "source_document_name_only",
            "used_for": [],
            "evidence_note_zh": "仅从角色契约 source_documents 字段发现，尚未核验官方来源。",
        }
    local_path = _find_local_source_path(doc_name, standards_dir)
    if local_path and not base.get("local_path"):
        base["local_path"] = local_path
    base.setdefault("title_zh", doc_name)
    base.setdefault("standard_identifier", _fallback_identifier(doc_name))
    base.setdefault("official_url", "")
    base.setdefault("search_url", "")
    base.setdefault("title_en", "")
    base.setdefault("standard_type", "")
    base.setdefault("status", "")
    base.setdefault("publication_date", "")
    base.setdefault("implementation_date", "")
    base.setdefault("ccs", "")
    base.setdefault("ics", "")
    base.setdefault("department", "")
    base.setdefault("technical_committee", "")
    base.setdefault("publisher", "")
    base.setdefault("hcno", "")
    base.setdefault("can_download", False)
    base.setdefault("can_online_preview", False)
    base.setdefault("not_for_production_gap", base.get("retrieval_status") != "official_fulltext_available")
    base["source_name"] = doc_name
    return base


def _find_local_source_path(doc_name: str, standards_dir: str | Path | None) -> str:
    if not standards_dir:
        return ""
    root = Path(standards_dir)
    if not root.exists():
        return ""
    candidates = [
        path
        for path in root.rglob("*")
        if path.is_file() and doc_name.replace(" ", "") in path.stem.replace(" ", "")
    ]
    if not candidates:
        return ""
    return str(sorted(candidates)[0])


def _fallback_identifier(doc_name: str) -> str:
    return (
        doc_name.upper()
        .replace("“", "")
        .replace("”", "")
        .replace("（", "-")
        .replace("）", "")
        .replace("(", "-")
        .replace(")", "")
        .replace(" ", "-")
    )


def _jsonish(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)

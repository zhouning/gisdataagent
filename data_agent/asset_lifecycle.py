"""Evidence-based lifecycle view for catalog assets.

This module is deliberately read-only. It projects existing catalog, quality,
usage, review, version, request, and lineage facts into one operational view;
it does not create a second metadata authority or infer state with an LLM.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text

from .db_engine import get_engine
from .i18n import t
from .observability import get_logger

logger = get_logger("asset_lifecycle")


class AssetLifecycleRepositoryError(RuntimeError):
    """Raised when the authoritative catalog cannot be queried."""


_STAGE_LABEL_KEYS = {
    "discovered": "asset.stage.discovered",
    "documented": "asset.stage.documented",
    "governed": "asset.stage.governed",
    "published": "asset.stage.published",
    "operating": "asset.stage.operating",
    "retired": "asset.stage.retired",
}
_STAGE_ORDER = tuple(_STAGE_LABEL_KEYS)


def _stage_label(stage_id: str) -> str:
    return t(_STAGE_LABEL_KEYS[stage_id])


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return []
    return []


def _path(source: dict[str, Any], *keys: str) -> Any:
    value: Any = source
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first_value(source: dict[str, Any], paths: Iterable[tuple[str, ...]]) -> Any:
    for candidate in paths:
        value = _path(source, *candidate)
        if _has_value(value):
            return value
    return None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "shared", "public"}
    return bool(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _display_value(value: Any) -> str | None:
    if not _has_value(value):
        return None
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("id", "name", "code", "value", "status"):
            if _has_value(value.get(key)):
                return str(value[key]).strip()
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _readiness_check(
    check_id: str,
    label: str,
    passed: bool,
    weight: int,
    missing_message: str,
    *,
    evidence: str = "",
    blocking: bool = True,
    applicable: bool = True,
) -> dict[str, Any]:
    if not applicable:
        return {
            "id": check_id,
            "label": label,
            "status": "not_applicable",
            "blocking": False,
            "weight": weight,
            "earned": weight,
            "message": t("asset.readiness.not_applicable"),
        }
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else ("missing" if blocking else "warning"),
        "blocking": blocking and not passed,
        "weight": weight,
        "earned": weight if passed else 0,
        "message": evidence if passed else missing_message,
    }


def calculate_asset_lifecycle(
    asset: dict[str, Any],
    *,
    quality: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    reviews: dict[str, Any] | None = None,
    versions: list[dict[str, Any]] | None = None,
    lineage: dict[str, Any] | None = None,
    distribution_requests: dict[str, int] | None = None,
    request_access: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate lifecycle stage and publication readiness from explicit facts."""
    technical = _json_object(asset.get("technical") or asset.get("technical_metadata"))
    business = _json_object(asset.get("business") or asset.get("business_metadata"))
    operational = _json_object(asset.get("operational") or asset.get("operational_metadata"))
    lineage_meta = _json_object(asset.get("lineage_metadata") or asset.get("lineage"))

    storage = _json_object(technical.get("storage"))
    spatial = _json_object(technical.get("spatial"))
    structure = _json_object(technical.get("structure"))
    semantic = _json_object(business.get("semantic"))
    classification = _json_object(business.get("classification"))
    version_meta = _json_object(operational.get("version"))

    asset_name = str(asset.get("asset_name") or asset.get("name") or "")
    display_name = str(asset.get("display_name") or asset_name)
    asset_type = str(
        asset.get("asset_type") or classification.get("category") or "other"
    )
    description = str(
        asset.get("description")
        or semantic.get("description")
        or business.get("description")
        or ""
    ).strip()
    owner = str(
        asset.get("owner_username") or asset.get("owner") or asset.get("owner_user") or ""
    ).strip()
    crs = str(asset.get("crs") or spatial.get("crs") or "").strip()
    extent = asset.get("spatial_extent") or spatial.get("extent")
    tags = (
        asset.get("tags")
        if asset.get("tags") is not None
        else semantic.get("keywords", business.get("keywords"))
    )
    tags = _json_list(tags) if not isinstance(tags, list) else tags
    shared = _as_bool(asset.get("is_shared", asset.get("shared", False)))
    access_level = str(asset.get("access_level") or "private").strip().lower()

    sensitivity = _display_value(_first_value(
        business,
        (
            ("governance", "sensitivity_level"),
            ("governance", "classification"),
            ("classification", "sensitivity_level"),
            ("classification", "sensitivity"),
            ("sensitivity_level",),
        ),
    ))
    license_value = _display_value(_first_value(
        business,
        (
            ("governance", "license_id"),
            ("governance", "license"),
            ("governance", "usage_authorization"),
            ("governance", "usage_rights"),
            ("usage", "license_id"),
            ("usage", "license"),
            ("usage", "authorization"),
            ("usage", "rights"),
            ("license_id",),
            ("license",),
        ),
    ))

    quality = quality or {}
    quality_score = _as_float(quality.get("score"))
    has_quality_evidence = quality_score is not None
    quality_view = {
        "has_evidence": has_quality_evidence,
        "score": quality_score,
        "issues_count": _as_int(quality.get("issues_count")),
        "standard_id": quality.get("standard_id"),
        "dimension_scores": _json_object(quality.get("dimension_scores")),
        "assessed_at": _iso(quality.get("created_at") or quality.get("assessed_at")),
        "run_by": quality.get("run_by"),
    }

    usage = usage or {}
    total_accesses = _as_int(usage.get("total_accesses") or usage.get("total"))
    usage_view = {
        "total_accesses": total_accesses,
        "unique_users": _as_int(usage.get("unique_users")),
        "last_accessed_at": _iso(usage.get("last_accessed_at")),
    }

    reviews = reviews or {}
    review_view = {
        "avg_rating": round(_as_float(reviews.get("avg_rating")) or 0.0, 1),
        "count": _as_int(reviews.get("count")),
    }

    versions = versions or []
    current_version = asset.get("version") or version_meta.get("version") or 1
    version_items = [
        {
            "version": item.get("version"),
            "change_summary": item.get("change_summary") or "",
            "created_by": item.get("created_by"),
            "created_at": _iso(item.get("created_at")),
            "file_size_bytes": _as_int(item.get("file_size_bytes")),
            "feature_count": _as_int(item.get("feature_count")),
        }
        for item in versions
    ]

    lineage = lineage or {}
    ancestors = lineage.get("ancestors") if isinstance(lineage.get("ancestors"), list) else []
    descendants = (
        lineage.get("descendants") if isinstance(lineage.get("descendants"), list) else []
    )
    upstream_meta = _json_object(lineage_meta.get("upstream"))
    metadata_sources = _json_list(upstream_meta.get("asset_ids"))
    has_lineage = bool(ancestors or descendants or metadata_sources)
    lineage_view = {
        "asset": lineage.get("asset") or {
            "id": asset.get("id"),
            "name": asset_name,
            "type": asset_type,
        },
        "ancestors": ancestors,
        "descendants": descendants,
        "has_evidence": has_lineage,
        "source_count": max(len(ancestors), len(metadata_sources)),
        "derived_count": len(descendants),
    }

    spatial_asset = asset_type.lower() in {"vector", "raster", "map", "tiles", "3d"} or bool(
        extent
    )
    checks = [
        _readiness_check(
            "responsible_owner", t("asset.readiness.owner_label"), bool(owner), 15,
            t("asset.readiness.owner_missing"),
            evidence=owner,
        ),
        _readiness_check(
            "description", t("asset.readiness.description_label"), bool(description), 15,
            t("asset.readiness.description_missing"),
            evidence=t("asset.readiness.description_present"),
        ),
        _readiness_check(
            "classification", t("asset.readiness.classification_label"),
            bool(asset_type and asset_type != "other"), 10,
            t("asset.readiness.classification_missing"), evidence=asset_type,
        ),
        _readiness_check(
            "spatial_reference", t("asset.readiness.spatial_reference_label"), bool(crs), 10,
            t("asset.readiness.spatial_reference_missing"),
            evidence=crs, applicable=spatial_asset,
        ),
        _readiness_check(
            "sensitivity", t("asset.readiness.sensitivity_label"), _has_value(sensitivity), 10,
            t("asset.readiness.sensitivity_missing"),
            evidence=str(sensitivity or ""),
        ),
        _readiness_check(
            "quality_evidence", t("asset.readiness.quality_label"), has_quality_evidence, 15,
            t("asset.readiness.quality_missing"),
            evidence=(
                t("asset.readiness.quality_score", score=quality_score)
                if quality_score is not None
                else ""
            ),
        ),
        _readiness_check(
            "usage_authorization", t("asset.readiness.usage_label"), _has_value(license_value), 15,
            t("asset.readiness.usage_missing"), evidence=str(license_value or ""),
        ),
        _readiness_check(
            "lineage_evidence", t("asset.readiness.lineage_label"), has_lineage, 10,
            t("asset.readiness.lineage_missing"),
            evidence=(
                t(
                    "asset.readiness.lineage_counts",
                    upstream=lineage_view["source_count"],
                    downstream=lineage_view["derived_count"],
                )
            ),
            blocking=False,
        ),
    ]
    blockers = [check["message"] for check in checks if check["blocking"]]
    warnings = [check["message"] for check in checks if check["status"] == "warning"]
    readiness_score = sum(_as_int(check["earned"]) for check in checks)

    publication_evidence: list[str] = []
    if shared:
        publication_evidence.append(t("asset.publication.shared"))
    if access_level in {"shared", "public", "published"}:
        publication_evidence.append(t("asset.publication.access_level", level=access_level))
    publication_status = str(_path(operational, "publication", "status") or "").lower()
    if publication_status in {"published", "active"}:
        publication_evidence.append(t("asset.publication.status", status=publication_status))
    endpoint = _first_value(
        operational,
        (
            ("publication", "service_endpoint"),
            ("publication", "endpoint"),
            ("distribution", "service_endpoint"),
            ("distribution", "endpoint"),
        ),
    )
    if endpoint:
        publication_evidence.append(t("asset.publication.endpoint"))
    data_product_urn = _display_value(
        _first_value(
            operational,
            (
                ("publication", "data_product_urn"),
                ("distribution", "data_product_urn"),
            ),
        )
    )
    if data_product_urn:
        publication_evidence.append(t("asset.publication.data_product"))

    lifecycle_status = str(
        _path(operational, "lifecycle", "status")
        or operational.get("status")
        or ""
    ).lower()
    retired = lifecycle_status in {"retired", "archived", "deprecated"}
    documented = bool(description and asset_type and asset_type != "other")
    governed = not blockers
    published = bool(publication_evidence)
    operating = published and total_accesses > 0

    achieved = {
        "discovered": True,
        "documented": documented,
        "governed": governed,
        "published": published,
        "operating": operating,
        "retired": retired,
    }
    if retired:
        current_stage = "retired"
    elif operating:
        current_stage = "operating"
    elif published:
        current_stage = "published"
    elif governed:
        current_stage = "governed"
    elif documented:
        current_stage = "documented"
    else:
        current_stage = "discovered"

    current_index = _STAGE_ORDER.index(current_stage)
    stages = []
    for index, stage_id in enumerate(_STAGE_ORDER):
        if stage_id == current_stage:
            status = "current"
        elif achieved[stage_id]:
            status = "complete"
        elif index < current_index:
            status = "attention"
        else:
            status = "pending"
        stages.append({
            "id": stage_id,
            "label": _stage_label(stage_id),
            "status": status,
            "achieved": achieved[stage_id],
        })

    return {
        "status": "success",
        "asset": {
            "id": asset.get("id"),
            "asset_code": asset.get("asset_code"),
            "asset_name": asset_name,
            "display_name": display_name,
            "asset_type": asset_type,
            "description": description,
            "tags": tags,
            "owner": owner,
            "is_shared": shared,
            "access_level": access_level,
            "sensitivity_level": sensitivity,
            "license": license_value,
            "file_format": asset.get("file_format") or storage.get("format"),
            "storage_backend": asset.get("storage_backend") or storage.get("backend"),
            "crs": crs,
            "spatial_extent": extent,
            "feature_count": _as_int(
                asset.get("feature_count") or structure.get("feature_count")
            ),
            "file_size_bytes": _as_int(asset.get("file_size_bytes") or storage.get("size_bytes")),
            "column_schema": (
                structure.get("columns")
                if isinstance(structure.get("columns"), list)
                else []
            ),
            "version": current_version,
            "created_at": _iso(asset.get("created_at") or asset.get("created")),
            "updated_at": _iso(asset.get("updated_at") or asset.get("updated")),
        },
        "current_stage": current_stage,
        "current_stage_label": _stage_label(current_stage),
        "stages": stages,
        "readiness": {
            "score": readiness_score,
            "ready": not blockers,
            "checks": checks,
            "blockers": blockers,
            "warnings": warnings,
        },
        "publication": {
            "evidence_detected": published,
            "evidence": publication_evidence,
            "status": publication_status or ("shared" if shared else "not_published"),
            "data_product_urn": data_product_urn,
        },
        "quality": quality_view,
        "usage": usage_view,
        "reviews": review_view,
        "versions": {
            "current": current_version,
            "history_count": len(version_items),
            "items": version_items,
        },
        "lineage": lineage_view,
        "distribution_requests": distribution_requests or {},
        "request_access": request_access or {
            "is_owner": False,
            "can_request": False,
            "can_package": False,
            "my_request": None,
            "active_grant": None,
        },
    }


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return dict(mapping)
    if isinstance(row, dict):
        return dict(row)
    return {}


def _optional_row(engine: Any, statement: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        with engine.connect() as conn:
            return _row_dict(conn.execute(text(statement), params).fetchone())
    except Exception as exc:
        logger.debug("Optional lifecycle evidence unavailable: %s", exc)
        return {}


def _optional_rows(engine: Any, statement: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        with engine.connect() as conn:
            return [
                _row_dict(row)
                for row in conn.execute(text(statement), params).fetchall()
            ]
    except Exception as exc:
        logger.debug("Optional lifecycle evidence unavailable: %s", exc)
        return []


def _request_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    expires_at = item.get("expires_at")
    grant_status = "none"
    if str(item.get("status") or "") == "approved":
        if item.get("revoked_at"):
            grant_status = "revoked"
        else:
            grant_status = "expired"
            try:
                expiry = expires_at
                if isinstance(expiry, str):
                    expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                if isinstance(expiry, datetime):
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=UTC)
                    if expiry > datetime.now(UTC):
                        grant_status = "active"
            except (TypeError, ValueError):
                pass

    product_version = None
    if item.get("data_product_version_id"):
        product_version = {
            "tenant_id": str(item.get("product_tenant_id") or ""),
            "product_urn": str(item.get("product_urn") or ""),
            "data_product_version_id": str(item.get("data_product_version_id")),
            "version_key": str(item.get("data_product_version_key") or ""),
        }

    requested_package_quota = _as_int(item.get("requested_package_quota"), 5)
    granted_package_quota = _as_int(
        item.get("granted_package_quota"),
        requested_package_quota if str(item.get("status") or "") == "approved" else 0,
    )
    packages_created = _as_int(item.get("packages_created"))
    packages_remaining = max(granted_package_quota - packages_created, 0)

    return {
        "id": _as_int(item.get("id")),
        "status": str(item.get("status") or "pending"),
        "requester": str(item.get("requester") or ""),
        "reason": str(item.get("reason") or ""),
        "approver": str(item.get("approver") or ""),
        "reject_reason": str(item.get("reject_reason") or ""),
        "requested_operations": _json_list(item.get("requested_operations")),
        "requested_duration_days": _as_int(item.get("requested_duration_days"), 30),
        "requested_package_quota": requested_package_quota,
        "granted_operations": _json_list(item.get("granted_operations")),
        "granted_package_quota": granted_package_quota,
        "packages_created": packages_created,
        "packages_remaining": packages_remaining,
        "quota_exhausted": (
            str(item.get("status") or "") == "approved"
            and granted_package_quota > 0
            and packages_remaining == 0
        ),
        "grant_status": grant_status,
        "grant_contract": (
            "data_product_version" if product_version else "asset_compatibility"
        ),
        "product_version": product_version,
        "expires_at": _iso(expires_at),
        "revoked_at": _iso(item.get("revoked_at")),
        "revoked_by": str(item.get("revoked_by") or ""),
        "revocation_reason": str(item.get("revocation_reason") or ""),
        "created_at": _iso(item.get("created_at")),
        "approved_at": _iso(item.get("approved_at")),
    }


def get_asset_lifecycle(asset_id: int) -> dict[str, Any] | None:
    """Load one accessible asset and aggregate its existing lifecycle evidence."""
    engine = get_engine(readonly=True)
    if not engine:
        raise AssetLifecycleRepositoryError("Database not configured")

    try:
        from .data_catalog import _inject_user_context

        with engine.connect() as conn:
            _inject_user_context(conn)
            row = conn.execute(
                text(
                    """
                    SELECT id, asset_name, display_name, owner_username,
                           is_shared, access_level, technical_metadata,
                           business_metadata, operational_metadata,
                           lineage_metadata, created_at, updated_at, asset_code
                    FROM agent_data_assets
                    WHERE id = :asset_id
                    """
                ),
                {"asset_id": asset_id},
            ).fetchone()
    except Exception as exc:
        logger.exception("Catalog asset lifecycle lookup failed")
        raise AssetLifecycleRepositoryError("Catalog unavailable") from exc

    if not row:
        return None

    asset = _row_dict(row)
    params = {"asset_id": asset_id}
    request_engine = get_engine() or engine
    from .user_context import current_user_id, current_user_role

    username = current_user_id.get()
    role = current_user_role.get()
    quality = _optional_row(
        engine,
        """
        SELECT score, dimension_scores, issues_count, standard_id, run_by, created_at
        FROM agent_quality_trends
        WHERE asset_name = :asset_name
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"asset_name": asset.get("asset_name")},
    )
    usage = _optional_row(
        engine,
        """
        SELECT COUNT(*) AS total_accesses,
               COUNT(DISTINCT username) AS unique_users,
               MAX(created_at) AS last_accessed_at
        FROM agent_asset_access_log
        WHERE asset_id = :asset_id
        """,
        params,
    )
    rating = _optional_row(
        engine,
        """
        SELECT AVG(rating) AS avg_rating, COUNT(*) AS count
        FROM agent_asset_reviews
        WHERE asset_id = :asset_id
        """,
        params,
    )
    versions = _optional_rows(
        engine,
        """
        SELECT version, change_summary, created_by, created_at,
               file_size_bytes, feature_count
        FROM agent_asset_versions
        WHERE asset_id = :asset_id
        ORDER BY version DESC
        LIMIT 20
        """,
        params,
    )
    request_rows = _optional_rows(
        request_engine,
        """
        SELECT status, COUNT(*) AS count
        FROM agent_data_requests
        WHERE asset_id = :asset_id
        GROUP BY status
        """,
        params,
    )
    request_counts = {
        str(item.get("status")): _as_int(item.get("count"))
        for item in request_rows
        if item.get("status")
    }
    my_request_rows = _optional_rows(
        request_engine,
        """
        SELECT id, status, requester, reason, approver, reject_reason,
               requested_operations, requested_duration_days,
               requested_package_quota, granted_operations,
               granted_package_quota, expires_at,
               product_tenant_id, product_urn, data_product_version_id,
               data_product_version_key, revoked_at, revoked_by,
               revocation_reason, created_at, approved_at,
               (
                   SELECT COUNT(DISTINCT quota_item.package_id)
                   FROM agent_distribution_package_items quota_item
                   WHERE quota_item.grant_request_id = agent_data_requests.id
               ) AS packages_created
        FROM agent_data_requests
        WHERE asset_id = :asset_id AND requester = :requester
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        {"asset_id": asset_id, "requester": username},
    )
    my_request = _request_item(my_request_rows[0] if my_request_rows else None)
    active_grant_rows = _optional_rows(
        request_engine,
        """
        SELECT id, status, requester, reason, approver, reject_reason,
               requested_operations, requested_duration_days,
               requested_package_quota, granted_operations,
               granted_package_quota, expires_at,
               product_tenant_id, product_urn, data_product_version_id,
               data_product_version_key, revoked_at, revoked_by,
               revocation_reason, created_at, approved_at,
               (
                   SELECT COUNT(DISTINCT quota_item.package_id)
                   FROM agent_distribution_package_items quota_item
                   WHERE quota_item.grant_request_id = agent_data_requests.id
               ) AS packages_created
        FROM agent_data_requests
        WHERE asset_id = :asset_id
          AND requester = :requester
          AND status = 'approved'
          AND revoked_at IS NULL
          AND expires_at > NOW()
          AND granted_operations @> '["download"]'::jsonb
        ORDER BY expires_at DESC, id DESC
        LIMIT 1
        """,
        {"asset_id": asset_id, "requester": username},
    )
    active_grant = _request_item(active_grant_rows[0] if active_grant_rows else None)
    is_owner = str(asset.get("owner_username") or "") == username
    quota_exhausted = bool(active_grant and active_grant["quota_exhausted"])
    request_access: dict[str, Any] = {
        "is_owner": is_owner,
        "can_request": (
            bool(username and username != "anonymous")
            and role != "admin"
            and not is_owner
            and (not active_grant or quota_exhausted)
            and (not my_request or my_request["status"] != "pending")
        ),
        "can_package": (
            role == "admin"
            or is_owner
            or (active_grant is not None and not quota_exhausted)
        ),
        "my_request": my_request,
        "active_grant": active_grant,
    }
    if role == "admin":
        pending_rows = _optional_rows(
            request_engine,
            """
            SELECT id, status, requester, reason, approver, reject_reason,
                   requested_operations, requested_duration_days,
                   requested_package_quota, granted_operations,
                   granted_package_quota, expires_at,
                   product_tenant_id, product_urn, data_product_version_id,
                   data_product_version_key, revoked_at, revoked_by,
                   revocation_reason, created_at, approved_at,
                   (
                       SELECT COUNT(DISTINCT quota_item.package_id)
                       FROM agent_distribution_package_items quota_item
                       WHERE quota_item.grant_request_id = agent_data_requests.id
                   ) AS packages_created
            FROM agent_data_requests
            WHERE asset_id = :asset_id AND status = 'pending'
            ORDER BY created_at ASC, id ASC
            LIMIT 100
            """,
            params,
        )
        request_access["pending_items"] = [
            item
            for item in (_request_item(row) for row in pending_rows)
            if item is not None
        ]
        active_rows = _optional_rows(
            request_engine,
            """
            SELECT id, status, requester, reason, approver, reject_reason,
                   requested_operations, requested_duration_days,
                   requested_package_quota, granted_operations,
                   granted_package_quota, expires_at,
                   product_tenant_id, product_urn, data_product_version_id,
                   data_product_version_key, revoked_at, revoked_by,
                   revocation_reason, created_at, approved_at,
                   (
                       SELECT COUNT(DISTINCT quota_item.package_id)
                       FROM agent_distribution_package_items quota_item
                       WHERE quota_item.grant_request_id = agent_data_requests.id
                   ) AS packages_created
            FROM agent_data_requests
            WHERE asset_id = :asset_id
              AND status = 'approved'
              AND revoked_at IS NULL
              AND expires_at > NOW()
              AND granted_operations @> '["download"]'::jsonb
            ORDER BY expires_at ASC, id ASC
            LIMIT 100
            """,
            params,
        )
        request_access["active_items"] = [
            item
            for item in (_request_item(row) for row in active_rows)
            if item is not None
        ]

    try:
        from .data_catalog import get_data_lineage

        lineage = get_data_lineage(str(asset_id), "both")
        if lineage.get("status") != "success":
            lineage = {}
    except Exception as exc:
        logger.debug("Lineage evidence unavailable: %s", exc)
        lineage = {}

    return calculate_asset_lifecycle(
        asset,
        quality=quality,
        usage=usage,
        reviews=rating,
        versions=versions,
        lineage=lineage,
        distribution_requests=request_counts,
        request_access=request_access,
    )

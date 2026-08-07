"""
Data Distribution — request/approval, packaging, reviews, access tracking (v15.0).

Manages the data sharing lifecycle: request → approve/reject → package → deliver.
Tracks asset access for popularity/heat analytics and user reviews for quality feedback.
"""

import json
import logging
import os
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from .database_tools import _inject_user_context
from .db_engine import get_engine

logger = logging.getLogger(__name__)

T_DATA_REQUESTS = "agent_data_requests"
T_ASSET_REVIEWS = "agent_asset_reviews"
T_ACCESS_LOG = "agent_asset_access_log"
T_DATA_ASSETS = "agent_data_assets"

VALID_REQUEST_STATUS = {"pending", "approved", "rejected"}
DEFAULT_REQUEST_DURATION_DAYS = 30
MAX_REQUEST_DURATION_DAYS = 365
DEFAULT_PACKAGE_QUOTA = 5
MAX_PACKAGE_QUOTA = 100
DOWNLOAD_OPERATION = "download"


def _serialize_row(row) -> dict:
    value = dict(row._mapping)
    for key, item in value.items():
        if isinstance(item, (date, datetime)):
            value[key] = item.isoformat()
    return value


def _as_naive_utc(value) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _version_binding_payload(value: dict | None) -> dict | None:
    if not value or not value.get("data_product_version_id"):
        return None
    return {
        "tenant_id": str(value.get("tenant_id") or value.get("product_tenant_id") or ""),
        "product_urn": str(value.get("product_urn") or ""),
        "data_product_version_id": str(value["data_product_version_id"]),
        "version_key": str(
            value.get("version_key") or value.get("data_product_version_key") or ""
        ),
    }


def _package_path_is_valid(file_path: str, requester: str) -> bool:
    uploads_root = os.path.realpath(os.path.join(os.path.dirname(__file__), "uploads"))
    user_dir = os.path.realpath(os.path.join(uploads_root, requester))
    package_path = os.path.realpath(file_path)
    try:
        return (
            os.path.commonpath([uploads_root, user_dir]) == uploads_root
            and os.path.commonpath([user_dir, package_path]) == user_dir
            and os.path.basename(package_path).startswith("data_package_")
            and package_path.endswith(".zip")
        )
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Data Requests (申请审批)
# ---------------------------------------------------------------------------

def create_data_request(
    asset_id: int,
    requester: str,
    reason: str = "",
    duration_days: int = DEFAULT_REQUEST_DURATION_DAYS,
    package_quota: int = DEFAULT_PACKAGE_QUOTA,
) -> dict:
    try:
        asset_id = int(asset_id)
    except (TypeError, ValueError):
        return {
            "status": "error",
            "error_code": "invalid_asset_id",
            "message": "资产编号无效",
        }
    requester = str(requester or "").strip()
    if asset_id <= 0 or not requester:
        return {
            "status": "error",
            "error_code": "invalid_asset_id",
            "message": "资产编号无效",
        }
    try:
        duration_days = int(duration_days)
    except (TypeError, ValueError):
        return {"status": "error", "message": "授权期限无效"}
    if not 1 <= duration_days <= MAX_REQUEST_DURATION_DAYS:
        return {
            "status": "error",
            "message": f"授权期限必须在 1-{MAX_REQUEST_DURATION_DAYS} 天之间",
        }
    try:
        package_quota = int(package_quota)
    except (TypeError, ValueError):
        return {
            "status": "error",
            "error_code": "invalid_package_quota",
            "message": "分发包额度无效",
        }
    if not 1 <= package_quota <= MAX_PACKAGE_QUOTA:
        return {
            "status": "error",
            "error_code": "invalid_package_quota",
            "message": f"分发包额度必须在 1-{MAX_PACKAGE_QUOTA} 次之间",
        }

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            asset = conn.execute(
                text(
                    """
                    SELECT id, owner_username
                    FROM agent_data_assets
                    WHERE id = :asset_id
                    """
                ),
                {"asset_id": asset_id},
            ).fetchone()
            if not asset:
                return {
                    "status": "error",
                    "error_code": "asset_not_found",
                    "message": "资产不存在或无权访问",
                }

            owner = str(asset._mapping.get("owner_username") or "").strip()
            if owner == requester:
                return {
                    "status": "error",
                    "error_code": "owner_request_not_allowed",
                    "message": "资产责任人无需申请自己的资产",
                }

            conn.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:request_scope, 0))"
                ),
                {"request_scope": f"data-request:{asset_id}:{requester}"},
            )
            pending = conn.execute(
                text(
                    f"""
                    SELECT id, requested_package_quota
                    FROM {T_DATA_REQUESTS}
                    WHERE asset_id = :asset_id
                      AND requester = :requester
                      AND status = 'pending'
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {"asset_id": asset_id, "requester": requester},
            ).fetchone()
            if pending:
                return {
                    "status": "ok",
                    "id": pending._mapping["id"],
                    "created": False,
                    "request_status": "pending",
                    "requested_package_quota": pending._mapping[
                        "requested_package_quota"
                    ],
                }

            conn.execute(
                text(
                    f"""
                    INSERT INTO {T_DATA_REQUESTS} (
                        asset_id, requester, reason,
                        requested_operations, requested_duration_days,
                        requested_package_quota
                    ) VALUES (
                        :a, :r, :re, CAST(:operations AS jsonb), :duration_days,
                        :package_quota
                    )
                    """
                ),
                {
                    "a": asset_id,
                    "r": requester,
                    "re": str(reason or "").strip(),
                    "operations": json.dumps([DOWNLOAD_OPERATION]),
                    "duration_days": duration_days,
                    "package_quota": package_quota,
                },
            )
            conn.commit()
            rid = conn.execute(
                text(
                    f"SELECT id FROM {T_DATA_REQUESTS} "
                    "WHERE asset_id = :a AND requester = :r "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"a": asset_id, "r": requester},
            ).scalar()
        return {
            "status": "ok",
            "id": rid,
            "created": True,
            "request_status": "pending",
            "requested_package_quota": package_quota,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_data_requests(username: str, role: str = "analyst") -> list:
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            if role == "admin":
                rows = conn.execute(text(
                    f"SELECT * FROM {T_DATA_REQUESTS} ORDER BY created_at DESC LIMIT 100"
                )).fetchall()
            else:
                rows = conn.execute(
                    text(
                        f"SELECT * FROM {T_DATA_REQUESTS} "
                        "WHERE requester = :u ORDER BY created_at DESC LIMIT 50"
                    ),
                    {"u": username},
                ).fetchall()
        return [_serialize_row(row) for row in rows]
    except Exception:
        return []


def approve_request(
    request_id: int,
    approver: str,
    tenant_id: str = "",
) -> dict:
    """Approve a request and snapshot the declared product's current version."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            request_row = conn.execute(
                text(
                    f"""
                    SELECT request.id, request.asset_id, request.requester,
                           request.requested_package_quota,
                           asset.operational_metadata->'publication'
                               ->>'data_product_urn' AS product_urn
                    FROM {T_DATA_REQUESTS} request
                    JOIN {T_DATA_ASSETS} asset ON asset.id = request.asset_id
                    WHERE request.id = :id AND request.status = 'pending'
                    FOR UPDATE OF request
                    """
                ),
                {"id": request_id},
            ).fetchone()
            if not request_row or request_row._mapping.get("requester") == approver:
                return {"status": "error", "message": "申请未找到、已处理或不能自批"}

            product_urn = str(request_row._mapping.get("product_urn") or "").strip()
            binding = None
            if product_urn:
                if not tenant_id:
                    return {
                        "status": "error",
                        "error_code": "product_version_unavailable",
                        "message": "当前用户未绑定租户，无法校验资产的数据产品版本",
                    }
                conn.execute(
                    text(
                        "SELECT pg_advisory_xact_lock("
                        "hashtextextended(:promotion_scope, 0))"
                    ),
                    {
                        "promotion_scope": (
                            f"data-product-promotion:{tenant_id}:{product_urn}"
                        )
                    },
                )
                try:
                    from .data_product_registry import DataProductRegistry

                    binding = DataProductRegistry().resolve_current_version(
                        tenant_id,
                        product_urn,
                    )
                except Exception:
                    logger.exception(
                        "Unable to resolve DataProductVersion for request %s",
                        request_id,
                    )
                    return {
                        "status": "error",
                        "error_code": "product_version_unavailable",
                        "message": "资产关联的数据产品版本不可用，审批已停止",
                    }

            result = conn.execute(text(f"""
                UPDATE {T_DATA_REQUESTS}
                SET status = 'approved', approver = :ap, approved_at = NOW(),
                    granted_operations = requested_operations,
                    granted_package_quota = requested_package_quota,
                    expires_at = NOW()
                        + (requested_duration_days::text || ' days')::interval,
                    product_tenant_id = :product_tenant_id,
                    product_urn = :product_urn,
                    data_product_version_id = :data_product_version_id,
                    data_product_version_key = :data_product_version_key
                WHERE id = :id AND status = 'pending' AND requester <> :ap
            """), {
                "id": request_id,
                "ap": approver,
                "product_tenant_id": binding.get("tenant_id") if binding else None,
                "product_urn": binding.get("product_urn") if binding else None,
                "data_product_version_id": (
                    binding.get("data_product_version_id") if binding else None
                ),
                "data_product_version_key": binding.get("version_key") if binding else None,
            })
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "申请未找到或已处理"}
        return {
            "status": "ok",
            "grant_contract": "data_product_version" if binding else "asset_compatibility",
            "product_version": _version_binding_payload(binding),
            "granted_package_quota": request_row._mapping[
                "requested_package_quota"
            ],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def reject_request(request_id: int, approver: str, reason: str = "") -> dict:
    reason = str(reason or "").strip()
    if not reason:
        return {"status": "error", "message": "驳回原因不能为空"}
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                UPDATE {T_DATA_REQUESTS}
                SET status = 'rejected', approver = :ap, reject_reason = :rr, approved_at = NOW()
                WHERE id = :id AND status = 'pending'
            """), {"id": request_id, "ap": approver, "rr": reason})
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "申请未找到或已处理"}
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def revoke_request(request_id: int, revoker: str, reason: str = "") -> dict:
    """Revoke an active grant and invalidate every package created from it."""
    reason = str(reason or "").strip()
    if not reason:
        return {"status": "error", "message": "撤销原因不能为空"}
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}

    invalidated_packages: list[dict] = []
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            revoked = conn.execute(
                text(
                    f"""
                    UPDATE {T_DATA_REQUESTS}
                    SET revoked_at = NOW(), revoked_by = :revoker,
                        revocation_reason = :reason
                    WHERE id = :id
                      AND status = 'approved'
                      AND revoked_at IS NULL
                      AND expires_at > NOW()
                    RETURNING requester
                    """
                ),
                {"id": request_id, "revoker": revoker, "reason": reason},
            ).fetchone()
            if not revoked:
                return {"status": "error", "message": "授权未找到、已撤销或已过期"}

            package_rows = conn.execute(
                text(
                    """
                    UPDATE agent_distribution_packages AS package
                    SET invalidated_at = NOW(), invalidated_by = :revoker,
                        invalidation_reason = :reason
                    WHERE package.invalidated_at IS NULL
                      AND EXISTS (
                          SELECT 1
                          FROM agent_distribution_package_items item
                          WHERE item.package_id = package.package_id
                            AND item.grant_request_id = :request_id
                      )
                    RETURNING package.file_path, package.requester
                    """
                ),
                {
                    "request_id": request_id,
                    "revoker": revoker,
                    "reason": reason,
                },
            ).fetchall()
            invalidated_packages = [_serialize_row(row) for row in package_rows]
            conn.commit()
    except Exception as e:
        return {"status": "error", "message": str(e)}

    removed = 0
    for package in invalidated_packages:
        file_path = str(package.get("file_path") or "")
        requester = str(package.get("requester") or "")
        if not _package_path_is_valid(file_path, requester):
            continue
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                removed += 1
        except OSError:
            logger.warning("Unable to remove invalidated distribution package %s", file_path)
    return {
        "status": "ok",
        "invalidated_packages": len(invalidated_packages),
        "removed_packages": removed,
    }


# ---------------------------------------------------------------------------
# Asset Packaging (分发包打包)
# ---------------------------------------------------------------------------

def package_assets(asset_ids: list, username: str = "") -> dict:
    """Package local assets and atomically consume their grant quota."""
    try:
        normalized_ids = sorted({int(asset_id) for asset_id in asset_ids})
    except (TypeError, ValueError):
        return {"status": "error", "message": "资产编号无效"}
    if not normalized_ids or any(asset_id <= 0 for asset_id in normalized_ids):
        return {"status": "error", "message": "资产编号无效"}
    if len(normalized_ids) > 50:
        return {"status": "error", "message": "单次最多打包 50 个资产"}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    zip_path = ""
    try:
        from .user_context import current_user_role, get_user_upload_dir

        role = current_user_role.get()
        upload_dir = get_user_upload_dir()
        os.makedirs(upload_dir, exist_ok=True)
        package_id = uuid.uuid4()
        zip_name = f"data_package_{package_id.hex[:12]}.zip"
        zip_path = os.path.join(upload_dir, zip_name)

        files_added: list[tuple[int, str, str]] = []
        package_items: list[dict] = []
        package_expiries: list[datetime] = []
        with engine.connect() as conn:
            _inject_user_context(conn)
            for asset_id in normalized_ids:
                row = conn.execute(
                    text(
                        """
                        SELECT asset_name, owner_username,
                               technical_metadata->'storage'->>'path' AS local_path
                        FROM agent_data_assets
                        WHERE id = :asset_id
                        """
                    ),
                    {"asset_id": asset_id},
                ).fetchone()
                if not row:
                    return {
                        "status": "error",
                        "error_code": "asset_not_found",
                        "message": "资产不存在或无权访问",
                    }

                item = row._mapping
                owner = str(item.get("owner_username") or "")
                grant = None
                if role != "admin" and owner != username:
                    grant = conn.execute(
                        text(
                            f"""
                            SELECT id, expires_at, product_tenant_id, product_urn,
                                   data_product_version_id,
                                   data_product_version_key,
                                   granted_package_quota
                            FROM {T_DATA_REQUESTS}
                            WHERE asset_id = :asset_id
                              AND requester = :requester
                              AND status = 'approved'
                              AND revoked_at IS NULL
                              AND expires_at > NOW()
                              AND granted_operations @> '["download"]'::jsonb
                            ORDER BY expires_at DESC, id DESC
                            LIMIT 1
                            FOR UPDATE
                            """
                        ),
                        {"asset_id": asset_id, "requester": username},
                    ).fetchone()
                    if not grant:
                        return {
                            "status": "error",
                            "error_code": "access_denied",
                            "message": f"没有资产 {asset_id} 的有效分发授权",
                        }

                grant_value = dict(grant._mapping) if grant else {}
                packages_created = 0
                granted_package_quota = 0
                if grant:
                    granted_package_quota = int(
                        grant_value.get("granted_package_quota") or 0
                    )
                    packages_created = int(
                        conn.execute(
                            text(
                                """
                                SELECT COUNT(DISTINCT package_id)
                                FROM agent_distribution_package_items
                                WHERE grant_request_id = :grant_request_id
                                """
                            ),
                            {"grant_request_id": grant_value["id"]},
                        ).scalar()
                        or 0
                    )
                    if packages_created >= granted_package_quota:
                        return {
                            "status": "error",
                            "error_code": "quota_exhausted",
                            "message": (
                                f"资产 {asset_id} 的分发包额度已用完，"
                                "请申请追加额度"
                            ),
                            "grant_request_id": grant_value["id"],
                            "granted_package_quota": granted_package_quota,
                            "packages_created": packages_created,
                            "packages_remaining": 0,
                        }
                grant_expiry = _as_naive_utc(grant_value.get("expires_at"))
                if grant_expiry is not None:
                    package_expiries.append(grant_expiry)

                file_path = str(item.get("local_path") or "")
                if not file_path or not os.path.isfile(file_path):
                    return {
                        "status": "error",
                        "error_code": "asset_unavailable",
                        "message": f"资产 {asset_id} 暂无可打包的本地文件",
                    }
                asset_name = str(item.get("asset_name") or "")
                files_added.append((asset_id, file_path, asset_name))
                package_items.append({
                    "asset_id": asset_id,
                    "asset_name": asset_name,
                    "grant_request_id": grant_value.get("id"),
                    "access_basis": (
                        "admin" if role == "admin" else "owner" if owner == username else "grant"
                    ),
                    "product_version": _version_binding_payload(grant_value),
                    "grant_expires_at": (
                        grant_expiry.isoformat() if grant_expiry is not None else None
                    ),
                    "package_quota": (
                        {
                            "granted": granted_package_quota,
                            "packages_created_before": packages_created,
                            "packages_created_after": packages_created + 1,
                            "packages_remaining_after": max(
                                granted_package_quota - packages_created - 1,
                                0,
                            ),
                        }
                        if grant
                        else None
                    ),
                })

            default_expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(
                days=DEFAULT_REQUEST_DURATION_DAYS
            )
            package_expiry = min(package_expiries) if package_expiries else default_expiry
            manifest = {
                "schema": "gda.asset_distribution_package.v2",
                "package_id": str(package_id),
                "generated_by": username,
                "generated_at": datetime.now(UTC).isoformat(),
                "expires_at": package_expiry.isoformat(),
                "delivery_source": "catalog_asset_local_file",
                "assets": package_items,
            }
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for _asset_id, fpath, asset_name in files_added:
                    arcname = os.path.basename(asset_name) or os.path.basename(fpath)
                    zf.write(fpath, arcname)
                zf.writestr(
                    "_gda_distribution_manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )

            conn.execute(
                text(
                    """
                    INSERT INTO agent_distribution_packages (
                        package_id, requester, zip_name, file_path, expires_at
                    ) VALUES (
                        CAST(:package_id AS uuid), :requester, :zip_name,
                        :file_path, :expires_at
                    )
                    """
                ),
                {
                    "package_id": str(package_id),
                    "requester": username,
                    "zip_name": zip_name,
                    "file_path": zip_path,
                    "expires_at": package_expiry,
                },
            )
            for package_item in package_items:
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_distribution_package_items (
                            package_id, asset_id, grant_request_id
                        ) VALUES (
                            CAST(:package_id AS uuid), :asset_id, :grant_request_id
                        )
                        """
                    ),
                    {
                        "package_id": str(package_id),
                        "asset_id": package_item["asset_id"],
                        "grant_request_id": package_item["grant_request_id"],
                    },
                )
            conn.commit()

        return {
            "status": "ok",
            "package_id": str(package_id),
            "zip_name": zip_name,
            "download_url": f"/api/distribution-packages/{package_id}/download",
            "file_count": len(files_added),
            "expires_at": package_expiry.isoformat(),
        }
    except Exception as e:
        if zip_path and os.path.isfile(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                logger.warning("Unable to remove failed distribution package %s", zip_path)
        return {"status": "error", "message": str(e)}


def get_distribution_package(package_id: str, username: str) -> dict:
    """Resolve a package only while its user and every source grant remain valid."""
    try:
        normalized_package_id = str(uuid.UUID(str(package_id)))
    except (TypeError, ValueError, AttributeError):
        return {
            "status": "error",
            "error_code": "package_not_found",
            "message": "分发包不存在",
        }
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            row = conn.execute(
                text(
                    f"""
                    SELECT package.package_id, package.requester,
                           package.zip_name, package.file_path, package.expires_at
                    FROM agent_distribution_packages package
                    WHERE package.package_id = CAST(:package_id AS uuid)
                      AND package.requester = :requester
                      AND package.invalidated_at IS NULL
                      AND package.expires_at > NOW()
                      AND NOT EXISTS (
                          SELECT 1
                          FROM agent_distribution_package_items item
                          JOIN {T_DATA_REQUESTS} request
                            ON request.id = item.grant_request_id
                          WHERE item.package_id = package.package_id
                            AND item.grant_request_id IS NOT NULL
                            AND (
                                request.revoked_at IS NOT NULL
                                OR request.expires_at <= NOW()
                            )
                      )
                    """
                ),
                {"package_id": normalized_package_id, "requester": username},
            ).fetchone()
            if not row:
                return {
                    "status": "error",
                    "error_code": "package_not_found",
                    "message": "分发包不存在、已过期或已撤销",
                }
            package = _serialize_row(row)
            file_path = str(package.get("file_path") or "")
            if (
                not _package_path_is_valid(file_path, username)
                or not os.path.isfile(file_path)
            ):
                return {
                    "status": "error",
                    "error_code": "package_not_found",
                    "message": "分发包文件不可用",
                }
            conn.execute(
                text(
                    """
                    UPDATE agent_distribution_packages
                    SET download_count = download_count + 1,
                        last_downloaded_at = NOW()
                    WHERE package_id = CAST(:package_id AS uuid)
                    """
                ),
                {"package_id": normalized_package_id},
            )
            conn.commit()
            return {"status": "ok", **package}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Asset Reviews (用户评价)
# ---------------------------------------------------------------------------

def add_review(asset_id: int, username: str, rating: int, comment: str = "") -> dict:
    if rating < 1 or rating > 5:
        return {"status": "error", "message": "评分必须在 1-5 之间"}
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_ASSET_REVIEWS} (asset_id, username, rating, comment)
                VALUES (:a, :u, :r, :c)
                ON CONFLICT (asset_id, username)
                DO UPDATE SET rating = :r, comment = :c, created_at = NOW()
            """), {"a": asset_id, "u": username, "r": rating, "c": comment})
            conn.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_reviews(asset_id: int) -> list:
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT * FROM {T_ASSET_REVIEWS}
                WHERE asset_id = :a ORDER BY created_at DESC LIMIT 50
            """), {"a": asset_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []


def get_asset_rating(asset_id: int) -> dict:
    engine = get_engine()
    if not engine:
        return {"avg_rating": 0, "count": 0}
    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT AVG(rating) as avg_r, COUNT(*) as cnt
                FROM {T_ASSET_REVIEWS} WHERE asset_id = :a
            """), {"a": asset_id}).fetchone()
        if row:
            return {"avg_rating": round(float(row._mapping["avg_r"] or 0), 1),
                    "count": int(row._mapping["cnt"])}
        return {"avg_rating": 0, "count": 0}
    except Exception:
        return {"avg_rating": 0, "count": 0}


# ---------------------------------------------------------------------------
# Access Tracking (热度统计)
# ---------------------------------------------------------------------------

def log_access(asset_id: int, username: str, access_type: str = "view"):
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_ACCESS_LOG} (asset_id, username, access_type)
                VALUES (:a, :u, :t)
            """), {"a": asset_id, "u": username, "t": access_type})
            conn.commit()
    except Exception:
        pass


def get_access_stats(asset_id: int = None, days: int = 30) -> dict:
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            if asset_id:
                row = conn.execute(text(f"""
                    SELECT COUNT(*) as total,
                           COUNT(DISTINCT username) as unique_users
                    FROM {T_ACCESS_LOG}
                    WHERE asset_id = :a AND created_at >= NOW() - INTERVAL '{int(days)} days'
                """), {"a": asset_id}).fetchone()
                return {
                    "asset_id": asset_id,
                    "total_accesses": int(row._mapping["total"]),
                    "unique_users": int(row._mapping["unique_users"]),
                    "period_days": days,
                }
            else:
                rows = conn.execute(text(f"""
                    SELECT access_type, COUNT(*) as cnt
                    FROM {T_ACCESS_LOG}
                    WHERE created_at >= NOW() - INTERVAL '{int(days)} days'
                    GROUP BY access_type
                """)).fetchall()
                return {
                    "by_type": {r._mapping["access_type"]: int(r._mapping["cnt"]) for r in rows},
                    "period_days": days,
                }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_hot_assets(limit: int = 10) -> list:
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT al.asset_id, dc.asset_name, COUNT(*) as access_count,
                       COUNT(DISTINCT al.username) as unique_users
                FROM {T_ACCESS_LOG} al
                LEFT JOIN {T_DATA_ASSETS} dc ON al.asset_id = dc.id
                WHERE al.created_at >= NOW() - INTERVAL '30 days'
                GROUP BY al.asset_id, dc.asset_name
                ORDER BY access_count DESC
                LIMIT :lim
            """), {"lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []

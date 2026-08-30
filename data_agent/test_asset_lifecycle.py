import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from data_agent.asset_lifecycle import (
    AssetLifecycleRepositoryError,
    calculate_asset_lifecycle,
    get_asset_lifecycle,
)
from data_agent.user_context import current_user_id, current_user_role


def _asset(**overrides):
    asset = {
        "id": 42,
        "asset_name": "districts.gpkg",
        "display_name": "行政区边界",
        "owner_username": "data-owner",
        "is_shared": False,
        "access_level": "private",
        "technical_metadata": {
            "storage": {
                "backend": "object",
                "format": "gpkg",
                "size_bytes": 2048,
            },
            "spatial": {
                "crs": "EPSG:4326",
                "extent": {"minx": 100, "miny": 20, "maxx": 110, "maxy": 30},
            },
            "structure": {
                "feature_count": 12,
                "columns": [{"name": "name", "type": "text"}],
            },
        },
        "business_metadata": {
            "semantic": {"description": "District boundaries", "keywords": ["admin"]},
            "classification": {"category": "vector"},
        },
        "operational_metadata": {"version": {"version": 2}},
        "lineage_metadata": {},
    }
    asset.update(overrides)
    return asset


def test_lifecycle_exposes_missing_governance_without_inventing_evidence():
    result = calculate_asset_lifecycle(_asset())

    assert result["current_stage"] == "documented"
    assert result["readiness"]["ready"] is False
    assert result["readiness"]["score"] == 50
    assert result["readiness"]["blockers"] == [
        "缺少敏感级别",
        "尚未执行质量检查",
        "缺少许可或使用授权",
    ]
    assert result["readiness"]["warnings"] == ["尚无可验证的血缘关系"]
    assert result["publication"]["evidence_detected"] is False
    assert result["quality"]["has_evidence"] is False


def test_lifecycle_reaches_operating_only_with_publish_and_usage_evidence():
    asset = _asset(
        is_shared=True,
        business_metadata={
            "semantic": {"description": "District boundaries", "keywords": ["admin"]},
            "classification": {"category": "vector"},
            "governance": {
                "sensitivity_level": "internal",
                "license_id": "government-use-2026",
            },
        },
        operational_metadata={
            "version": {"version": 3},
            "publication": {
                "status": "active",
                "service_endpoint": "https://data.example.test/districts",
            },
        },
    )
    result = calculate_asset_lifecycle(
        asset,
        quality={
            "score": 94.5,
            "issues_count": 1,
            "dimension_scores": {"completeness": 98},
            "created_at": "2026-08-01T10:00:00Z",
        },
        usage={"total_accesses": 18, "unique_users": 4},
        reviews={"avg_rating": 4.4, "count": 5},
        versions=[{"version": 2, "change_summary": "Fixed geometry"}],
        lineage={"ancestors": [{"id": 1, "name": "survey.gpkg"}], "descendants": []},
        distribution_requests={"approved": 2, "pending": 1},
    )

    assert result["current_stage"] == "operating"
    assert result["readiness"]["ready"] is True
    assert result["readiness"]["score"] == 100
    assert result["publication"]["evidence_detected"] is True
    assert result["usage"] == {
        "total_accesses": 18,
        "unique_users": 4,
        "last_accessed_at": None,
    }
    assert result["versions"]["current"] == 3
    assert result["lineage"]["source_count"] == 1


def test_non_spatial_assets_do_not_require_a_crs():
    asset = _asset(
        technical_metadata={
            "storage": {"backend": "object", "format": "csv"},
            "structure": {"feature_count": 100},
        },
        business_metadata={
            "semantic": {"description": "Population totals"},
            "classification": {"category": "tabular"},
            "governance": {
                "sensitivity_level": "public",
                "license_id": "odc-by-1.0",
            },
        },
    )
    result = calculate_asset_lifecycle(asset, quality={"score": 90})
    crs_check = next(
        check for check in result["readiness"]["checks"]
        if check["id"] == "spatial_reference"
    )

    assert crs_check["status"] == "not_applicable"
    assert result["readiness"]["ready"] is True


def test_explicit_retirement_overrides_other_operational_stages():
    asset = _asset(
        is_shared=True,
        operational_metadata={
            "lifecycle": {"status": "retired"},
            "publication": {"status": "published"},
        },
    )
    result = calculate_asset_lifecycle(asset, usage={"total_accesses": 20})

    assert result["current_stage"] == "retired"
    assert result["stages"][-1]["status"] == "current"


def _request(asset_id: int = 42):
    request = MagicMock()
    request.cookies = {}
    request.path_params = {"asset_id": asset_id}
    return request


def _user():
    user = MagicMock()
    user.identifier = "analyst"
    user.metadata = {"role": "analyst", "tenant_id": "planning"}
    return user


def test_lifecycle_route_requires_authentication():
    from data_agent.api.catalog_lifecycle_routes import catalog_asset_lifecycle

    with patch(
        "data_agent.api.catalog_lifecycle_routes._get_user_from_request",
        return_value=None,
    ):
        response = asyncio.run(catalog_asset_lifecycle(_request()))
    assert response.status_code == 401


def test_lifecycle_route_returns_404_for_inaccessible_asset():
    from data_agent.api.catalog_lifecycle_routes import catalog_asset_lifecycle

    with (
        patch(
            "data_agent.api.catalog_lifecycle_routes._get_user_from_request",
            return_value=_user(),
        ),
        patch(
            "data_agent.api.catalog_lifecycle_routes.get_asset_lifecycle",
            return_value=None,
        ),
    ):
        response = asyncio.run(catalog_asset_lifecycle(_request()))
    assert response.status_code == 404


def test_lifecycle_route_returns_evidence_view():
    from data_agent.api.catalog_lifecycle_routes import catalog_asset_lifecycle

    payload = calculate_asset_lifecycle(_asset())
    with (
        patch(
            "data_agent.api.catalog_lifecycle_routes._get_user_from_request",
            return_value=_user(),
        ),
        patch(
            "data_agent.api.catalog_lifecycle_routes.get_asset_lifecycle",
            return_value=payload,
        ),
    ):
        response = asyncio.run(catalog_asset_lifecycle(_request()))

    assert response.status_code == 200
    assert json.loads(response.body)["asset"]["asset_name"] == "districts.gpkg"


def test_lifecycle_route_fails_closed_when_catalog_is_unavailable():
    from data_agent.api.catalog_lifecycle_routes import catalog_asset_lifecycle

    with (
        patch(
            "data_agent.api.catalog_lifecycle_routes._get_user_from_request",
            return_value=_user(),
        ),
        patch(
            "data_agent.api.catalog_lifecycle_routes.get_asset_lifecycle",
            side_effect=AssetLifecycleRepositoryError("offline"),
        ),
    ):
        response = asyncio.run(catalog_asset_lifecycle(_request()))
    assert response.status_code == 503


def test_lifecycle_route_and_existing_detail_ui_are_wired_together():
    from data_agent.frontend_api import get_frontend_api_routes

    paths = [route.path for route in get_frontend_api_routes()]
    assert "/api/catalog/{asset_id:int}/lifecycle" in paths

    root = Path(__file__).resolve().parents[1]
    catalog_ui = (
        root / "frontend/src/components/datapanel/CatalogTab.tsx"
    ).read_text(encoding="utf-8")
    assert "/lifecycle" in catalog_ui
    assert "/api/data-requests" in catalog_ui
    assert "asset-lifecycle-steps" in catalog_ui
    assert "normalizeCatalogAsset" in catalog_ui


def _repository_engine(asset):
    engine = MagicMock()
    conn = engine.connect.return_value.__enter__.return_value
    row = MagicMock()
    row._mapping = asset
    conn.execute.return_value.fetchone.return_value = row
    return engine


def test_lifecycle_only_exposes_current_users_request_to_analyst():
    my_request = {
        "id": 19,
        "status": "pending",
        "requester": "analyst",
        "reason": "规划分析",
        "created_at": "2026-08-02T08:00:00Z",
    }
    user_token = current_user_id.set("analyst")
    role_token = current_user_role.set("analyst")
    try:
        with (
            patch(
                "data_agent.asset_lifecycle.get_engine",
                return_value=_repository_engine(_asset()),
            ),
            patch("data_agent.data_catalog._inject_user_context"),
            patch("data_agent.asset_lifecycle._optional_row", return_value={}),
            patch(
                "data_agent.asset_lifecycle._optional_rows",
                side_effect=[
                    [],
                    [{"status": "pending", "count": 2}],
                    [my_request],
                    [],
                ],
            ),
            patch("data_agent.data_catalog.get_data_lineage", return_value={"status": "error"}),
        ):
            result = get_asset_lifecycle(42)
    finally:
        current_user_id.reset(user_token)
        current_user_role.reset(role_token)

    assert result is not None
    assert result["request_access"]["my_request"]["id"] == 19
    assert result["request_access"]["can_request"] is False
    assert "pending_items" not in result["request_access"]


def test_lifecycle_exposes_asset_pending_queue_only_to_admin():
    pending = {
        "id": 21,
        "status": "pending",
        "requester": "planner",
        "reason": "专题制图",
        "created_at": "2026-08-02T08:00:00Z",
    }
    user_token = current_user_id.set("admin")
    role_token = current_user_role.set("admin")
    try:
        with (
            patch(
                "data_agent.asset_lifecycle.get_engine",
                return_value=_repository_engine(_asset()),
            ),
            patch("data_agent.data_catalog._inject_user_context"),
            patch("data_agent.asset_lifecycle._optional_row", return_value={}),
            patch(
                "data_agent.asset_lifecycle._optional_rows",
                side_effect=[
                    [],
                    [{"status": "pending", "count": 1}],
                    [],
                    [],
                    [pending],
                    [],
                ],
            ),
            patch("data_agent.data_catalog.get_data_lineage", return_value={"status": "error"}),
        ):
            result = get_asset_lifecycle(42)
    finally:
        current_user_id.reset(user_token)
        current_user_role.reset(role_token)

    assert result is not None
    assert result["request_access"]["can_request"] is False
    assert result["request_access"]["pending_items"] == [{
        "id": 21,
        "status": "pending",
        "requester": "planner",
        "reason": "专题制图",
        "approver": "",
        "reject_reason": "",
        "requested_operations": [],
        "requested_duration_days": 30,
        "requested_package_quota": 5,
        "granted_operations": [],
        "granted_package_quota": 0,
        "packages_created": 0,
        "packages_remaining": 0,
        "quota_exhausted": False,
        "grant_status": "none",
        "grant_contract": "asset_compatibility",
        "product_version": None,
        "expires_at": None,
        "revoked_at": None,
        "revoked_by": "",
        "revocation_reason": "",
        "created_at": "2026-08-02T08:00:00Z",
        "approved_at": None,
    }]


def test_lifecycle_marks_unexpired_download_grant_as_packageable():
    grant = {
        "id": 31,
        "status": "approved",
        "requester": "analyst",
        "reason": "离线规划分析",
        "requested_operations": ["download"],
        "requested_duration_days": 30,
        "requested_package_quota": 5,
        "granted_operations": ["download"],
        "granted_package_quota": 5,
        "packages_created": 2,
        "expires_at": "2099-09-01T00:00:00Z",
        "created_at": "2026-08-02T08:00:00Z",
        "approved_at": "2026-08-02T09:00:00Z",
    }
    user_token = current_user_id.set("analyst")
    role_token = current_user_role.set("analyst")
    try:
        with (
            patch(
                "data_agent.asset_lifecycle.get_engine",
                return_value=_repository_engine(_asset()),
            ),
            patch("data_agent.data_catalog._inject_user_context"),
            patch("data_agent.asset_lifecycle._optional_row", return_value={}),
            patch(
                "data_agent.asset_lifecycle._optional_rows",
                side_effect=[
                    [],
                    [{"status": "approved", "count": 1}],
                    [grant],
                    [grant],
                ],
            ),
            patch("data_agent.data_catalog.get_data_lineage", return_value={"status": "error"}),
        ):
            result = get_asset_lifecycle(42)
    finally:
        current_user_id.reset(user_token)
        current_user_role.reset(role_token)

    assert result is not None
    assert result["request_access"]["can_request"] is False
    assert result["request_access"]["can_package"] is True
    assert result["request_access"]["active_grant"]["grant_status"] == "active"
    assert result["request_access"]["active_grant"]["packages_remaining"] == 3


def test_lifecycle_exhausted_grant_can_request_more_but_cannot_package():
    grant = {
        "id": 34,
        "status": "approved",
        "requester": "analyst",
        "reason": "离线规划分析",
        "requested_operations": ["download"],
        "requested_duration_days": 30,
        "requested_package_quota": 3,
        "granted_operations": ["download"],
        "granted_package_quota": 3,
        "packages_created": 3,
        "expires_at": "2099-09-01T00:00:00Z",
        "created_at": "2026-08-02T08:00:00Z",
        "approved_at": "2026-08-02T09:00:00Z",
    }
    user_token = current_user_id.set("analyst")
    role_token = current_user_role.set("analyst")
    try:
        with (
            patch(
                "data_agent.asset_lifecycle.get_engine",
                return_value=_repository_engine(_asset()),
            ),
            patch("data_agent.data_catalog._inject_user_context"),
            patch("data_agent.asset_lifecycle._optional_row", return_value={}),
            patch(
                "data_agent.asset_lifecycle._optional_rows",
                side_effect=[
                    [],
                    [{"status": "approved", "count": 1}],
                    [grant],
                    [grant],
                ],
            ),
            patch(
                "data_agent.data_catalog.get_data_lineage",
                return_value={"status": "error"},
            ),
        ):
            result = get_asset_lifecycle(42)
    finally:
        current_user_id.reset(user_token)
        current_user_role.reset(role_token)

    assert result is not None
    access = result["request_access"]
    assert access["active_grant"]["quota_exhausted"] is True
    assert access["active_grant"]["packages_remaining"] == 0
    assert access["can_request"] is True
    assert access["can_package"] is False


def test_lifecycle_expired_grant_can_be_requested_again_but_not_packaged():
    expired = {
        "id": 32,
        "status": "approved",
        "requester": "analyst",
        "reason": "历史离线分析",
        "requested_operations": ["download"],
        "requested_duration_days": 7,
        "granted_operations": ["download"],
        "expires_at": "2020-09-01T00:00:00Z",
        "created_at": "2020-08-01T08:00:00Z",
        "approved_at": "2020-08-01T09:00:00Z",
    }
    user_token = current_user_id.set("analyst")
    role_token = current_user_role.set("analyst")
    try:
        with (
            patch(
                "data_agent.asset_lifecycle.get_engine",
                return_value=_repository_engine(_asset()),
            ),
            patch("data_agent.data_catalog._inject_user_context"),
            patch("data_agent.asset_lifecycle._optional_row", return_value={}),
            patch(
                "data_agent.asset_lifecycle._optional_rows",
                side_effect=[
                    [],
                    [{"status": "approved", "count": 1}],
                    [expired],
                    [],
                ],
            ),
            patch("data_agent.data_catalog.get_data_lineage", return_value={"status": "error"}),
        ):
            result = get_asset_lifecycle(42)
    finally:
        current_user_id.reset(user_token)
        current_user_role.reset(role_token)

    assert result is not None
    assert result["request_access"]["can_request"] is True
    assert result["request_access"]["can_package"] is False
    assert result["request_access"]["my_request"]["grant_status"] == "expired"


def test_lifecycle_exposes_locked_product_version_and_revocation():
    revoked = {
        "id": 33,
        "status": "approved",
        "requester": "analyst",
        "reason": "离线规划分析",
        "requested_operations": ["download"],
        "requested_duration_days": 30,
        "granted_operations": ["download"],
        "expires_at": "2099-09-01T00:00:00Z",
        "product_tenant_id": "planning",
        "product_urn": "gda://planning/data_product/districts",
        "data_product_version_id": "3e5b675a-6d82-4e38-9e9b-3c454016c592",
        "data_product_version_key": "v2.1.0",
        "revoked_at": "2026-08-03T08:00:00Z",
        "revoked_by": "admin",
        "revocation_reason": "项目已结束",
        "created_at": "2026-08-02T08:00:00Z",
        "approved_at": "2026-08-02T09:00:00Z",
    }
    user_token = current_user_id.set("analyst")
    role_token = current_user_role.set("analyst")
    try:
        with (
            patch(
                "data_agent.asset_lifecycle.get_engine",
                return_value=_repository_engine(_asset()),
            ),
            patch("data_agent.data_catalog._inject_user_context"),
            patch("data_agent.asset_lifecycle._optional_row", return_value={}),
            patch(
                "data_agent.asset_lifecycle._optional_rows",
                side_effect=[
                    [],
                    [{"status": "approved", "count": 1}],
                    [revoked],
                    [],
                ],
            ),
            patch("data_agent.data_catalog.get_data_lineage", return_value={"status": "error"}),
        ):
            result = get_asset_lifecycle(42)
    finally:
        current_user_id.reset(user_token)
        current_user_role.reset(role_token)

    assert result is not None
    request = result["request_access"]["my_request"]
    assert request["grant_status"] == "revoked"
    assert request["grant_contract"] == "data_product_version"
    assert request["product_version"]["version_key"] == "v2.1.0"
    assert request["revocation_reason"] == "项目已结束"
    assert result["request_access"]["can_request"] is True
    assert result["request_access"]["can_package"] is False

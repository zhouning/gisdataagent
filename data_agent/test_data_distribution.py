"""Tests for data distribution — requests, reviews, packaging, access stats (v15.0)."""
import asyncio
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from data_agent.user_context import current_user_role


def _row(**values):
    row = MagicMock()
    row._mapping = values
    return row


class TestCreateRequest(unittest.TestCase):
    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_create_success(self, mock_eng, mock_inject):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        created_id = MagicMock()
        created_id.scalar.return_value = 1
        conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=_row(id=1, owner_username="owner"))),
            None,
            MagicMock(fetchone=MagicMock(return_value=None)),
            None,
            created_id,
        ]
        mock_eng.return_value = engine
        from data_agent.data_distribution import create_data_request
        result = create_data_request(1, "user1", "need this data")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["created"])
        mock_inject.assert_called_once_with(conn)
        insert_params = conn.execute.call_args_list[3].args[1]
        self.assertEqual(insert_params["duration_days"], 30)
        self.assertEqual(insert_params["package_quota"], 5)
        self.assertEqual(json.loads(insert_params["operations"]), ["download"])

    def test_create_rejects_duration_outside_bounded_contract(self):
        from data_agent.data_distribution import create_data_request

        result = create_data_request(1, "user1", duration_days=366)

        self.assertEqual(result["status"], "error")
        self.assertIn("1-365", result["message"])

    def test_create_rejects_package_quota_outside_bounded_contract(self):
        from data_agent.data_distribution import create_data_request

        result = create_data_request(1, "user1", package_quota=101)

        self.assertEqual(result["error_code"], "invalid_package_quota")
        self.assertIn("1-100", result["message"])

    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_existing_pending_request_is_idempotent(self, mock_eng, _mock_inject):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=_row(id=1, owner_username="owner"))),
            None,
            MagicMock(
                fetchone=MagicMock(
                    return_value=_row(id=77, requested_package_quota=8)
                )
            ),
        ]
        mock_eng.return_value = engine

        from data_agent.data_distribution import create_data_request

        result = create_data_request(1, "user1", "duplicate click")

        self.assertEqual(result, {
            "status": "ok",
            "id": 77,
            "created": False,
            "request_status": "pending",
            "requested_package_quota": 8,
        })
        conn.commit.assert_not_called()
        lock_call = conn.execute.call_args_list[1]
        self.assertIn("pg_advisory_xact_lock", str(lock_call.args[0]))

    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_inaccessible_asset_is_rejected(self, mock_eng, _mock_inject):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = None
        mock_eng.return_value = engine

        from data_agent.data_distribution import create_data_request

        result = create_data_request(999, "user1")

        self.assertEqual(result["error_code"], "asset_not_found")
        conn.commit.assert_not_called()

    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_owner_cannot_request_own_asset(self, mock_eng, _mock_inject):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = _row(
            id=1,
            owner_username="user1",
        )
        mock_eng.return_value = engine

        from data_agent.data_distribution import create_data_request

        result = create_data_request(1, "user1")

        self.assertEqual(result["error_code"], "owner_request_not_allowed")
        conn.commit.assert_not_called()

    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_create_no_db(self, _):
        from data_agent.data_distribution import create_data_request
        result = create_data_request(1, "user1")
        self.assertEqual(result["status"], "error")


class TestListRequests(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_list_no_db(self, _):
        from data_agent.data_distribution import list_data_requests
        self.assertEqual(list_data_requests("user1"), [])

    @patch("data_agent.data_distribution.get_engine")
    def test_list_serializes_request_timestamps_for_json_api(self, mock_eng):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchall.return_value = [
            _row(id=1, requester="user1", created_at=datetime(2026, 8, 2, 9, 0))
        ]
        mock_eng.return_value = engine

        from data_agent.data_distribution import list_data_requests

        result = list_data_requests("user1")

        self.assertEqual(result[0]["created_at"], "2026-08-02T09:00:00")
        json.dumps(result)


class TestApproveReject(unittest.TestCase):
    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_approve_creates_bounded_grant(self, mock_eng, _mock_inject):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        update_result = MagicMock(rowcount=1)
        conn.execute.side_effect = [
            MagicMock(
                fetchone=MagicMock(
                    return_value=_row(
                        id=1,
                        asset_id=42,
                        requester="analyst",
                        requested_package_quota=5,
                        product_urn=None,
                    )
                )
            ),
            update_result,
        ]
        mock_eng.return_value = engine

        from data_agent.data_distribution import approve_request

        result = approve_request(1, "admin")

        self.assertEqual(result["status"], "ok")
        statement = str(conn.execute.call_args_list[1].args[0])
        self.assertIn("granted_operations = requested_operations", statement)
        self.assertIn("granted_package_quota = requested_package_quota", statement)
        self.assertIn("expires_at", statement)
        self.assertIn("requester <> :ap", statement)
        self.assertEqual(result["grant_contract"], "asset_compatibility")

    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_approve_locks_declared_data_product_version(self, mock_eng, _mock_inject):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        update_result = MagicMock(rowcount=1)
        conn.execute.side_effect = [
            MagicMock(
                fetchone=MagicMock(
                    return_value=_row(
                        id=1,
                        asset_id=42,
                        requester="analyst",
                        requested_package_quota=7,
                        product_urn="gda://planning/data_product/districts",
                    )
                )
            ),
            None,
            update_result,
        ]
        mock_eng.return_value = engine
        resolved = {
            "tenant_id": "planning",
            "product_urn": "gda://planning/data_product/districts",
            "data_product_version_id": "3e5b675a-6d82-4e38-9e9b-3c454016c592",
            "version_key": "v2.1.0",
        }

        from data_agent.data_distribution import approve_request

        with patch(
            "data_agent.data_product_registry.DataProductRegistry.resolve_current_version",
            return_value=resolved,
        ) as resolve:
            result = approve_request(1, "admin", "planning")

        self.assertEqual(result["grant_contract"], "data_product_version")
        self.assertEqual(result["product_version"]["version_key"], "v2.1.0")
        self.assertEqual(result["granted_package_quota"], 7)
        resolve.assert_called_once_with(
            "planning",
            "gda://planning/data_product/districts",
        )
        lock_statement = str(conn.execute.call_args_list[1].args[0])
        self.assertIn("pg_advisory_xact_lock", lock_statement)
        update_params = conn.execute.call_args_list[2].args[1]
        self.assertEqual(update_params["data_product_version_key"], "v2.1.0")

    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_approve_no_db(self, _):
        from data_agent.data_distribution import approve_request
        result = approve_request(1, "admin")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_reject_no_db(self, _):
        from data_agent.data_distribution import reject_request
        result = reject_request(1, "admin", "not appropriate")
        self.assertEqual(result["status"], "error")

    def test_reject_requires_reason(self):
        from data_agent.data_distribution import reject_request

        result = reject_request(1, "admin", "  ")
        self.assertEqual(result["message"], "驳回原因不能为空")

    def test_revoke_requires_reason(self):
        from data_agent.data_distribution import revoke_request

        result = revoke_request(1, "admin", "  ")
        self.assertEqual(result["message"], "撤销原因不能为空")

    @patch("data_agent.data_distribution.os.remove")
    @patch("data_agent.data_distribution.os.path.isfile", return_value=True)
    @patch("data_agent.data_distribution._package_path_is_valid", return_value=True)
    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_revoke_invalidates_and_removes_generated_packages(
        self,
        mock_eng,
        _mock_inject,
        _mock_valid_path,
        _mock_isfile,
        mock_remove,
    ):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=_row(requester="analyst"))),
            MagicMock(
                fetchall=MagicMock(
                    return_value=[
                        _row(
                            file_path=(
                                "/tmp/uploads/analyst/data_package_123456789abc.zip"
                            ),
                            requester="analyst",
                        )
                    ]
                )
            ),
        ]
        mock_eng.return_value = engine

        from data_agent.data_distribution import revoke_request

        result = revoke_request(9, "admin", "项目已结束")

        self.assertEqual(result["invalidated_packages"], 1)
        self.assertEqual(result["removed_packages"], 1)
        mock_remove.assert_called_once()


class TestDistributionRoutes(unittest.TestCase):
    def test_duplicate_request_route_returns_200(self):
        from data_agent.api.distribution_routes import dreq_create

        request = MagicMock()
        request.cookies = {}
        request.json = AsyncMock(return_value={"asset_id": 42, "reason": "planning"})
        user = MagicMock()
        user.identifier = "analyst"
        user.metadata = {"role": "analyst"}
        with (
            patch(
                "data_agent.api.distribution_routes._get_user_from_request",
                return_value=user,
            ),
            patch(
                "data_agent.data_distribution.create_data_request",
                return_value={
                    "status": "ok",
                    "id": 7,
                    "created": False,
                    "request_status": "pending",
                },
            ),
        ):
            response = asyncio.run(dreq_create(request))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(json.loads(response.body)["created"])

    def test_package_access_denial_returns_403(self):
        from data_agent.api.distribution_routes import assets_package

        request = MagicMock()
        request.cookies = {}
        request.json = AsyncMock(return_value={"asset_ids": [42]})
        user = MagicMock()
        user.identifier = "analyst"
        user.metadata = {"role": "analyst"}
        with (
            patch(
                "data_agent.api.distribution_routes._get_user_from_request",
                return_value=user,
            ),
            patch(
                "data_agent.data_distribution.package_assets",
                return_value={
                    "status": "error",
                    "error_code": "access_denied",
                    "message": "没有有效分发授权",
                },
            ),
        ):
            response = asyncio.run(assets_package(request))

        self.assertEqual(response.status_code, 403)

    def test_package_quota_exhaustion_returns_409(self):
        from data_agent.api.distribution_routes import assets_package

        request = MagicMock()
        request.cookies = {}
        request.json = AsyncMock(return_value={"asset_ids": [42]})
        user = MagicMock()
        user.identifier = "analyst"
        user.metadata = {"role": "analyst"}
        with (
            patch(
                "data_agent.api.distribution_routes._get_user_from_request",
                return_value=user,
            ),
            patch(
                "data_agent.data_distribution.package_assets",
                return_value={
                    "status": "error",
                    "error_code": "quota_exhausted",
                    "message": "分发包额度已用完",
                },
            ),
        ):
            response = asyncio.run(assets_package(request))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.body)["error_code"], "quota_exhausted")

    def test_approval_route_propagates_authenticated_tenant(self):
        from data_agent.api.distribution_routes import dreq_approve

        request = MagicMock()
        request.cookies = {}
        request.path_params = {"id": 17}
        user = MagicMock()
        user.identifier = "admin"
        user.metadata = {"role": "admin", "tenant_id": "planning"}
        with (
            patch(
                "data_agent.api.helpers._get_user_from_request",
                return_value=user,
            ),
            patch(
                "data_agent.data_distribution.approve_request",
                return_value={"status": "ok"},
            ) as approve,
        ):
            response = asyncio.run(dreq_approve(request))

        self.assertEqual(response.status_code, 200)
        approve.assert_called_once_with(17, "admin", "planning")

    def test_distribution_routes_include_revocation_and_controlled_download(self):
        from data_agent.api.distribution_routes import get_distribution_routes

        paths = {route.path for route in get_distribution_routes()}
        self.assertIn("/api/data-requests/{id:int}/revoke", paths)
        self.assertIn(
            "/api/distribution-packages/{package_id:str}/download",
            paths,
        )


class TestAddReview(unittest.TestCase):
    def test_invalid_rating(self):
        from data_agent.data_distribution import add_review
        result = add_review(1, "user1", 0)
        self.assertEqual(result["status"], "error")
        result = add_review(1, "user1", 6)
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_distribution import add_review
        result = add_review(1, "user1", 4, "good data")
        self.assertEqual(result["status"], "error")


class TestGetReviews(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_distribution import get_reviews
        self.assertEqual(get_reviews(1), [])


class TestGetAssetRating(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_distribution import get_asset_rating
        result = get_asset_rating(1)
        self.assertEqual(result["avg_rating"], 0)
        self.assertEqual(result["count"], 0)


class TestAccessStats(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_stats_no_db(self, _):
        from data_agent.data_distribution import get_access_stats
        result = get_access_stats()
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_hot_no_db(self, _):
        from data_agent.data_distribution import get_hot_assets
        self.assertEqual(get_hot_assets(), [])


class TestPackageAssets(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_distribution import package_assets
        result = package_assets([1, 2])
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_package_requires_active_grant_for_non_owner(self, mock_eng, _mock_inject):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        grant_result = MagicMock()
        grant_result.fetchone.return_value = None
        conn.execute.side_effect = [
            MagicMock(
                fetchone=MagicMock(
                    return_value=_row(
                        asset_name="districts.gpkg",
                        owner_username="owner",
                        local_path="/data/districts.gpkg",
                    )
                )
            ),
            grant_result,
        ]
        mock_eng.return_value = engine
        role_token = current_user_role.set("analyst")
        try:
            with patch(
                "data_agent.user_context.get_user_upload_dir",
                return_value="/tmp/distribution-test-user",
            ):
                from data_agent.data_distribution import package_assets

                result = package_assets([42], username="analyst")
        finally:
            current_user_role.reset(role_token)

        self.assertEqual(result["error_code"], "access_denied")
        grant_statement = str(conn.execute.call_args_list[1].args[0])
        self.assertIn("expires_at > NOW()", grant_statement)
        self.assertIn("revoked_at IS NULL", grant_statement)

    @patch("data_agent.data_distribution.zipfile.ZipFile")
    @patch("data_agent.data_distribution.os.path.isfile", return_value=True)
    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_active_grant_creates_downloadable_package(
        self,
        mock_eng,
        _mock_inject,
        _mock_isfile,
        mock_zip,
    ):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        grant_result = MagicMock()
        grant_result.fetchone.return_value = _row(
            id=88,
            expires_at=datetime(2099, 9, 1),
            product_tenant_id="planning",
            product_urn="gda://planning/data_product/districts",
            data_product_version_id="3e5b675a-6d82-4e38-9e9b-3c454016c592",
            data_product_version_key="v2.1.0",
            granted_package_quota=3,
        )
        quota_result = MagicMock()
        quota_result.scalar.return_value = 2
        conn.execute.side_effect = [
            MagicMock(
                fetchone=MagicMock(
                    return_value=_row(
                        asset_name="districts.gpkg",
                        owner_username="owner",
                        local_path="/data/districts.gpkg",
                    )
                )
            ),
            grant_result,
            quota_result,
            MagicMock(),
            MagicMock(),
        ]
        mock_eng.return_value = engine
        role_token = current_user_role.set("analyst")
        try:
            with (
                patch(
                    "data_agent.user_context.get_user_upload_dir",
                    return_value="/tmp/distribution-test-user",
                ),
                patch("data_agent.data_distribution.os.makedirs"),
            ):
                from data_agent.data_distribution import package_assets

                result = package_assets([42], username="analyst")
        finally:
            current_user_role.reset(role_token)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(
            result["download_url"].startswith("/api/distribution-packages/")
        )
        mock_zip.return_value.__enter__.return_value.write.assert_called_once_with(
            "/data/districts.gpkg",
            "districts.gpkg",
        )
        manifest_call = mock_zip.return_value.__enter__.return_value.writestr.call_args
        manifest = json.loads(manifest_call.args[1])
        self.assertEqual(manifest["schema"], "gda.asset_distribution_package.v2")
        self.assertEqual(
            manifest["assets"][0]["product_version"]["version_key"],
            "v2.1.0",
        )
        self.assertEqual(
            manifest["assets"][0]["package_quota"],
            {
                "granted": 3,
                "packages_created_before": 2,
                "packages_created_after": 3,
                "packages_remaining_after": 0,
            },
        )

    @patch("data_agent.data_distribution.zipfile.ZipFile")
    @patch("data_agent.data_distribution.os.path.isfile", return_value=True)
    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_package_rejects_after_quota_is_exhausted_under_grant_lock(
        self,
        mock_eng,
        _mock_inject,
        _mock_isfile,
        mock_zip,
    ):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        grant_result = MagicMock()
        grant_result.fetchone.return_value = _row(
            id=88,
            expires_at=datetime(2099, 9, 1),
            granted_package_quota=2,
        )
        quota_result = MagicMock()
        quota_result.scalar.return_value = 2
        conn.execute.side_effect = [
            MagicMock(
                fetchone=MagicMock(
                    return_value=_row(
                        asset_name="districts.gpkg",
                        owner_username="owner",
                        local_path="/data/districts.gpkg",
                    )
                )
            ),
            grant_result,
            quota_result,
        ]
        mock_eng.return_value = engine
        role_token = current_user_role.set("analyst")
        try:
            with (
                patch(
                    "data_agent.user_context.get_user_upload_dir",
                    return_value="/tmp/distribution-test-user",
                ),
                patch("data_agent.data_distribution.os.makedirs"),
            ):
                from data_agent.data_distribution import package_assets

                result = package_assets([42], username="analyst")
        finally:
            current_user_role.reset(role_token)

        self.assertEqual(result["error_code"], "quota_exhausted")
        self.assertEqual(result["packages_created"], 2)
        self.assertEqual(result["packages_remaining"], 0)
        self.assertIn("FOR UPDATE", str(conn.execute.call_args_list[1].args[0]))
        self.assertIn(
            "COUNT(DISTINCT package_id)",
            str(conn.execute.call_args_list[2].args[0]),
        )
        conn.commit.assert_not_called()
        mock_zip.assert_not_called()

    @patch("data_agent.data_distribution.os.path.isfile", return_value=True)
    @patch("data_agent.data_distribution._package_path_is_valid", return_value=True)
    @patch("data_agent.data_distribution._inject_user_context")
    @patch("data_agent.data_distribution.get_engine")
    def test_package_download_fails_closed_after_grant_invalidation(
        self,
        mock_eng,
        _mock_inject,
        _mock_valid_path,
        _mock_isfile,
    ):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = None
        mock_eng.return_value = engine

        from data_agent.data_distribution import get_distribution_package

        result = get_distribution_package(
            "3e5b675a-6d82-4e38-9e9b-3c454016c592",
            "analyst",
        )

        self.assertEqual(result["error_code"], "package_not_found")
        statement = str(conn.execute.call_args.args[0])
        self.assertIn("request.revoked_at IS NOT NULL", statement)


class TestConstants(unittest.TestCase):
    def test_valid_status(self):
        from data_agent.data_distribution import VALID_REQUEST_STATUS
        self.assertIn("pending", VALID_REQUEST_STATUS)
        self.assertIn("approved", VALID_REQUEST_STATUS)
        self.assertIn("rejected", VALID_REQUEST_STATUS)


def test_asset_distribution_grant_migration_is_bounded_and_transitional():
    root = Path(__file__).resolve().parents[1]
    migration = (
        root / "data_agent/migrations/105_asset_distribution_grant.sql"
    ).read_text(encoding="utf-8")

    assert "ALTER TABLE agent_data_requests" in migration
    assert "requested_duration_days BETWEEN 1 AND 365" in migration
    assert "granted_operations" in migration
    assert "expires_at > approved_at" in migration
    assert "ConsumerBinding" in migration


def test_version_locked_grant_migration_binds_versions_and_invalidates_packages():
    root = Path(__file__).resolve().parents[1]
    migration = (
        root / "data_agent/migrations/106_version_locked_distribution_grant.sql"
    ).read_text(encoding="utf-8")

    assert "fk_dreq_data_product_version" in migration
    assert "data_product_version_id" in migration
    assert "revoked_at" in migration
    assert "agent_distribution_packages" in migration
    assert "agent_distribution_package_items" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration


def test_distribution_grant_quota_migration_is_bounded_and_auditable():
    root = Path(__file__).resolve().parents[1]
    migration = (
        root / "data_agent/migrations/107_distribution_grant_package_quota.sql"
    ).read_text(encoding="utf-8")

    assert "requested_package_quota BETWEEN 1 AND 100" in migration
    assert "granted_package_quota BETWEEN 1 AND 100" in migration
    assert "status = 'approved'" in migration
    assert "agent_distribution_package_items" in migration


if __name__ == "__main__":
    unittest.main()

"""Unit and API contract tests for dynamic platform branding."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_agent.platform_branding import (
    DEFAULT_PLATFORM_NAME,
    BrandingStoreUnavailable,
    BrandingValidationError,
    PlatformBranding,
    get_platform_branding,
    update_platform_branding,
    validate_branding,
)


def _run(coro):
    return asyncio.run(coro)


def _request(body=None):
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    request.client = MagicMock(host="127.0.0.1")
    return request


def test_validate_branding_normalizes_whitespace():
    values = validate_branding(
        {
            "platform_name": "  宁夏时空数据智能平台  ",
            "platform_subtitle": "  自然资源时空数据底座  ",
        }
    )
    assert values == {
        "platform_name": "宁夏时空数据智能平台",
        "platform_subtitle": "自然资源时空数据底座",
    }


@pytest.mark.parametrize(
    "name",
    ["", "A", "x" * 81, "无效\n名称"],
)
def test_validate_branding_rejects_invalid_name(name):
    with pytest.raises(BrandingValidationError):
        validate_branding(
            {"platform_name": name, "platform_subtitle": "有效副标题"}
        )


@patch("data_agent.platform_branding.get_engine", return_value=None)
def test_public_branding_falls_back_to_defaults(_engine):
    assert get_platform_branding().platform_name == DEFAULT_PLATFORM_NAME


@patch("data_agent.platform_branding.get_engine")
def test_public_branding_reads_persistent_values(engine):
    updated_at = datetime(2026, 8, 5, 1, 2, tzinfo=UTC)
    rows = [
        {
            "setting_key": "platform_name",
            "setting_value": "宁夏时空数据智能平台",
            "updated_by": "admin",
            "updated_at": updated_at,
        },
        {
            "setting_key": "platform_subtitle",
            "setting_value": "自然资源时空数据智能底座",
            "updated_by": "admin",
            "updated_at": updated_at,
        },
    ]
    connection = engine.return_value.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.all.return_value = rows

    branding = get_platform_branding()

    assert branding.platform_name == "宁夏时空数据智能平台"
    assert branding.platform_subtitle == "自然资源时空数据智能底座"
    assert branding.updated_by == "admin"
    assert branding.updated_at == updated_at.isoformat()


@patch("data_agent.platform_branding.get_engine", return_value=None)
def test_update_requires_persistent_store(_engine):
    with pytest.raises(BrandingStoreUnavailable):
        update_platform_branding(
            {
                "platform_name": "宁夏时空数据智能平台",
                "platform_subtitle": "自然资源时空数据底座",
            },
            updated_by="admin",
        )


@patch("data_agent.platform_branding.get_platform_branding")
def test_public_api_returns_branding(get_branding):
    get_branding.return_value = PlatformBranding(platform_name="测试平台")
    from data_agent.frontend_api import _api_platform_branding

    response = _run(_api_platform_branding(_request()))
    assert response.status_code == 200
    assert json.loads(response.body)["platform_name"] == "测试平台"


@patch("data_agent.frontend_api._get_user_from_request", return_value=None)
def test_admin_update_requires_authentication(_user):
    from data_agent.frontend_api import _api_admin_platform_branding_put

    response = _run(_api_admin_platform_branding_put(_request({})))
    assert response.status_code == 401


@patch("data_agent.frontend_api._get_user_from_request")
def test_admin_update_requires_admin(user):
    user.return_value = {"identifier": "analyst", "metadata": {"role": "analyst"}}
    from data_agent.frontend_api import _api_admin_platform_branding_put

    response = _run(_api_admin_platform_branding_put(_request({})))
    assert response.status_code == 403


@patch("data_agent.frontend_api.record_audit")
@patch("data_agent.platform_branding.update_platform_branding")
@patch("data_agent.frontend_api._get_user_from_request")
def test_admin_update_returns_saved_branding(user, update, audit):
    user.return_value = {"identifier": "admin", "metadata": {"role": "admin"}}
    update.return_value = PlatformBranding(
        platform_name="宁夏时空数据智能平台",
        platform_subtitle="自然资源时空数据底座",
        updated_by="admin",
    )
    from data_agent.frontend_api import _api_admin_platform_branding_put

    response = _run(
        _api_admin_platform_branding_put(
            _request(
                {
                    "platform_name": "宁夏时空数据智能平台",
                    "platform_subtitle": "自然资源时空数据底座",
                }
            )
        )
    )
    assert response.status_code == 200
    assert json.loads(response.body)["platform_name"] == "宁夏时空数据智能平台"
    audit.assert_called_once()

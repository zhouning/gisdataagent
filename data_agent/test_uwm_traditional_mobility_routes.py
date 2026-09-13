import json

import pytest
from starlette.requests import Request

from data_agent.api import uwm_traditional_mobility_routes as routes
from data_agent.test_traditional_mobility_accessibility_service import product_dir


def request(path, path_params=None):
    return Request({"type":"http","method":"GET","path":path,"headers":[],"query_string":b"","path_params":path_params or {}})


def auth(monkeypatch, username="analyst"):
    monkeypatch.setattr(routes,"_get_user_from_request",lambda req:{"id":username}); monkeypatch.setattr(routes,"_set_user_context",lambda user:(username,"analyst"))


def methods(items,path): return next(set(item.methods or []) for item in items if item.path==path)


def test_routes_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes
    own=routes.get_uwm_traditional_mobility_routes(); mounted=get_frontend_api_routes()
    for path in ["/api/uwm/traditional-livability/mobility/overview","/api/uwm/traditional-livability/mobility/admin-units","/api/uwm/traditional-livability/mobility/admin-units/{admin_unit_id}","/api/uwm/traditional-livability/mobility/map"]:
        assert "GET" in methods(own,path); assert "GET" in methods(mounted,path)


@pytest.mark.asyncio
async def test_routes_require_auth_and_return_product(tmp_path,monkeypatch):
    monkeypatch.setenv("UWM_TRADITIONAL_MOBILITY_PATH",str(product_dir(tmp_path))); routes._reset_service_cache(); monkeypatch.setattr(routes,"_get_user_from_request",lambda req:None)
    response=await routes.mobility_overview(request("/x")); assert response.status_code==401
    auth(monkeypatch); response=await routes.mobility_overview(request("/x")); assert response.status_code==200; assert json.loads(response.body)["summary"]["admin_unit_count"]==2
    response=await routes.mobility_admin_unit(request("/x",{"admin_unit_id":"A"})); assert response.status_code==200
    response=await routes.mobility_admin_unit(request("/x",{"admin_unit_id":"missing"})); assert response.status_code==404


@pytest.mark.asyncio
async def test_missing_product_returns_503(tmp_path,monkeypatch):
    monkeypatch.setenv("UWM_TRADITIONAL_MOBILITY_PATH",str(tmp_path/"missing")); routes._reset_service_cache(); auth(monkeypatch)
    response=await routes.mobility_overview(request("/x")); assert response.status_code==503

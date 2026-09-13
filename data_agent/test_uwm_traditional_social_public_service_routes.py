import json,pytest
from starlette.requests import Request
from data_agent.api import uwm_traditional_social_public_service_routes as routes
from data_agent.test_traditional_social_public_service_service import product_dir

def request(path,path_params=None,query=b''):return Request({'type':'http','method':'GET','path':path,'headers':[],'query_string':query,'path_params':path_params or {}})
def auth(monkeypatch):monkeypatch.setattr(routes,'_get_user_from_request',lambda req:{'id':'analyst'});monkeypatch.setattr(routes,'_set_user_context',lambda user:('analyst','analyst'))
def methods(items,path):return next(set(item.methods or []) for item in items if item.path==path)
def test_routes_registered_in_frontend_api():
 from data_agent.frontend_api import get_frontend_api_routes
 own=routes.get_uwm_traditional_social_public_service_routes();mounted=get_frontend_api_routes()
 for path in ['/api/uwm/traditional-livability/social-public-service/overview','/api/uwm/traditional-livability/social-public-service/facilities','/api/uwm/traditional-livability/social-public-service/admin-units','/api/uwm/traditional-livability/social-public-service/admin-units/{admin_unit_id}','/api/uwm/traditional-livability/social-public-service/map']:
  assert 'GET' in methods(own,path);assert 'GET' in methods(mounted,path)
@pytest.mark.asyncio
async def test_routes_require_auth_and_filter_views(tmp_path,monkeypatch):
 monkeypatch.setenv('UWM_TRADITIONAL_SOCIAL_PUBLIC_SERVICE_PATH',str(product_dir(tmp_path)));routes._reset_service_cache();monkeypatch.setattr(routes,'_get_user_from_request',lambda req:None)
 assert (await routes.social_public_service_overview(request('/x'))).status_code==401
 auth(monkeypatch);r=await routes.social_public_service_facilities(request('/x',query=b'view=social_infrastructure'));assert r.status_code==200;assert json.loads(r.body)['count']==1
 r=await routes.social_public_service_admin_unit(request('/x',{'admin_unit_id':'500101'},b'view=government_public_service'));assert r.status_code==200
@pytest.mark.asyncio
async def test_missing_product_returns_503(tmp_path,monkeypatch):
 monkeypatch.setenv('UWM_TRADITIONAL_SOCIAL_PUBLIC_SERVICE_PATH',str(tmp_path/'missing'));routes._reset_service_cache();auth(monkeypatch)
 assert (await routes.social_public_service_overview(request('/x'))).status_code==503

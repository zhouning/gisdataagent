import json,pytest
from starlette.requests import Request
from data_agent.api import uwm_traditional_safety_comfort_routes as routes
from data_agent.test_traditional_safety_comfort_service import product_dir
def req(path,params=None):return Request({'type':'http','method':'GET','path':path,'headers':[],'query_string':b'','path_params':params or {}})
def auth(m):m.setattr(routes,'_get_user_from_request',lambda r:{'id':'a'});m.setattr(routes,'_set_user_context',lambda u:('a','analyst'))
def methods(items,path):return next(set(x.methods or []) for x in items if x.path==path)
def test_registered():
 from data_agent.frontend_api import get_frontend_api_routes
 own=routes.get_uwm_traditional_safety_comfort_routes();mounted=get_frontend_api_routes()
 for path in ['/api/uwm/traditional-livability/safety-comfort/overview','/api/uwm/traditional-livability/safety-comfort/admin-units','/api/uwm/traditional-livability/safety-comfort/admin-units/{admin_unit_id}','/api/uwm/traditional-livability/safety-comfort/evidence-sources','/api/uwm/traditional-livability/safety-comfort/map']:
  assert 'GET' in methods(own,path);assert 'GET' in methods(mounted,path)
@pytest.mark.asyncio
async def test_auth_and_product(tmp_path,monkeypatch):
 monkeypatch.setenv('UWM_TRADITIONAL_SAFETY_COMFORT_PATH',str(product_dir(tmp_path)));routes._reset_service_cache();monkeypatch.setattr(routes,'_get_user_from_request',lambda r:None);assert (await routes.safety_comfort_overview(req('/x'))).status_code==401;auth(monkeypatch);r=await routes.safety_comfort_evidence_sources(req('/x'));assert r.status_code==200 and json.loads(r.body)['count']==3
@pytest.mark.asyncio
async def test_missing_product_503(tmp_path,monkeypatch):
 monkeypatch.setenv('UWM_TRADITIONAL_SAFETY_COMFORT_PATH',str(tmp_path/'missing'));routes._reset_service_cache();auth(monkeypatch);assert (await routes.safety_comfort_overview(req('/x'))).status_code==503

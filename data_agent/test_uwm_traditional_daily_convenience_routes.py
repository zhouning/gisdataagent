import json,pytest
from starlette.requests import Request
from data_agent.api import uwm_traditional_daily_convenience_routes as routes
from data_agent.test_traditional_daily_convenience_service import product_dir
def req(path,params=None,q=b''):return Request({'type':'http','method':'GET','path':path,'headers':[],'query_string':q,'path_params':params or {}})
def auth(m):m.setattr(routes,'_get_user_from_request',lambda r:{'id':'a'});m.setattr(routes,'_set_user_context',lambda u:('a','analyst'))
def methods(items,path):return next(set(x.methods or []) for x in items if x.path==path)
def test_registered():
 from data_agent.frontend_api import get_frontend_api_routes
 own=routes.get_uwm_traditional_daily_convenience_routes();mounted=get_frontend_api_routes()
 for path in ['/api/uwm/traditional-livability/daily-convenience/overview','/api/uwm/traditional-livability/daily-convenience/places','/api/uwm/traditional-livability/daily-convenience/admin-units','/api/uwm/traditional-livability/daily-convenience/admin-units/{admin_unit_id}','/api/uwm/traditional-livability/daily-convenience/map']:
  assert 'GET' in methods(own,path);assert 'GET' in methods(mounted,path)
@pytest.mark.asyncio
async def test_auth_and_view(tmp_path,monkeypatch):
 monkeypatch.setenv('UWM_TRADITIONAL_DAILY_CONVENIENCE_PATH',str(product_dir(tmp_path)));routes._reset_service_cache();monkeypatch.setattr(routes,'_get_user_from_request',lambda r:None);assert (await routes.daily_convenience_overview(req('/x'))).status_code==401;auth(monkeypatch);r=await routes.daily_convenience_places(req('/x',q=b'view=business_activity_evidence'));assert r.status_code==200 and json.loads(r.body)['count']==1
@pytest.mark.asyncio
async def test_missing_503(tmp_path,monkeypatch):
 monkeypatch.setenv('UWM_TRADITIONAL_DAILY_CONVENIENCE_PATH',str(tmp_path/'missing'));routes._reset_service_cache();auth(monkeypatch);assert (await routes.daily_convenience_overview(req('/x'))).status_code==503

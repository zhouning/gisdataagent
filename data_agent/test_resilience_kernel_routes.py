import json

import pytest
from starlette.requests import Request

from data_agent.api import uwm_resilience_kernel_routes as routes

TARGET = '江北区|观音桥街道|653'


def request(path, method='GET', payload=None, path_params=None):
    body = json.dumps(payload or {}).encode()
    sent = False
    async def receive():
        nonlocal sent
        if sent:
            return {'type': 'http.disconnect'}
        sent = True
        return {'type': 'http.request', 'body': body, 'more_body': False}
    return Request({'type': 'http', 'method': method, 'path': path, 'headers': [(b'content-type', b'application/json')], 'query_string': b'', 'path_params': path_params or {}}, receive)


def auth(monkeypatch):
    monkeypatch.setattr(routes, '_get_user_from_request', lambda req: {'id': 'resilience-planner'})
    monkeypatch.setattr(routes, '_set_user_context', lambda user: ('resilience-planner', 'analyst'))


@pytest.mark.asyncio
async def test_resilience_routes_are_mounted_and_auth_protected(monkeypatch):
    from data_agent.frontend_api import get_frontend_api_routes
    mounted = {(route.path, method) for route in get_frontend_api_routes() for method in (getattr(route, 'methods', None) or [])}
    for path, method in [
        ('/api/uwm/resilience-kernel/nodes', 'GET'),
        ('/api/uwm/resilience-kernel/nodes/{node_id}', 'GET'),
        ('/api/uwm/resilience-kernel/scenario-readiness', 'POST'),
    ]:
        assert (path, method) in mounted
    monkeypatch.setattr(routes, '_get_user_from_request', lambda req: None)
    response = await routes.nodes(request('/x'))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_real_node_detail_map_and_fail_closed_scenario(monkeypatch):
    auth(monkeypatch)
    routes._reset_service_cache()
    response = await routes.nodes(request('/x'))
    nodes = json.loads(response.body)
    assert response.status_code == 200
    assert nodes['total'] == 1017
    assert any(item['node_id'] == TARGET for item in nodes['nodes']) is False
    response = await routes.node_detail(request('/x', path_params={'node_id': TARGET}))
    detail = json.loads(response.body)
    assert response.status_code == 200
    assert detail['geometry_available'] is True
    assert len(detail['map_payload']['layers'][0]['geojsonData']['features']) == 1
    response = await routes.scenario_readiness(request('/x', 'POST', {'node_id': TARGET, 'hazard_type': 'flood', 'intervention_type': 'evacuation_route'}))
    scenario = json.loads(response.body)
    assert response.status_code == 200
    assert scenario['status'] == 'blocked'
    assert scenario['reason'] == 'resilience_dynamic_mechanisms_uncalibrated'
    assert 'authoritative_hazard_event_timeseries_missing' in scenario['required_evidence']
    assert '灾害传播系数' in scenario['claim_boundary']

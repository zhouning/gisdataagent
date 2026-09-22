from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.testclient import TestClient

import data_agent.abu_dhabi_rdf_workflow_service as service
import data_agent.api.abu_dhabi_flood_routes as routes


MINIMAL_INP = """[OPTIONS]
FLOW_UNITS LPS
[JUNCTIONS]
CB-1 0 2 0 0 0
[OUTFALLS]
OF-1 0 FREE NO
[CONDUITS]
CO-1 CB-1 OF-1 10 0.01 0 0 0
[PUMPS]
PU-1 CB-1 OF-1 PC-1 ON 0
[XSECTIONS]
CO-1 CIRCULAR 1 0 0 0 1
[INFLOWS]
CB-1 FLOW TS-1 FLOW 1 1 0
[TIMESERIES]
TS-1 01/01/2026 00:00 0.1
[COORDINATES]
CB-1 230735.267 2705608.894
OF-1 230800.267 2705668.894
"""


MINIMAL_RPT = """EPA STORM WATER MANAGEMENT MODEL - VERSION 5.2 (Build 5.2.4)
  Flow Units ............... LPS
  Flow Routing Method ...... DYNWAVE
  Flow Routing Continuity        hectare-m      10^6 ltr
  External Outflow .........         5.264        52.641
  Flooding Loss ............         9.747        97.476
  Continuity Error (%) .....        -1.458
  Highest Continuity Errors
  % of Steps Not Converging   :     1.25
  Node Depth Summary
  ---------------------------------------------------------------------
  CB-1 JUNCTION 0.06 0.64 2.09 0 11:45 0.56
  OF-1 OUTFALL 0.01 0.02 0.02 0 11:40 0.02
  Node Inflow Summary
  Node Flooding Summary
  ---------------------------------------------------------------------
  CB-1 0.50 0.12 0 11:45 0.21 0.0
  Storage Volume Summary
"""


class ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)
        return SimpleNamespace(done=lambda: True)


def _configure(tmp_path, monkeypatch):
    source = tmp_path / "RD F.inp"
    source.write_text(MINIMAL_INP, encoding="utf-8")
    executable = tmp_path / "runswmm"
    executable.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("ABU_DHABI_RDF_INPUT", str(source))
    monkeypatch.setenv("ABU_DHABI_RDF_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("ABU_DHABI_RDF_SWMM_EXECUTABLE", str(executable))
    service._scan_cached.cache_clear()
    service._map_payload_cached.cache_clear()
    service._RUNS.clear()
    service._ACTIVE_RUN_ID = None


def test_rdf_preflight_preserves_external_inflow_contract(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    source = service.inspect_source()
    workflow = service.workflow_status()

    assert source["source_ready"] is True
    assert source["external_inflow_driven"] is True
    assert source["missing_inflow_series_count"] == 0
    assert source["sections"]["[JUNCTIONS]"] == 1
    assert workflow["stage_count"] == 5
    assert workflow["stages"][0]["status"] == "ready"
    assert workflow["stages"][1]["status"] == "partial"


def test_rdf_native_run_writes_audited_receipt_and_map(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    def fake_run(arguments, **_kwargs):
        report_path = arguments[2]
        output_path = arguments[3]
        report_path.write_text(MINIMAL_RPT, encoding="utf-8")
        output_path.write_bytes(b"swmm-out")
        return SimpleNamespace(returncode=0, stdout="fixture completed")

    monkeypatch.setattr(service, "_EXECUTOR", ImmediateExecutor())
    monkeypatch.setattr(service.subprocess, "run", fake_run)

    queued = service.start_baseline_run()
    completed = service.public_run(queued["run_id"])
    result_map = service.run_map_payload(queued["run_id"])

    assert completed["status"] == "completed"
    assert completed["summary"]["routing_continuity_error_percent"] == -1.458
    assert completed["summary"]["external_outflow_million_litres"] == 52.641
    assert completed["summary"]["nonconverging_steps_percent"] == 1.25
    assert completed["summary"]["quality"]["passed"] is True
    assert completed["artifacts"]["input_snapshot"]["sha256"] == queued["source"]["sha256"]
    assert result_map["metadata"]["feature_count"] == 2
    assert result_map["features"][0]["properties"]["model_scope"] == "RD F local network"


def test_rdf_routes_are_authenticated_and_expose_workflow(monkeypatch):
    monkeypatch.setattr(
        routes,
        "_get_user_from_request",
        lambda request: SimpleNamespace(identifier="test-analyst", metadata={"role": "analyst"}),
    )
    monkeypatch.setattr(routes, "_set_user_context", lambda user: None)
    monkeypatch.setattr(
        service,
        "workflow_status",
        lambda: {
            "schema": service.RDF_WORKFLOW_SCHEMA,
            "status": "partial",
            "source": {"filename": "RD F.inp", "source_ready": True},
            "latest_run": None,
            "stages": [{"key": str(index)} for index in range(5)],
            "ready_stage_count": 1,
            "stage_count": 5,
        },
    )
    client = TestClient(Starlette(routes=routes.get_abu_dhabi_flood_routes()))

    response = client.get("/api/abu-dhabi/flood/rd-f/workflow")

    assert response.status_code == 200
    assert response.json()["source"]["filename"] == "RD F.inp"
    assert response.json()["stage_count"] == 5


def test_rdf_route_contract_has_no_duplicate_registrations():
    route_contracts = [
        (route.path, tuple(sorted(route.methods or ())))
        for route in routes.get_abu_dhabi_flood_routes()
        if "/rd-f/" in route.path
    ]

    assert route_contracts == [
        ("/api/abu-dhabi/flood/rd-f/workflow", ("GET", "HEAD")),
        ("/api/abu-dhabi/flood/rd-f/runs", ("POST",)),
        ("/api/abu-dhabi/flood/rd-f/runs/{run_id}", ("GET", "HEAD")),
        ("/api/abu-dhabi/flood/rd-f/runs/{run_id}/map", ("GET", "HEAD")),
    ]

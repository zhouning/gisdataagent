"""Opt-in real PostGIS acceptance for the multi-step GIS workflow."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text

from data_agent.api import gis_analysis_routes
from data_agent.gis_analysis_execution import GISAnalysisPlanner
from data_agent.gis_workflow import GISWorkflowPlanner, PostGISWorkflowProvider
from data_agent.gis_workflow_proposal import GISWorkflowProposalPlanner
from data_agent.platform_contracts import SubjectContext, SubjectType
from data_agent.test_gis_analysis_routes import _request, _user
from data_agent.test_gis_workflow import (
    _Authority,
    _Gateway,
    _planning_zone_preview_request,
    _preview_request,
)
from data_agent.test_gis_workflow_proposal import (
    QUESTION,
    _configure_llm,
    _llm_evidence,
    _supported_payload,
)

POSTGIS_URL = os.getenv("GDA_GIS_WORKFLOW_INTEGRATION_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGIS_URL,
    reason="GDA_GIS_WORKFLOW_INTEGRATION_DATABASE_URL is not configured",
)

_RELATIONS = (
    "parcel_current",
    "synthetic_eco_redline",
    "road_network",
    "admin_units",
    "synthetic_planning_zones",
)


def _workflow_planner() -> GISWorkflowPlanner:
    authority = _Authority()
    gateway = _Gateway(authority)
    return GISWorkflowPlanner(
        source_authority=authority,
        gateway=gateway,
        gis_planner=GISAnalysisPlanner(authority, gateway),
    )


def _drop_fixture(engine) -> None:
    with engine.begin() as connection:
        for relation in _RELATIONS:
            connection.execute(text(f'DROP TABLE IF EXISTS "{relation}"'))


def _install_fixture(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    _drop_fixture(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE parcel_current ("
                "parcel_id text PRIMARY KEY, land_use_code text NOT NULL, "
                "land_use_name text NOT NULL, geom geometry(Polygon, 4326) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE synthetic_eco_redline ("
                "redline_id text PRIMARY KEY, geom geometry(Polygon, 4326) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE road_network ("
                "road_id text PRIMARY KEY, geom geometry(LineString, 4326) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE admin_units ("
                "admin_code text PRIMARY KEY, admin_name text NOT NULL, "
                "geom geometry(Polygon, 4326) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE synthetic_planning_zones ("
                "zone_code text PRIMARY KEY, zone_name text NOT NULL, "
                "geom geometry(Polygon, 4326) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO parcel_current VALUES "
                "('eligible', '0101', '水田', ST_GeomFromText("
                "'POLYGON((106.000 29.000,106.010 29.000,106.010 29.010,"
                "106.000 29.010,106.000 29.000))',4326)),"
                "('far_from_road', '0201', '果园', ST_GeomFromText("
                "'POLYGON((106.040 29.000,106.050 29.000,106.050 29.010,"
                "106.040 29.010,106.040 29.000))',4326)),"
                "('outside_redline', '0301', '林地', ST_GeomFromText("
                "'POLYGON((106.080 29.000,106.090 29.000,106.090 29.010,"
                "106.080 29.010,106.080 29.000))',4326))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO synthetic_eco_redline VALUES "
                "('redline-1', ST_GeomFromText("
                "'POLYGON((105.995 28.995,106.060 28.995,106.060 29.020,"
                "105.995 29.020,105.995 28.995))',4326))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO road_network VALUES "
                "('road-1', ST_GeomFromText("
                "'LINESTRING(105.999 29.005,106.001 29.005)',4326))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO admin_units VALUES "
                "('A', '东区', ST_GeomFromText("
                "'POLYGON((105.990 28.990,106.006 28.990,106.006 29.020,"
                "105.990 29.020,105.990 28.990))',4326)),"
                "('B', '西区', ST_GeomFromText("
                "'POLYGON((106.006 28.990,106.100 28.990,106.100 29.020,"
                "106.006 29.020,106.006 28.990))',4326))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO synthetic_planning_zones VALUES "
                "('Z1', '重点发展区', ST_GeomFromText("
                "'POLYGON((105.995 28.995,106.030 28.995,106.030 29.020,"
                "105.995 29.020,105.995 28.995))',4326)),"
                "('Z2', '生态协调区', ST_GeomFromText("
                "'POLYGON((106.030 28.995,106.100 28.995,106.100 29.020,"
                "106.030 29.020,106.030 28.995))',4326))"
            )
        )


def test_workflow_executes_as_read_only_map_table_and_evidence_result() -> None:
    assert POSTGIS_URL is not None
    engine = create_engine(POSTGIS_URL, pool_pre_ping=True)
    planner = _workflow_planner()
    subject = SubjectContext(
        tenant_id="tenant-a",
        subject_id="integration-analyst",
        subject_type=SubjectType.HUMAN,
        roles=("analyst",),
        purpose="gis_workflow_acceptance",
    )
    preview = planner.preview(
        _preview_request(),
        subject,
        planned_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    assert preview.plan is not None

    try:
        _install_fixture(engine)
        result = PostGISWorkflowProvider(engine).execute(preview.plan)

        assert result.geojson["type"] == "FeatureCollection"
        assert {
            feature["properties"]["parcel_id"]
            for feature in result.geojson["features"]
        } == {"eligible"}
        assert {item.admin_code for item in result.statistics} == {"A", "B"}
        assert result.summary["eligible_parcel_count"] == 1
        assert result.summary["admin_unit_count"] == 2
        assert result.summary["total_allocated_area_m2"] > 6_666
        assert result.map_update["layers"][0]["geojsonData"] == result.geojson
        assert result.evidence.transaction_read_only is True
        assert result.evidence.transaction_isolation == "repeatable read"
        assert result.evidence.plan_fingerprint == preview.plan_fingerprint
        assert len(result.evidence.source_resource_versions) == 4
        assert len(result.evidence.algorithm_spec_fingerprints) == 5
    finally:
        _drop_fixture(engine)
        engine.dispose()


def test_planning_zone_workflow_executes_real_spatial_grouping() -> None:
    assert POSTGIS_URL is not None
    engine = create_engine(POSTGIS_URL, pool_pre_ping=True)
    authority = _Authority(("parcel_current", "synthetic_planning_zones"))
    gateway = _Gateway(authority)
    planner = GISWorkflowPlanner(
        source_authority=authority,
        gateway=gateway,
        gis_planner=GISAnalysisPlanner(authority, gateway),
    )
    subject = SubjectContext(
        tenant_id="tenant-a",
        subject_id="integration-analyst",
        subject_type=SubjectType.HUMAN,
        roles=("analyst",),
        purpose="gis_workflow_acceptance",
    )
    preview = planner.preview(
        _planning_zone_preview_request(),
        subject,
        planned_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    assert preview.plan is not None

    try:
        _install_fixture(engine)
        result = PostGISWorkflowProvider(engine).execute(preview.plan)

        assert result.summary["parcel_count"] == 3
        assert result.summary["planning_zone_count"] == 2
        assert result.summary["land_use_category_count"] == 3
        assert {item.zone_code for item in result.statistics} == {"Z1", "Z2"}
        assert {item.land_use_code for item in result.statistics} == {
            "0101",
            "0201",
            "0301",
        }
        assert all(
            item.statistic_type == "planning_zone_land_use"
            for item in result.statistics
        )
        assert len(result.evidence.source_resource_versions) == 2
        assert len(result.evidence.algorithm_spec_fingerprints) == 2
    finally:
        _drop_fixture(engine)
        engine.dispose()


@pytest.mark.asyncio
async def test_proposal_preview_execute_api_closes_on_real_postgis(monkeypatch) -> None:
    assert POSTGIS_URL is not None
    engine = create_engine(POSTGIS_URL, pool_pre_ping=True)
    planner = _workflow_planner()
    _configure_llm(monkeypatch)
    monkeypatch.setattr(gis_analysis_routes, "_get_user_from_request", lambda _: _user())
    monkeypatch.setattr(gis_analysis_routes, "_workflow_planner", lambda: planner)
    monkeypatch.setattr(gis_analysis_routes, "get_engine", lambda: engine)
    monkeypatch.setattr(
        gis_analysis_routes,
        "_workflow_proposal_planner",
        lambda: GISWorkflowProposalPlanner(
            lambda **_: (json.dumps(_supported_payload()), _llm_evidence())
        ),
    )

    try:
        _install_fixture(engine)
        proposal_response = await gis_analysis_routes.propose_gis_workflow(
            _request(
                "/api/platform/v1/gis-workflows/proposals",
                body={"question": QUESTION},
            )
        )
        proposal = json.loads(proposal_response.body)["data"]
        preview_body = {
            "question": QUESTION,
            "proposal": proposal["proposal"],
            "question_sha256": proposal["question_sha256"],
            "proposal_fingerprint": proposal["proposal_fingerprint"],
            "proposal_attestation": proposal["proposal_attestation"],
            "planner_evidence": proposal["evidence"],
            "redline_relation": "intersects",
            "area_basis": "clipped_result",
            "road_distance_basis": "geometry_boundary",
            "output_crs": "EPSG:4326",
            "source_names": {},
            "fields": {},
        }
        preview_response = await gis_analysis_routes.preview_gis_workflow(
            _request(
                "/api/platform/v1/gis-workflows/preview",
                body=preview_body,
            )
        )
        preview = json.loads(preview_response.body)["data"]
        execute_response = await gis_analysis_routes.execute_gis_workflow(
            _request(
                "/api/platform/v1/gis-workflows/execute",
                body={
                    **preview_body,
                    "confirmed_plan_fingerprint": preview["plan_fingerprint"],
                    "confirm_assumptions": True,
                },
            )
        )
        result = json.loads(execute_response.body)["data"]

        assert proposal_response.status_code == 200
        assert proposal["evidence"]["mode"] == "llm"
        assert preview_response.status_code == 200
        assert preview["executable"] is True
        assert execute_response.status_code == 200
        assert result["summary"]["eligible_parcel_count"] == 1
        assert result["summary"]["admin_unit_count"] == 2
        assert result["evidence"]["transaction_read_only"] is True
        assert result["evidence"]["plan_fingerprint"] == preview["plan_fingerprint"]
    finally:
        _drop_fixture(engine)
        engine.dispose()

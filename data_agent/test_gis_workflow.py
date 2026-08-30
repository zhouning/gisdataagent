"""Contract tests for the user-visible multi-step GIS workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from data_agent.gis_analysis_execution import GISAnalysisPlanner
from data_agent.gis_workflow import (
    GISWorkflowAreaBasis,
    GISWorkflowExecuteRequest,
    GISWorkflowPlanner,
    GISWorkflowPreviewRequest,
    GISWorkflowRedlineRelation,
    GISWorkflowRoadDistanceBasis,
    GISWorkflowSourceRole,
    GISWorkflowUnavailableError,
    PostGISWorkflowProvider,
)
from data_agent.gis_workflow_proposal import (
    GISWorkflowPlannerEvidence,
    GISWorkflowPlannerMode,
    GISWorkflowProposalEnvelope,
    deterministic_gis_workflow_proposal,
)
from data_agent.nl2sql_source_authority import (
    NL2SQLSourceAuthorityUnavailableError,
    NL2SQLSourceBinding,
)
from data_agent.platform_contracts import ResourceVersion, SubjectContext, SubjectType

TENANT = "tenant-a"
NOW = datetime(2026, 8, 13, tzinfo=UTC)
QUESTION = "找出生态红线内、距离道路500米以内、面积大于10亩的地块，并按行政区统计面积"
PLANNING_ZONE_QUESTION = "叠加规划区与现状地块，并按规划区和用地类型统计面积"


def _preview_request(
    question: str = QUESTION,
    **changes,
) -> GISWorkflowPreviewRequest:
    proposal = deterministic_gis_workflow_proposal(question)
    envelope = GISWorkflowProposalEnvelope.create(
        proposal,
        GISWorkflowPlannerEvidence(
            mode=GISWorkflowPlannerMode.DETERMINISTIC_FALLBACK,
            prompt_version="test.deterministic.v1",
            fallback_reason="unit_test",
        ),
        question=question,
    )
    values = {
        "question": question,
        "proposal": envelope.proposal,
        "question_sha256": envelope.question_sha256,
        "proposal_fingerprint": envelope.proposal_fingerprint,
        "proposal_attestation": envelope.proposal_attestation,
        "planner_evidence": envelope.evidence,
        "redline_relation": GISWorkflowRedlineRelation.INTERSECTS,
        "area_basis": GISWorkflowAreaBasis.CLIPPED_RESULT,
        "road_distance_basis": GISWorkflowRoadDistanceBasis.GEOMETRY_BOUNDARY,
    }
    values.update(changes)
    return GISWorkflowPreviewRequest(
        **values,
    )


def _planning_zone_preview_request(**changes) -> GISWorkflowPreviewRequest:
    proposal = deterministic_gis_workflow_proposal(PLANNING_ZONE_QUESTION)
    envelope = GISWorkflowProposalEnvelope.create(
        proposal,
        GISWorkflowPlannerEvidence(
            mode=GISWorkflowPlannerMode.DETERMINISTIC_FALLBACK,
            prompt_version="test.deterministic.v1",
            fallback_reason="unit_test",
        ),
        question=PLANNING_ZONE_QUESTION,
    )
    values = {
        "question": PLANNING_ZONE_QUESTION,
        "proposal": envelope.proposal,
        "question_sha256": envelope.question_sha256,
        "proposal_fingerprint": envelope.proposal_fingerprint,
        "proposal_attestation": envelope.proposal_attestation,
        "planner_evidence": envelope.evidence,
    }
    values.update(changes)
    return GISWorkflowPreviewRequest(**values)


def _subject() -> SubjectContext:
    return SubjectContext(
        tenant_id=TENANT,
        subject_id="analyst",
        subject_type=SubjectType.HUMAN,
        roles=("analyst",),
        purpose="gis_workflow",
    )


def _version(index: int, name: str, columns: tuple[str, ...]) -> ResourceVersion:
    return ResourceVersion(
        tenant_id=TENANT,
        resource_urn=f"gda://{TENANT}/source_snapshot/{name.replace('_', '-')}",
        resource_version_id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
        version_key="2026-08-13",
        content_sha256=f"{index:x}" * 64,
        authority_version_ref={
            "postgis_table": f"public.{name}",
            "source_mode": "immutable_snapshot",
            "immutable_snapshot": True,
            "geometry_column": "geom",
            "srid": 4326,
            "columns": [{"name": column} for column in (*columns, "geom")],
        },
        created_by="workload:ingestion-provider",
        created_at=NOW,
    )


class _Authority:
    def __init__(self, source_names: tuple[str, ...] | None = None):
        names = source_names or (
            "parcel_current",
            "synthetic_eco_redline",
            "road_network",
            "admin_units",
        )
        field_sets = {
            "parcel_current": (
                "parcel_id",
                "land_use_code",
                "land_use_name",
            ),
            "synthetic_eco_redline": ("redline_id",),
            "road_network": ("road_id",),
            "admin_units": ("admin_code", "admin_name"),
            "synthetic_planning_zones": ("zone_code", "zone_name"),
        }
        self.versions = {
            name: _version(index, name, field_sets.get(name, ("id",)))
            for index, name in enumerate(names, start=1)
        }
        self.bindings = {
            name: NL2SQLSourceBinding.create(
                tenant_id=TENANT,
                semantic_source_name=name,
                execution_engine="postgis",
                physical_locator=f"public.{name}",
                source_mode="immutable_snapshot",
                resource_version=version,
            )
            for name, version in self.versions.items()
        }

    def list_active(self, tenant_id, engine):
        assert tenant_id == TENANT and engine == "postgis"
        return tuple(self.bindings.values())

    def resolve(self, tenant_id, semantic_source_name, engine):
        assert tenant_id == TENANT and engine == "postgis"
        return self.bindings[semantic_source_name]


class _Gateway:
    def __init__(self, authority: _Authority):
        self.by_id = {
            version.resource_version_id: version
            for version in authority.versions.values()
        }

    def get_resource_version(self, tenant_id, resource_version_id):
        assert tenant_id == TENANT
        return self.by_id[resource_version_id]


def _planner(authority: _Authority | None = None) -> GISWorkflowPlanner:
    source_authority = authority or _Authority()
    gateway = _Gateway(source_authority)
    return GISWorkflowPlanner(
        source_authority=source_authority,
        gateway=gateway,
        gis_planner=GISAnalysisPlanner(source_authority, gateway),
    )


def test_preview_interprets_units_and_builds_version_bound_five_step_dag() -> None:
    preview = _planner().preview(
        _preview_request(),
        _subject(),
        planned_at=NOW,
    )

    assert preview.status == "ready"
    assert preview.executable is True
    assert preview.plan is not None
    assert preview.plan.intent.distance_meters == 500
    assert preview.plan.intent.minimum_area_m2 == pytest.approx(20_000 / 3)
    assert tuple(step.node_id for step in preview.steps) == (
        "redline_intersection",
        "road_buffer",
        "road_proximity_intersection",
        "area_filter",
        "admin_area_summary",
    )
    assert preview.steps[2].operation == "spatial_filter"
    assert preview.steps[2].algorithm.algorithm_id == "postgis.st_intersects_filter"
    assert tuple(binding.role for binding in preview.plan.sources) == (
        GISWorkflowSourceRole.PARCELS,
        GISWorkflowSourceRole.ECO_REDLINE,
        GISWorkflowSourceRole.ROADS,
        GISWorkflowSourceRole.ADMIN_UNITS,
    )
    assert all(binding.source.version_key == "2026-08-13" for binding in preview.plan.sources)
    assert len(preview.plan_fingerprint or "") == 64


def test_preview_reports_missing_road_source_instead_of_inventing_data() -> None:
    preview = _planner(
        _Authority(("parcel_current", "synthetic_eco_redline", "admin_units"))
    ).preview(_preview_request(), _subject(), planned_at=NOW)

    assert preview.status == "blocked"
    assert preview.plan is None
    assert any(
        blocker.role is GISWorkflowSourceRole.ROADS
        and blocker.code == "workflow_source_missing"
        for blocker in preview.blockers
    )


def test_preview_reports_unverified_business_fields_as_blockers() -> None:
    authority = _Authority()
    admin_version = authority.versions["admin_units"]
    authority.versions["admin_units"] = admin_version.model_copy(
        update={
            "authority_version_ref": {
                **admin_version.authority_version_ref,
                "columns": [{"name": "geom"}],
            }
        }
    )
    authority.bindings["admin_units"] = NL2SQLSourceBinding.create(
        tenant_id=TENANT,
        semantic_source_name="admin_units",
        execution_engine="postgis",
        physical_locator="public.admin_units",
        source_mode="immutable_snapshot",
        resource_version=authority.versions["admin_units"],
    )
    gateway = _Gateway(authority)
    planner = GISWorkflowPlanner(
        source_authority=authority,
        gateway=gateway,
        gis_planner=GISAnalysisPlanner(authority, gateway),
    )

    preview = planner.preview(
        _preview_request(), _subject(), planned_at=NOW
    )

    assert preview.status == "blocked"
    missing = {
        blocker.field
        for blocker in preview.blockers
        if blocker.code == "workflow_field_missing"
    }
    assert missing == {"admin_code", "admin_name"}


def test_source_authority_outage_is_reported_as_workflow_unavailable() -> None:
    class UnavailableAuthority:
        def list_active(self, tenant_id, engine):
            raise NL2SQLSourceAuthorityUnavailableError("source authority unavailable")

    planner = GISWorkflowPlanner(
        source_authority=UnavailableAuthority(),
        gateway=SimpleGateway(),
    )

    with pytest.raises(
        GISWorkflowUnavailableError, match="source authority unavailable"
    ) as failure:
        planner.preview(_preview_request(), _subject())
    assert failure.value.code == "gis_workflow_unavailable"


class SimpleGateway:
    pass


def test_plan_fingerprint_changes_for_semantic_assumptions_but_not_preview_time() -> None:
    planner = _planner()
    first = planner.preview(
        _preview_request(), _subject(), planned_at=NOW
    )
    replay = planner.preview(
        _preview_request(),
        _subject(),
        planned_at=NOW.replace(hour=12),
    )
    changed = planner.preview(
        _preview_request(
            redline_relation=GISWorkflowRedlineRelation.COVERED_BY,
            area_basis=GISWorkflowAreaBasis.ORIGINAL_PARCEL,
        ),
        _subject(),
        planned_at=NOW,
    )

    assert first.plan_fingerprint == replay.plan_fingerprint
    assert first.plan_fingerprint != changed.plan_fingerprint
    assert len(changed.assumptions) == 4


def test_execute_contract_requires_explicit_assumption_confirmation() -> None:
    preview = _planner().preview(
        _preview_request(), _subject(), planned_at=NOW
    )
    request = GISWorkflowExecuteRequest(
        **_preview_request().model_dump(),
        confirmed_plan_fingerprint=preview.plan_fingerprint,
        confirm_assumptions=True,
    )
    assert request.confirm_assumptions is True


def test_preview_contract_rejects_forged_planner_evidence() -> None:
    document = _preview_request().model_dump(mode="json")
    document["planner_evidence"]["model"] = "forged-model"

    with pytest.raises(ValidationError, match="attestation is invalid"):
        GISWorkflowPreviewRequest.model_validate(document)


def test_postgis_compiler_uses_bound_identifiers_and_parameters() -> None:
    preview = _planner().preview(
        _preview_request(), _subject(), planned_at=NOW
    )
    assert preview.plan is not None
    provider = PostGISWorkflowProvider(create_engine("postgresql+psycopg2://"))

    result_sql, statistics_sql, parameters = provider._queries(preview.plan)

    assert "ST_Buffer" in result_sql
    assert "ST_Intersection" in result_sql
    assert "ST_Area" in result_sql
    assert "GROUP BY admin_code, admin_name" in statistics_sql
    assert parameters == {
        "output_srid": 4326,
        "distance_meters": 500,
        "minimum_area_m2": pytest.approx(20_000 / 3),
    }
    assert ":distance_meters" in result_sql
    assert ":minimum_area_m2" in result_sql
    assert "CAST(:output_srid AS integer)" in result_sql
    assert "ST_Buffer(ST_Transform(geom, 4326)::geography, 500)" not in result_sql
    assert ";" not in result_sql


def test_planning_zone_preview_builds_two_step_template_without_parcel_assumptions() -> None:
    authority = _Authority(("parcel_current", "synthetic_planning_zones"))
    preview = _planner(authority).preview(
        _planning_zone_preview_request(),
        _subject(),
        planned_at=NOW,
    )

    assert preview.status == "ready"
    assert preview.plan is not None
    assert preview.plan.intent.template_id == "planning-zone-land-use-summary.v1"
    assert preview.plan.intent.group_by == "planning_zone_land_use"
    assert preview.assumptions == ()
    assert tuple(binding.role for binding in preview.plan.sources) == (
        GISWorkflowSourceRole.PARCELS,
        GISWorkflowSourceRole.PLANNING_ZONES,
    )
    assert tuple(step.node_id for step in preview.steps) == (
        "planning_zone_land_use_intersection",
        "planning_zone_land_use_summary",
    )
    assert preview.steps[-1].operation == "land_use_spatial_group_by"
    assert preview.plan.redline_relation is None
    assert preview.plan.area_basis is None
    assert preview.plan.road_distance_basis is None


def test_planning_zone_preview_reports_only_template_sources_and_fields() -> None:
    authority = _Authority(("parcel_current",))
    preview = _planner(authority).preview(
        _planning_zone_preview_request(), _subject(), planned_at=NOW
    )

    assert preview.status == "blocked"
    assert {blocker.role for blocker in preview.blockers} == {
        GISWorkflowSourceRole.PLANNING_ZONES
    }

    authority = _Authority(("parcel_current", "synthetic_planning_zones"))
    parcel_version = authority.versions["parcel_current"]
    authority.versions["parcel_current"] = parcel_version.model_copy(
        update={
            "authority_version_ref": {
                **parcel_version.authority_version_ref,
                "columns": [{"name": "parcel_id"}, {"name": "geom"}],
            }
        }
    )
    authority.bindings["parcel_current"] = NL2SQLSourceBinding.create(
        tenant_id=TENANT,
        semantic_source_name="parcel_current",
        execution_engine="postgis",
        physical_locator="public.parcel_current",
        source_mode="immutable_snapshot",
        resource_version=authority.versions["parcel_current"],
    )
    preview = _planner(authority).preview(
        _planning_zone_preview_request(), _subject(), planned_at=NOW
    )

    assert preview.status == "blocked"
    assert {
        blocker.field
        for blocker in preview.blockers
        if blocker.code == "workflow_field_missing"
    } == {"land_use_code", "land_use_name"}


def test_planning_zone_plan_fingerprint_is_stable_and_sql_is_template_specific() -> None:
    planner = _planner(_Authority(("parcel_current", "synthetic_planning_zones")))
    first = planner.preview(
        _planning_zone_preview_request(), _subject(), planned_at=NOW
    )
    replay = planner.preview(
        _planning_zone_preview_request(), _subject(), planned_at=NOW.replace(hour=12)
    )
    assert first.plan_fingerprint == replay.plan_fingerprint
    assert first.plan is not None

    provider = PostGISWorkflowProvider(create_engine("postgresql+psycopg2://"))
    result_sql, statistics_sql, parameters = provider._queries(first.plan)

    assert "planning_zone_source" in result_sql
    assert "ST_Intersection(parcel.geom, zone.geom)" in result_sql
    assert "land_use_code" in result_sql
    assert "GROUP BY zone_code, zone_name, land_use_code" in statistics_sql
    assert parameters == {"output_srid": 4326}
    assert ":distance_meters" not in result_sql
    assert ":minimum_area_m2" not in result_sql
    assert ";" not in result_sql


def test_planning_zone_execution_builds_typed_statistics_map_and_evidence() -> None:
    planner = _planner(_Authority(("parcel_current", "synthetic_planning_zones")))
    preview = planner.preview(
        _planning_zone_preview_request(), _subject(), planned_at=NOW
    )
    assert preview.plan is not None

    class _Result:
        def __init__(self, *, scalar=None, rows=()):
            self.scalar = scalar
            self.rows = rows

        def scalar_one(self):
            return self.scalar

        def mappings(self):
            return self

        def all(self):
            return list(self.rows)

    result_rows = (
        {
            "zone_code": "Z1",
            "zone_name": "重点发展区",
            "parcel_id": "P1",
            "land_use_code": "0101",
            "land_use_name": "水田",
            "area_m2": 1_000.0,
            "geometry_json": '{"type":"Polygon","coordinates":[]}',
        },
    )
    statistic_rows = (
        {
            "zone_code": "Z1",
            "zone_name": "重点发展区",
            "land_use_code": "0101",
            "land_use_name": "水田",
            "parcel_count": 1,
            "area_m2": 1_000.0,
        },
    )

    class _Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class _Connection(_Transaction):
        def begin(self):
            return _Transaction()

        def exec_driver_sql(self, statement):
            assert statement == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"

        def execute(self, statement, _parameters=None):
            sql = str(statement)
            if sql.startswith("SELECT set_config"):
                return _Result()
            if sql == "SHOW transaction_read_only":
                return _Result(scalar="on")
            if sql == "SHOW transaction_isolation":
                return _Result(scalar="repeatable read")
            if "ST_AsGeoJSON" in sql:
                return _Result(rows=result_rows)
            return _Result(rows=statistic_rows)

    class _Engine:
        dialect = create_engine("postgresql+psycopg2://").dialect

        def connect(self):
            return _Connection()

    result = PostGISWorkflowProvider(_Engine()).execute(preview.plan)

    assert result.geojson["features"][0]["properties"] == {
        "parcel_id": "P1",
        "zone_code": "Z1",
        "zone_name": "重点发展区",
        "land_use_code": "0101",
        "land_use_name": "水田",
        "area_m2": 1_000.0,
    }
    assert result.statistics[0].statistic_type == "planning_zone_land_use"
    assert result.statistics[0].area_mu == 1.5
    assert result.summary["parcel_count"] == 1
    assert result.summary["planning_zone_count"] == 1
    assert result.summary["land_use_category_count"] == 1
    assert result.map_update["summary"]["title"] == "规划区现状用地叠加统计"
    assert len(result.evidence.source_resource_versions) == 2
    assert len(result.evidence.algorithm_spec_fingerprints) == 2

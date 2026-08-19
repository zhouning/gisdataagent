"""Opt-in integration tests for the governed PostGIS GIS provider."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.gis_analysis_command_consumer import (
    PostGISAnalysisProvider,
    PostGISBackendCanceller,
)
from data_agent.gis_analysis_execution import (
    GISAnalysisBackendBinding,
    GISAnalysisCancelOutcome,
    GISAnalysisOperation,
)
from data_agent.test_gis_analysis_command_consumer import _plan

POSTGIS_INTEGRATION_URL = os.getenv("GDA_GIS_ANALYSIS_INTEGRATION_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGIS_INTEGRATION_URL,
    reason="GDA_GIS_ANALYSIS_INTEGRATION_DATABASE_URL is not configured",
)


def _integration_plan(operation: GISAnalysisOperation, schema: str):
    plan = _plan(operation)
    sources = tuple(
        source.model_copy(
            update={
                "physical_relation": (
                    f"{schema}.input_features"
                    if source.role == "input"
                    else f"{schema}.overlay_features"
                ),
                "source_srid": 4326,
            }
        )
        for source in plan.sources
    )
    return type(plan).create(
        tenant_id=plan.tenant_id,
        operation=operation,
        sources=sources,
        distance_meters=plan.distance_meters,
        output_srid=4326,
        budget=plan.budget,
        security_context_fingerprint=plan.security_context_fingerprint,
    )


def test_postgis_executes_buffer_clip_and_intersection_as_canonical_geojson(
    tmp_path: Path,
) -> None:
    assert POSTGIS_INTEGRATION_URL is not None
    engine = create_engine(POSTGIS_INTEGRATION_URL, pool_pre_ping=True)
    schema = f"gda_gis_it_{uuid4().hex[:12]}"
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".input_features '
                    "(id bigint PRIMARY KEY, geom geometry(Geometry, 4326) NOT NULL)"
                )
            )
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".overlay_features '
                    "(id bigint PRIMARY KEY, geom geometry(Polygon, 4326) NOT NULL)"
                )
            )
            connection.execute(
                text(
                    f'INSERT INTO "{schema}".input_features (id, geom) VALUES '
                    "(1, ST_SetSRID(ST_Point(106.20, 38.45), 4326)), "
                    "(2, ST_GeomFromText('POLYGON((106.0 38.3, 106.4 38.3, "
                    "106.4 38.7, 106.0 38.7, 106.0 38.3))', 4326))"
                )
            )
            connection.execute(
                text(
                    f'INSERT INTO "{schema}".overlay_features (id, geom) VALUES '
                    "(1, ST_GeomFromText('POLYGON((106.1 38.4, 106.3 38.4, "
                    "106.3 38.6, 106.1 38.6, 106.1 38.4))', 4326))"
                )
            )

        provider = PostGISAnalysisProvider(engine, result_root=tmp_path / "results")
        for operation in GISAnalysisOperation:
            plan = _integration_plan(operation, schema)
            run_id = uuid4()
            result = provider.execute(
                plan,
                run_id=run_id,
                plan_fingerprint="e" * 64,
                on_backend_ready=lambda _: None,
            )

            payload = (tmp_path / "results" / plan.tenant_id / f"{run_id}.json").read_bytes()
            document = json.loads(payload)
            assert payload == json.dumps(
                document,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            assert document["type"] == "FeatureCollection"
            assert document["gda"]["operation"] == operation.value
            assert document["gda"]["algorithm_id"] == plan.algorithm_id
            assert document["gda"]["algorithm_version"] == plan.algorithm_version
            assert (
                document["gda"]["algorithm_spec_fingerprint"]
                == plan.algorithm_spec_fingerprint
            )
            assert result.features_returned == len(document["features"])
            assert result.features_returned > 0
            assert result.manifest["transaction_read_only"] is True
            assert result.manifest["transaction_isolation"] == "repeatable read"
            assert result.manifest["format"] == "canonical-geojson"
            assert (
                result.manifest["algorithm_spec_fingerprint"]
                == plan.algorithm_spec_fingerprint
            )
            assert result.sha256 == hashlib.sha256(payload).hexdigest()
    finally:
        try:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            engine.dispose()


def test_postgis_cancels_only_the_exact_backend_identity() -> None:
    assert POSTGIS_INTEGRATION_URL is not None
    engine = create_engine(POSTGIS_INTEGRATION_URL, pool_pre_ping=True)
    run_id = uuid4()
    application_name = f"gda-gis-analysis/{run_id}"
    ready = threading.Event()
    finished = threading.Event()
    evidence: dict[str, object] = {}

    def execute_long_query() -> None:
        try:
            with engine.connect() as connection, connection.begin():
                connection.execute(
                    text("SELECT set_config('application_name', :name, false)"),
                    {"name": application_name},
                )
                row = connection.execute(
                    text(
                        "SELECT pg_backend_pid() AS backend_pid, backend_start, "
                        "datid::bigint AS database_oid, usesysid::bigint AS user_oid, "
                        "application_name FROM pg_stat_activity "
                        "WHERE pid = pg_backend_pid()"
                    )
                ).mappings().one()
                evidence["binding"] = GISAnalysisBackendBinding.create(**row)
                ready.set()
                connection.execute(text("SELECT pg_sleep(30)"))
        except DBAPIError as exc:
            original = getattr(exc, "orig", None)
            evidence["sqlstate"] = getattr(original, "sqlstate", None) or getattr(
                original, "pgcode", None
            )
            evidence["message"] = str(original or exc)
        finally:
            finished.set()

    target = threading.Thread(target=execute_long_query, daemon=True)
    target.start()
    try:
        assert ready.wait(timeout=5), "PostGIS target backend did not become ready"
        binding = evidence["binding"]
        assert isinstance(binding, GISAnalysisBackendBinding)
        wrong_binding = GISAnalysisBackendBinding.create(
            backend_pid=binding.backend_pid,
            backend_start=binding.backend_start,
            database_oid=binding.database_oid,
            user_oid=binding.user_oid,
            application_name=f"gda-gis-analysis/{uuid4()}",
        )
        canceller = PostGISBackendCanceller(engine)

        assert canceller.cancel(wrong_binding) is GISAnalysisCancelOutcome.NOT_FOUND
        with engine.connect() as unaffected:
            assert unaffected.execute(text("SELECT 1")).scalar_one() == 1
        assert not finished.is_set()

        assert canceller.cancel(binding) is GISAnalysisCancelOutcome.SIGNALLED
        assert finished.wait(timeout=5), "PostGIS target did not observe cancellation"
        assert evidence["sqlstate"] == "57014"
        assert "user request" in str(evidence["message"]).casefold()
        with engine.connect() as unaffected:
            assert unaffected.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        target.join(timeout=5)
        engine.dispose()

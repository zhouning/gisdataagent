"""PostgreSQL integration coverage for the irrigation world-model authority."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine
from data_agent.irrigation_world_model_demo import (
    IrrigationWorldModelConflict,
    IrrigationWorldModelNotFound,
    IrrigationWorldModelService,
)


def _postgres_engine():
    engine = get_engine()
    if engine is None or engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is not configured")
    return engine


def _register_reviewer(engine, tenant_id: str, actor: str) -> None:
    with engine.connect() as connection:
        with connection.begin():
            connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": tenant_id},
            )
            connection.execute(
                text(
                    """
                    SELECT principal_subject
                    FROM gda_control.upsert_approval_principal(
                        :tenant, :subject, 0, :display_name, 'active', true,
                        'available', clock_timestamp(), NULL, :subject,
                        'Register isolated irrigation integration-test reviewer'
                    )
                    """
                ),
                {
                    "tenant": tenant_id,
                    "subject": f"human:{actor}",
                    "display_name": actor,
                },
            ).scalar_one()


def test_postgres_run_review_restart_and_tenant_isolation():
    engine = _postgres_engine()
    suffix = uuid.uuid4().hex[:12]
    tenant_id = f"odiwm-pg-{suffix}"
    other_tenant = f"odiwm-other-{suffix}"
    actor = f"reviewer_{suffix}"
    _register_reviewer(engine, tenant_id, actor)

    service = IrrigationWorldModelService()
    run = service.run(
        {
            "supply_drop_percent": 25,
            "west_shift_hours": 8,
            "candidate_east_ratio_percent": 45,
            "horizon_hours": 12,
        },
        actor,
        tenant_id,
    )
    assert run["proposal"]["status"] == "pending"
    assert run["proposal"]["execution_allowed"] is False

    reviewed = service.review_proposal(
        run["proposal"]["proposal_id"],
        {"decision": "approved", "note": "Integration reviewer approval; no execution."},
        actor,
        tenant_id,
    )
    assert reviewed["status"] == "reviewed"
    assert reviewed["proposal"]["status"] == "approved"
    assert reviewed["proposal"]["execution_allowed"] is False
    assert len(reviewed["audit_events"]) == 6

    reloaded = IrrigationWorldModelService().get_run(run["run_id"], actor, tenant_id)
    assert reloaded["proposal"]["status"] == "approved"
    assert reloaded["proposal"]["reviewed_by"] == actor

    with pytest.raises(IrrigationWorldModelConflict):
        service.review_proposal(
            run["proposal"]["proposal_id"],
            {"decision": "returned", "note": "A second verdict must conflict."},
            actor,
            tenant_id,
        )

    with pytest.raises(IrrigationWorldModelNotFound):
        service.get_run(run["run_id"], actor, other_tenant)

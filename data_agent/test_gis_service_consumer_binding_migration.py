from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from data_agent.consumer_binding import (
    ConsumerBindingMigrationNotificationEnvelope,
)
from data_agent.consumer_binding_notification_worker import (
    render_consumer_binding_migration_alert,
)
from data_agent.gis_service_consumer_binding_migration import (
    GISServiceConsumerBindingMigrationImpact,
    gis_service_consumer_binding_migration_impact_fingerprint,
)
from data_agent.test_consumer_binding_notification_worker import (
    _binding,
    _notification,
    _state,
)

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


def _impact() -> GISServiceConsumerBindingMigrationImpact:
    values = {
        "tenant_id": "planning",
        "impact_id": UUID("00000000-0000-4000-8000-000000000301"),
        "source_service_consumer_binding_id": _binding().binding_id,
        "source_binding_sha256": _binding().binding_sha256,
        "service_urn": "gda://planning/gis_service/district-features",
        "consumer_ref": "workload:planner-api",
        "source_service_definition_version_id": UUID(
            "00000000-0000-4000-8000-000000000303"
        ),
        "source_service_release_binding_id": UUID(
            "00000000-0000-4000-8000-000000000304"
        ),
        "target_service_definition_version_id": UUID(
            "00000000-0000-4000-8000-000000000305"
        ),
        "target_service_release_binding_id": UUID(
            "00000000-0000-4000-8000-000000000306"
        ),
        "source_product_urn": _state().product_urn,
        "from_product_version_id": _state().from_product_version_id,
        "to_product_version_id": _state().to_product_version_id,
        "migration_state_id": _state().migration_state_id,
        "notification_id": _notification().notification_id,
        "recorded_by": "service:migration-impact-recorder",
        "recorded_at": NOW,
    }
    values["impact_sha256"] = gis_service_consumer_binding_migration_impact_fingerprint(
        values
    )
    return GISServiceConsumerBindingMigrationImpact.model_validate(values)


def test_impact_is_content_bound_and_enriches_existing_alert() -> None:
    impact = _impact()
    envelope = ConsumerBindingMigrationNotificationEnvelope(
        notification=_notification(),
        binding=_binding(),
        migration_state=_state(),
        gis_service_impacts=(impact,),
    )

    alert = render_consumer_binding_migration_alert(envelope)

    assert alert["labels"]["gda_service_urn"] == impact.service_urn
    assert alert["labels"]["gda_source_service_release_binding_id"] == str(
        impact.source_service_release_binding_id
    )
    assert alert["annotations"]["gda_source_service_consumer_binding_sha256"] == (
        impact.source_binding_sha256
    )
    assert alert["annotations"]["gda_service_impact_sha256"] == impact.impact_sha256


def test_impact_contract_rejects_tampering_and_migration_is_guarded() -> None:
    impact = _impact()
    tampered = impact.model_dump(mode="python")
    tampered["target_service_release_binding_id"] = UUID(
        "00000000-0000-4000-8000-000000000307"
    )
    try:
        GISServiceConsumerBindingMigrationImpact.model_validate(tampered)
    except ValueError as error:
        assert "impact_sha256" in str(error)
    else:
        raise AssertionError("tampered GIS service impact was accepted")

    migration = (
        Path(__file__).parent
        / "migrations/217_gis_service_consumer_binding_migration_impact.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "FORCE ROW LEVEL SECURITY",
        "guard_gis_service_consumer_binding_migration_impact_insert",
        "record_gis_service_consumer_binding_migration_impact",
        "REVOKE ALL ON TABLE gda_control.gis_service_consumer_binding_migration_impact",
        (
            "GRANT EXECUTE ON FUNCTION "
            "gda_control.record_gis_service_consumer_binding_migration_impact"
        ),
    ):
        assert marker in migration

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "129_platform_run_event_delivery_outbox.sql"
)


def test_run_event_delivery_migration_is_prospective_and_leased() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.platform_run_event_delivery_outbox",
        "AFTER INSERT ON gda_control.platform_run_event",
        "FOR UPDATE SKIP LOCKED",
        "claimed_until <= clock_timestamp()",
        "claim_platform_run_event_deliveries",
        "complete_platform_run_event_delivery",
        "fail_platform_run_event_delivery",
        "FORCE ROW LEVEL SECURITY",
        "GRANT SELECT ON TABLE gda_control.platform_run_event_delivery_outbox",
        "'gda.platform-runs.status'",
        "'cloudevents:platform-run-default'",
    ):
        assert marker in sql

    trigger_start = sql.index(
        "CREATE OR REPLACE FUNCTION gda_control.enqueue_platform_run_event_delivery()"
    )
    first_outbox_insert = sql.index(
        "INSERT INTO gda_control.platform_run_event_delivery_outbox"
    )
    assert first_outbox_insert > trigger_start
    assert sql.count("INSERT INTO gda_control.platform_run_event_delivery_outbox") == 1


def test_run_event_delivery_outbox_does_not_store_endpoint_or_credentials() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    table_definition = sql.split(
        "CREATE TABLE IF NOT EXISTS gda_control.platform_run_event_delivery_outbox (",
        1,
    )[1].split(");", 1)[0]

    assert "destination_ref TEXT NOT NULL" in table_definition
    assert "url" not in table_definition.lower()
    assert "token" not in table_definition.lower()
    assert "secret" not in table_definition.lower()

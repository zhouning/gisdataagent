"""Static invariants for the GIS analysis Run authority migration."""

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "158_gis_analysis_run_authority.sql"
)
RECONCILIATION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "159_gis_analysis_reconciliation_authority.sql"
)


def test_gis_analysis_migration_is_tenant_scoped_and_fail_closed() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    required = {
        "CREATE TABLE IF NOT EXISTS gda_control.gis_analysis_execution_admission",
        "CREATE TABLE IF NOT EXISTS gda_control.gis_analysis_execution_observation",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "SET row_security = on",
        "workload:gis-analysis-postgis",
        "application/geo+json",
        "gda.gis_analysis_result.v1",
        "canonical-geojson",
        "cancel_pending_gis_analysis_execution",
        "cancelled before provider start",
    }
    missing = sorted(marker for marker in required if marker not in sql)
    assert not missing, f"GIS analysis migration markers missing: {missing}"


def test_gis_analysis_migration_binds_source_fingerprints_and_start_receipt() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "authority_version_sha256" in sql
    assert "physical_binding_sha256" in sql
    assert "authority_version_ref::text" not in sql
    completion_lookup = """FROM gda_control.framework_attempt_observation
    WHERE tenant_id = p_tenant_id
      AND observation_id = p_start_observation_id
      AND run_id = p_run_id
      AND attempt_no = p_attempt_no
      AND observed_state = 'running';"""
    assert completion_lookup in sql
    assert "v_existing.external_attempt_id IS DISTINCT FROM p_external_attempt_id" in sql
    assert "v_existing.evidence->'backend'->>'binding_fingerprint'" in sql
    assert "IS DISTINCT FROM p_backend_binding_fingerprint" in sql
    assert "gis_analysis_backend_binding_fingerprint" in sql
    assert "p_backend_start > p_observed_at" in sql
    assert "p_requested_at < v_start.observed_at" in sql
    assert "p_observed_at < v_cancel.requested_at" in sql
    assert "p_observed_at < v_receipt.observed_at" in sql


def test_gis_analysis_migration_binds_exact_algorithm_releases() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    for marker in {
        "algorithm_spec_fingerprint",
        "postgis.st_buffer_geography",
        "28fd66b7ee57b3471d405813bd642941135fe11d00676ffa2470795510737ff2",
        "postgis.st_clip",
        "59887943945a96ceebae7e76f7702e6d1703c9b21286a898c46d08acfaa729d1",
        "postgis.st_intersection",
        "da3cd4bbf6bbf3b61c81ce1001a8874aaa14c10643c2a529ed41159521556d8d",
    }:
        assert marker in sql


def test_gis_failure_path_cannot_publish_a_result_artifact() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    failure_guard = """ELSIF p_outcome = 'failed' AND (
        p_result_artifact_id IS NOT NULL
        OR p_result_storage_uri IS NOT NULL
        OR p_result_media_type IS NOT NULL
        OR p_result_sha256 IS NOT NULL
        OR p_result_size_bytes IS NOT NULL"""
    assert failure_guard in sql
    assert "IF p_outcome = 'succeeded' THEN\n        INSERT INTO gda_control.artifact" in sql


def test_gis_reconciliation_is_bounded_audited_and_fail_closed() -> None:
    sql = RECONCILIATION_MIGRATION.read_text(encoding="utf-8")
    for marker in {
        "gis_analysis.reconcile",
        "gis_analysis_reconciliation_observation",
        "reconciliation_deadline",
        "max_reconciliation_attempts",
        "gis_analysis_reconciliation_timeout",
        "workload:gis-analysis-postgis-reconciler",
        "resolve_gis_analysis_reconciliation",
        "resolve_gis_reconciliation_incident_on_terminal",
        "terminal cancellation evidence remained unavailable",
        "Alertmanager",
    }:
        assert marker in sql
    assert "p_outcome IN ('not_found', 'unknown')" not in sql
    assert "status IN ('succeeded', 'failed', 'cancelled', 'timed_out')" in sql
    assert "WHERE run.status IN ('cancelling', 'reconciling')" in sql


def test_cancelled_terminal_can_win_reconciliation_race() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "v_run.status NOT IN ('cancelling', 'reconciling')" in sql
    assert "v_run.status NOT IN ('running', 'reconciling')" in sql

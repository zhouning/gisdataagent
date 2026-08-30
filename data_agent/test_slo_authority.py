"""Contract tests for versioned, ApprovalCase-gated SLO authority."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.slo_authority import (
    SLOBurnRateWindow,
    SLOCompilationError,
    SLODefinitionActivation,
    SLODefinitionAuthority,
    SLODefinitionDraft,
    SLODefinitionEvent,
    SLODefinitionVersion,
    SLOEventRatioIndicator,
    compile_slo_prometheus_rules,
)

NOW = datetime(2026, 8, 4, 8, tzinfo=UTC)
TENANT = "slo-contract"
SLO_REF = f"gda://{TENANT}/slo_definition/approval-notification-delivery"
VERSION_REF = f"{SLO_REF}.v1"


def _indicator(**changes) -> SLOEventRatioIndicator:
    values = {
        "metric_name": "gda_approval_notification_operations_total",
        "good_outcomes": ("delivered",),
        "bad_outcomes": ("dead_lettered", "retrying"),
        "match_labels": {},
    }
    values.update(changes)
    return SLOEventRatioIndicator(**values)


def _burn_windows() -> tuple[SLOBurnRateWindow, ...]:
    return (
        SLOBurnRateWindow(
            name="fast",
            short_window_seconds=300,
            long_window_seconds=3600,
            burn_rate_milli=14400,
            minimum_events=20,
            for_seconds=120,
            severity="critical",
        ),
        SLOBurnRateWindow(
            name="slow",
            short_window_seconds=1800,
            long_window_seconds=21600,
            burn_rate_milli=6000,
            minimum_events=100,
            for_seconds=900,
            severity="warning",
        ),
    )


def _draft(**changes) -> SLODefinitionDraft:
    values = {
        "tenant_id": TENANT,
        "slo_definition_ref": SLO_REF,
        "slo_version_ref": VERSION_REF,
        "version": 1,
        "service_resource_urn": (
            f"gda://{TENANT}/service/approval-notification"
        ),
        "indicator": _indicator(),
        "objective_basis_points": 9900,
        "objective_window_seconds": 30 * 24 * 60 * 60,
        "owner_subject": "team:data-platform",
        "oncall_ref": "oncall:approval-primary",
        "burn_rate_windows": _burn_windows(),
        "created_by": "human:platform-sre",
        "creation_reason": "stage a candidate for explicit service-owner review",
        "created_at": NOW,
    }
    values.update(changes)
    return SLODefinitionDraft(**values)


def _definition(**changes) -> SLODefinitionVersion:
    values = {
        **_draft().model_dump(),
        "definition_fingerprint": "a" * 64,
    }
    values.update(changes)
    return SLODefinitionVersion(**values)


def _activation(**changes) -> SLODefinitionActivation:
    values = {
        "tenant_id": TENANT,
        "slo_definition_ref": SLO_REF,
        "active_version_ref": VERSION_REF,
        "active_fingerprint": "a" * 64,
        "approval_case_ref": f"gda://{TENANT}/approval_case/slo-v1-activation",
        "activation_version": 1,
        "activated_by": "workload:slo-controller",
        "activation_reason": "apply the approved SLO definition",
        "activated_at": NOW,
    }
    values.update(changes)
    return SLODefinitionActivation(**values)


def test_slo_draft_is_strict_tenant_bound_and_frozen() -> None:
    draft = _draft()

    assert draft.objective_basis_points == 9900
    assert draft.indicator.good_outcomes == ("delivered",)
    with pytest.raises(ValidationError, match="frozen"):
        draft.objective_basis_points = 9500  # type: ignore[misc]
    with pytest.raises(ValidationError, match="definition tenant"):
        _draft(slo_definition_ref="gda://other/slo_definition/approval-delivery")
    with pytest.raises(ValidationError, match="version reference"):
        _draft(slo_version_ref=f"{SLO_REF}.v2")
    with pytest.raises(ValidationError, match="on-call"):
        _draft(oncall_ref="https://paging.example.test")


def test_event_ratio_indicator_rejects_ambiguous_or_unsafe_promql_inputs() -> None:
    with pytest.raises(ValidationError, match="disjoint"):
        _indicator(bad_outcomes=("delivered", "retrying"))
    with pytest.raises(ValidationError, match="unique and sorted"):
        _indicator(bad_outcomes=("retrying", "dead_lettered"))
    with pytest.raises(ValidationError, match="metric name"):
        _indicator(metric_name='metric{tenant="other"}')
    with pytest.raises(ValidationError, match="cannot override outcome"):
        _indicator(match_labels={"outcome": "delivered"})
    with pytest.raises(ValidationError, match="match label"):
        _indicator(match_labels={"tenant": 'a" or vector(1)'})


def test_burn_policy_requires_ordered_bounded_windows() -> None:
    with pytest.raises(ValidationError, match="long window"):
        SLOBurnRateWindow(
            name="invalid",
            short_window_seconds=1800,
            long_window_seconds=1200,
            burn_rate_milli=1000,
            minimum_events=1,
            severity="warning",
        )
    with pytest.raises(ValidationError, match="cannot exceed objective"):
        _draft(
            objective_window_seconds=3600,
            burn_rate_windows=(
                SLOBurnRateWindow(
                    name="invalid",
                    short_window_seconds=300,
                    long_window_seconds=7200,
                    burn_rate_milli=1000,
                    minimum_events=1,
                    severity="warning",
                ),
            ),
        )


def test_rule_compilation_fails_closed_without_exact_active_pointer() -> None:
    definition = _definition()

    with pytest.raises(SLOCompilationError, match="not active"):
        compile_slo_prometheus_rules(definition, None)
    with pytest.raises(SLOCompilationError, match="exact definition"):
        compile_slo_prometheus_rules(
            definition,
            _activation(active_fingerprint="b" * 64),
        )
    with pytest.raises(SLOCompilationError, match="exact definition"):
        compile_slo_prometheus_rules(
            definition,
            _activation(tenant_id="other"),
        )


def test_active_definition_compiles_multiwindow_traffic_guarded_rules() -> None:
    compiled = compile_slo_prometheus_rules(_definition(), _activation())
    group = compiled["groups"][0]
    recording_rules = [rule for rule in group["rules"] if "record" in rule]
    alerts = [rule for rule in group["rules"] if "alert" in rule]

    assert group["name"] == (
        "gis-data-agent-slo-approval-notification-delivery-v1"
    )
    assert len(recording_rules) == 8
    assert len(alerts) == 2
    assert {rule["record"] for rule in recording_rules} == {
        "gda:slo_error_ratio",
        "gda:slo_events_total",
    }
    assert {rule["labels"]["window"] for rule in recording_rules} == {
        "300s",
        "1800s",
        "3600s",
        "21600s",
    }
    assert {rule["labels"]["burn_window"] for rule in alerts} == {
        "fast",
        "slow",
    }
    assert {rule["labels"]["severity"] for rule in alerts} == {
        "critical",
        "warning",
    }
    assert all("gda:slo_events_total" in rule["expr"] for rule in alerts)
    assert all(rule["expr"].count("and ignoring(window)") == 2 for rule in alerts)
    assert any("> 0.144" in rule["expr"] for rule in alerts)
    assert any("> 0.06" in rule["expr"] for rule in alerts)
    assert all(
        rule["annotations"]["approval_case_ref"].endswith("slo-v1-activation")
        for rule in alerts
    )
    rendered = str(compiled)
    assert "http://" not in rendered and "https://" not in rendered


def test_slo_events_bind_approval_only_to_activation() -> None:
    staged = SLODefinitionEvent(
        tenant_id=TENANT,
        slo_event_id=UUID("00000000-0000-4000-8000-000000000001"),
        slo_definition_ref=SLO_REF,
        slo_version_ref=VERSION_REF,
        definition_fingerprint="a" * 64,
        event_type="staged",
        actor_subject="human:platform-sre",
        reason="stage candidate",
        occurred_at=NOW,
    )
    assert staged.approval_case_ref is None
    with pytest.raises(ValidationError, match="only an SLO activation"):
        SLODefinitionEvent.model_validate(
            {
                **staged.model_dump(),
                "approval_case_ref": (
                    f"gda://{TENANT}/approval_case/slo-v1-activation"
                ),
            }
        )


def test_slo_authority_version_list_is_bounded_and_detects_next_page() -> None:
    newest = _definition(
        slo_version_ref=f"{SLO_REF}.v2",
        version=2,
        definition_fingerprint="b" * 64,
    )
    oldest = _definition()

    def database_row(definition: SLODefinitionVersion) -> dict:
        row = definition.model_dump(mode="python")
        row.pop("schema_id")
        row["indicator_config"] = row.pop("indicator")
        row["burn_rate_policy"] = row.pop("burn_rate_windows")
        return row

    rows_result = MagicMock()
    rows_result.mappings.return_value.all.return_value = [
        database_row(newest),
        database_row(oldest),
    ]
    connection = MagicMock()
    connection.execute.return_value = rows_result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    authority = SLODefinitionAuthority()

    with patch.object(authority, "_transaction", return_value=transaction):
        page = authority.list_versions(
            TENANT,
            SLO_REF,
            limit=1,
            offset=2,
        )

    assert page.items == (newest,)
    assert page.offset == 2
    assert page.limit == 1
    assert page.has_more is True
    assert connection.execute.call_args.args[1] == {
        "tenant_id": TENANT,
        "slo_definition_ref": SLO_REF,
        "row_limit": 2,
        "offset": 2,
    }


def test_migration_enforces_immutable_rls_approval_and_least_privilege() -> None:
    sql = (
        Path(__file__).parent / "migrations/122_slo_definition_authority.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.slo_definition_version",
        "CREATE TABLE IF NOT EXISTS gda_control.slo_definition_activation",
        "CREATE TABLE IF NOT EXISTS gda_control.slo_definition_event",
        "stage_slo_definition_version",
        "activate_slo_definition_version",
        "ApprovalCase does not authorize this SLO activation",
        "slo_definition.activate",
        "definition_fingerprint",
        "IF NOT COALESCE(v_inserted, FALSE) THEN",
        "Preserve the first server timestamp and its fingerprint across HTTP retries",
        "FROM jsonb_object_keys(p_indicator_config) AS keys(key)",
        "array_agg(value) IS DISTINCT FROM array_agg(value ORDER BY value)",
        "FORCE ROW LEVEL SECURITY",
        "reject_immutable_mutation",
        "GRANT SELECT ON gda_control.slo_definition_version",
    ):
        assert marker in sql
    assert "GRANT INSERT ON gda_control.slo_definition_version" not in sql
    assert "GRANT UPDATE ON gda_control.slo_definition_activation" not in sql
    assert "GRANT INSERT ON gda_control.slo_definition_event" not in sql

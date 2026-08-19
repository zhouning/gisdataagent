from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import create_engine, text

from data_agent.cross_store_projection_compensation_chongqing_source_selection_profile_release import (  # noqa: E501
    build_initial_chongqing_source_selection_profile_release_history,
    publish_chongqing_source_selection_profile_change,
    rollback_chongqing_source_selection_profile_release,
)
from data_agent.cross_store_projection_compensation_chongqing_source_selection_profile_release_authority import (  # noqa: E501
    CHONGQING_SOURCE_SELECTION_PROFILE_RELEASE_AUTHORITY_MIGRATION,
    ChongqingSourceSelectionProfileReleaseAuthorityConfigurationError,
    ChongqingSourceSelectionProfileReleaseAuthorityForbiddenError,
    ChongqingSourceSelectionProfileReleaseAuthorityValidationError,
    PostgresChongqingSourceSelectionProfileReleaseAuthorityStore,
)
from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.test_cross_store_projection_compensation_chongqing_source_selection_profile_release import (  # noqa: E501
    _profile,
    _revised_profile,
)


def test_migration_exposes_only_governed_immutable_release_storage() -> None:
    migration = CHONGQING_SOURCE_SELECTION_PROFILE_RELEASE_AUTHORITY_MIGRATION.read_text(
        encoding="utf-8"
    )

    assert "chongqing_source_selection_profile_release_history" in migration
    assert "chongqing_source_selection_profile_release_history_current" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "technical_history_active_unreviewed" in migration
    assert "assisted_precheck_not_for_production_decision" in migration
    assert "production_execution_authorized" in migration
    assert "GRANT INSERT" not in migration


def test_repository_requires_postgresql() -> None:
    store = PostgresChongqingSourceSelectionProfileReleaseAuthorityStore(
        "chongqing-customer",
        create_engine("sqlite://"),
    )

    with pytest.raises(
        ChongqingSourceSelectionProfileReleaseAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        store.release_history_current(
            "chongqing-heping-review-source-selection-baseline-v1",
            "heping_review",
        )


def test_repository_rejects_cross_tenant_history_before_database_access() -> None:
    history = build_initial_chongqing_source_selection_profile_release_history(_profile())
    store = PostgresChongqingSourceSelectionProfileReleaseAuthorityStore(
        "another-tenant",
        create_engine("sqlite://"),
    )

    with pytest.raises(
        ChongqingSourceSelectionProfileReleaseAuthorityForbiddenError,
        match="tenant differs",
    ):
        store.record(history)


def test_repository_rejects_invalid_identity_before_database_access() -> None:
    store = PostgresChongqingSourceSelectionProfileReleaseAuthorityStore(
        "chongqing-customer",
        create_engine("sqlite://"),
    )

    with pytest.raises(
        ChongqingSourceSelectionProfileReleaseAuthorityValidationError,
        match="scenario_id",
    ):
        store.release_history_current("profile", "not-a-scenario")


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_profile_release_authority_is_append_only_and_tenant_scoped(
    tmp_path,
) -> None:
    initial = build_initial_chongqing_source_selection_profile_release_history(_profile())
    revised_profile = _revised_profile(tmp_path)
    changed = publish_chongqing_source_selection_profile_change(
        initial,
        revised_profile,
        change_reason="customer scenario evidence technical revision",
    )
    competing_v2 = publish_chongqing_source_selection_profile_change(
        initial,
        revised_profile,
        change_reason="competing technical revision",
    )
    rolled_back = rollback_chongqing_source_selection_profile_release(
        changed,
        initial.active_release_sha256,
        _profile(),
        change_reason="restore prior sealed technical profile",
    )

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            connection.exec_driver_sql(
                CHONGQING_SOURCE_SELECTION_PROFILE_RELEASE_AUTHORITY_MIGRATION.read_text(
                    encoding="utf-8"
                ).replace("%", "%%")
            )

        store = PostgresChongqingSourceSelectionProfileReleaseAuthorityStore(
            initial.tenant_id,
            sandbox.runtime_engine,
        )
        assert store.record(initial) == initial
        assert store.record(initial) == initial
        assert store.record(changed) == changed
        assert store.release_history_current(initial.profile_id, initial.scenario_id) == changed
        assert store.record(rolled_back) == rolled_back
        assert (
            store.release_history_current(initial.profile_id, initial.scenario_id)
            == rolled_back
        )
        assert store.history_snapshots(initial.profile_id, initial.scenario_id) == (
            initial,
            changed,
            rolled_back,
        )
        assert store.record(initial) == initial
        assert store.record(changed) == changed
        assert (
            store.release_history_current(initial.profile_id, initial.scenario_id)
            == rolled_back
        )

        with pytest.raises(
            ChongqingSourceSelectionProfileReleaseAuthorityValidationError,
            match="version is not contiguous",
        ):
            store.record(competing_v2)

        other_tenant = PostgresChongqingSourceSelectionProfileReleaseAuthorityStore(
            "another-tenant",
            sandbox.runtime_engine,
        )
        assert (
            other_tenant.release_history_current(initial.profile_id, initial.scenario_id)
            is None
        )

        with pytest.raises(
            ChongqingSourceSelectionProfileReleaseAuthorityForbiddenError,
            match="tenant or role was denied",
        ):
            with store._transaction() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.
                            chongqing_source_selection_profile_release_history (
                            tenant_id, profile_id, scenario_id,
                            active_release_version, active_release_sha256,
                            history_sha256, history_document
                        ) VALUES (
                            :tenant_id, :profile_id, :scenario_id,
                            :active_release_version, :active_release_sha256,
                            :history_sha256, CAST(:history_document AS jsonb)
                        )
                        """
                    ),
                    {
                        "tenant_id": initial.tenant_id,
                        "profile_id": initial.profile_id,
                        "scenario_id": initial.scenario_id,
                        "active_release_version": 3,
                        "active_release_sha256": "f" * 64,
                        "history_sha256": "e" * 64,
                        "history_document": json.dumps(changed.model_dump(mode="json")),
                    },
                )

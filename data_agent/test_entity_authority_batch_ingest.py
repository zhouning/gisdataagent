"""Contracts for bounded atomic entity-authority batches."""

from pathlib import Path

import pytest

from data_agent.entity_link_authority import (
    EntityLinkAuthority,
    EntityLinkValidationError,
)
from data_agent.temporal_entity_authority import (
    TemporalEntityAuthority,
    TemporalEntityValidationError,
)

MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "162_entity_authority_batch_ingest.sql"
)


def test_batch_migration_is_bounded_atomic_and_minimum_privilege() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    for marker in (
        "record_temporal_entity_assertion_batch",
        "bind_entity_source_identity_batch",
        "register_entity_link_type_batch",
        "record_entity_link_assertion_batch",
        "jsonb_array_length(p_items) NOT BETWEEN 1 AND 500",
        "SECURITY DEFINER",
        "SET row_security = on",
        "FROM PUBLIC",
        "TO gda_control_gateway",
    ):
        assert marker in sql
    assert sql.count("RETURNS JSONB") == 4
    assert sql.count("jsonb_array_length(p_items) NOT BETWEEN 1 AND 500") == 4
    assert sql.count("FROM PUBLIC;") == 4
    assert sql.count("TO gda_control_gateway;") == 4
    assert "GRANT INSERT ON TABLE" not in sql
    assert "GRANT UPDATE ON TABLE" not in sql
    assert "GRANT DELETE ON TABLE" not in sql


def test_python_batch_methods_reject_empty_and_oversized_inputs_before_database() -> None:
    temporal = TemporalEntityAuthority()
    links = EntityLinkAuthority()

    with pytest.raises(TemporalEntityValidationError, match="cannot be empty"):
        temporal.record_batch(())
    with pytest.raises(EntityLinkValidationError, match="cannot be empty"):
        links.bind_sources_batch(())
    with pytest.raises(EntityLinkValidationError, match="cannot be empty"):
        links.register_link_types_batch(())
    with pytest.raises(EntityLinkValidationError, match="cannot be empty"):
        links.record_links_batch(())

    placeholder = object()
    with pytest.raises(TemporalEntityValidationError, match="maximum is 500"):
        temporal.record_batch((placeholder,) * 501)  # type: ignore[arg-type]
    with pytest.raises(EntityLinkValidationError, match="maximum is 500"):
        links.record_links_batch((placeholder,) * 501)  # type: ignore[arg-type]

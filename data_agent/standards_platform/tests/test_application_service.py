"""PostgreSQL transaction tests for confirmed standard mapping contracts."""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from data_agent.database_tools import _inject_user_context
from data_agent.standards_platform.application.service import (
    confirm_virtual_source_mapping,
    load_confirmed_virtual_source_mapping,
)
from data_agent.user_context import current_user_id, current_user_role


def test_confirm_rejects_invalid_version_identity_before_database_access():
    with pytest.raises(ValueError, match="standard_version_id must be a UUID"):
        confirm_virtual_source_mapping(
            source_id=1,
            owner_username="alice",
            standard_version_id="draft-version",
            source_profile_hash="a" * 64,
            schema_mapping={"old": "new"},
            field_bindings=[{
                "source_field": "old",
                "target_data_element_id": str(uuid.uuid4()),
                "confidence": 1,
            }],
            confirmed_by="alice",
        )


def test_confirm_rejects_non_digest_source_profile_before_database_access():
    with pytest.raises(ValueError, match="source_profile_hash"):
        confirm_virtual_source_mapping(
            source_id=1,
            owner_username="alice",
            standard_version_id=str(uuid.uuid4()),
            source_profile_hash="not-a-digest",
            schema_mapping={"old": "new"},
            field_bindings=[{
                "source_field": "old",
                "target_data_element_id": str(uuid.uuid4()),
                "confidence": 1,
            }],
            confirmed_by="alice",
        )


def test_confirm_mapping_is_atomic_version_bound_and_idempotent(engine, fresh_clause):
    _, _, version_id = fresh_clause
    element_id = str(uuid.uuid4())
    source_name = f"mapping-source-{uuid.uuid4().hex[:10]}"
    user_token = current_user_id.set("alice")
    role_token = current_user_role.set("analyst")
    source_id = None

    try:
        with engine.begin() as conn:
            _inject_user_context(conn)
            conn.execute(text("""
                UPDATE std_document_version
                   SET status = 'released', released_at = now()
                 WHERE id = :version_id
            """), {"version_id": version_id})
            conn.execute(text("""
                INSERT INTO std_data_element (
                    id, document_version_id, code, name_zh,
                    representation_class, datatype, obligation,
                    bound_table, bound_column)
                VALUES (:id, :version_id, 'DLBM', '地类编码',
                        'code', 'VARCHAR', 'mandatory', 'cq_land', 'dlbm')
            """), {"id": element_id, "version_id": version_id})
            source_id = conn.execute(text("""
                INSERT INTO agent_virtual_sources (
                    source_name, source_type, endpoint_url, owner_username)
                VALUES (:name, 'wfs', 'https://example.test/wfs', 'alice')
                RETURNING id
            """), {"name": source_name}).scalar_one()

        request = {
            "source_id": source_id,
            "owner_username": "alice",
            "standard_version_id": version_id,
            "source_profile_hash": "a" * 64,
            "schema_mapping": {"DLBM_OLD": "dlbm"},
            "field_bindings": [{
                "source_field": "DLBM_OLD",
                "target_data_element_id": element_id,
                "confidence": 0.97,
                "match_method": "hybrid_embedding",
                "evidence": {"lexical_score": 0.9, "type_score": 1.0},
            }],
            "confirmed_by": "alice",
            "source_fields": ["DLBM_OLD", "UNUSED"],
            "review_decisions": [
                {
                    "source_field": "DLBM_OLD",
                    "decision": "approved",
                    "reason": "recommendation_accepted",
                },
                {
                    "source_field": "UNUSED",
                    "decision": "rejected",
                    "reason": "not_applicable",
                },
            ],
            "target_table": "cq_land",
        }
        first = confirm_virtual_source_mapping(**request)
        repeated = confirm_virtual_source_mapping(**request)

        assert first["status"] == "confirmed"
        assert first["idempotent"] is False
        assert repeated["idempotent"] is True
        assert repeated["contract_id"] == first["contract_id"]
        assert first["quality_gate"]["status"] == "passed"
        assert first["quality_gate"]["summary"]["rejected"] == 1
        assert first["publication"]["status"] == "not_published"
        assert first["publication"]["ready"] is False

        with engine.connect() as conn:
            _inject_user_context(conn)
            contract = conn.execute(text("""
                SELECT standard_version_id, source_snapshot_hash, status,
                       metadata
                  FROM std_application_mapping_contract WHERE id = :id
            """), {"id": first["contract_id"]}).first()
            field = conn.execute(text("""
                SELECT source_field, target_data_element_id, target_field,
                       transform_spec
                  FROM std_application_field_mapping WHERE contract_id = :id
            """), {"id": first["contract_id"]}).mappings().one()
            stored_mapping = conn.execute(text("""
                SELECT schema_mapping FROM agent_virtual_sources WHERE id = :id
            """), {"id": source_id}).scalar_one()

        assert str(contract[0]) == version_id
        assert contract[1] == "a" * 64
        assert contract[2] == "confirmed"
        metadata = contract[3]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        assert metadata["quality_gate"]["status"] == "passed"
        assert metadata["target_table"] == "cq_land"
        assert field["source_field"] == "DLBM_OLD"
        assert str(field["target_data_element_id"]) == element_id
        assert field["target_field"] == "dlbm"
        transform = field["transform_spec"]
        if isinstance(transform, str):
            transform = json.loads(transform)
        assert transform == {"operation": "rename"}
        assert stored_mapping == {"DLBM_OLD": "dlbm"}

        preflight_input = load_confirmed_virtual_source_mapping(
            source_id=source_id,
            owner_username="alice",
        )
        assert preflight_input["contract_id"] == first["contract_id"]
        assert preflight_input["mapping_hash"] == first["mapping_hash"]
        assert preflight_input["target_table"] == "cq_land"
        assert preflight_input["field_bindings"] == [{
            "source_field": "DLBM_OLD",
            "target_data_element_id": uuid.UUID(element_id),
            "target_field": "dlbm",
            "datatype": "VARCHAR",
            "representation_class": "code",
            "obligation": "mandatory",
        }]

        other_user_token = current_user_id.set("bob")
        try:
            with pytest.raises(
                LookupError,
                match="virtual source not found or not owned by user",
            ):
                confirm_virtual_source_mapping(**request)
        finally:
            current_user_id.reset(other_user_token)
    finally:
        try:
            if source_id is not None:
                with engine.begin() as conn:
                    _inject_user_context(conn)
                    conn.execute(text(
                        "DELETE FROM agent_virtual_sources WHERE id = :id"
                    ), {"id": source_id})
        finally:
            current_user_role.reset(role_token)
            current_user_id.reset(user_token)

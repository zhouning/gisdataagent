"""Tests for TWM SpatialPolicyRuleStrategy — to_spatial_policy_rule."""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from data_agent.standards_platform.derivation import runner
from data_agent.territory_world_model.rule_dsl import validate_rule_body


def _json(value):
    return value if isinstance(value, dict) else json.loads(value)


def _seed_element(
    engine,
    ver_id: str,
    *,
    name_zh: str = "永久基本农田边界",
    bound_table: str = "synthetic_pbf",
    bound_column: str = "geometry",
    representation_class: str | None = "geometry",
    datatype: str = "geometry",
) -> str:
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element "
            "(id, document_version_id, code, name_zh, representation_class, "
            " datatype, obligation, bound_table, bound_column) "
            "VALUES (:i, :v, :c, :n, :rc, :dt, 'optional', :bt, :bc)"
        ), {"i": eid, "v": ver_id, "c": f"E-{eid[:6]}", "n": name_zh,
             "rc": representation_class, "dt": datatype,
             "bt": bound_table, "bc": bound_column})
    return eid


def _collect(engine, version_id: str) -> dict[str, list]:
    with engine.connect() as c:
        rule_set_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM twm_rule_set WHERE source_std_version_id=:v "
            "ORDER BY created_at, id"
        ), {"v": version_id}).fetchall()]
        rule_rows = []
        if rule_set_ids:
            rule_rows = c.execute(text(
                "SELECT id, rule_set_id, rule_code, title, category, "
                "       severity, rule_body, legal_basis, review_policy, "
                "       enabled, std_derived_link_id, metadata "
                "FROM twm_policy_rule "
                "WHERE rule_set_id = ANY(:ids) "
                "ORDER BY created_at, id"
            ), {"ids": rule_set_ids}).mappings().all()
        link_rows = c.execute(text(
            "SELECT id, source_kind, source_id, source_version_id, "
            "       target_kind, target_table, target_id, "
            "       derivation_strategy, status "
            "FROM std_derived_link "
            "WHERE source_version_id=:v "
            "  AND derivation_strategy='to_spatial_policy_rule' "
            "ORDER BY generated_at, id"
        ), {"v": version_id}).mappings().all()
    return {
        "rule_set_ids": rule_set_ids,
        "rule_rows": [dict(r) for r in rule_rows],
        "link_rows": [dict(r) for r in link_rows],
    }


def _cleanup(engine, doc_id: str) -> None:
    with engine.connect() as c:
        version_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM std_document_version WHERE document_id=:d"
        ), {"d": doc_id}).fetchall()]
        rule_set_ids: list[str] = []
        if version_ids:
            rule_set_ids = [str(r[0]) for r in c.execute(text(
                "SELECT id FROM twm_rule_set "
                "WHERE source_std_version_id = ANY(:ids)"
            ), {"ids": version_ids}).fetchall()]

    with engine.begin() as conn:
        if rule_set_ids:
            conn.execute(text(
                "DELETE FROM twm_policy_rule WHERE rule_set_id = ANY(:ids)"
            ), {"ids": rule_set_ids})
            conn.execute(text(
                "DELETE FROM twm_rule_set WHERE id = ANY(:ids)"
            ), {"ids": rule_set_ids})
        if version_ids:
            conn.execute(text(
                "DELETE FROM std_derived_link "
                "WHERE source_version_id = ANY(CAST(:ids AS uuid[])) "
                "  AND derivation_strategy='to_spatial_policy_rule'"
            ), {"ids": version_ids})
        conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                     {"i": doc_id})


def test_runner_lists_spatial_policy_rule_as_active():
    statuses = {s["name"]: s["status"] for s in runner.get_strategy_status()}
    assert statuses["to_spatial_policy_rule"] == "active"


def test_spatial_candidate_creates_disabled_twm_policy_rule(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    element_id = _seed_element(engine, ver_id)
    try:
        results = runner.dispatch(
            version_id=ver_id,
            by_user="admin",
            strategies=["to_spatial_policy_rule"],
        )
        assert results["to_spatial_policy_rule"]["ok"] is True
        assert results["to_spatial_policy_rule"]["new"] == 1

        created = _collect(engine, ver_id)
        assert len(created["rule_set_ids"]) == 1
        assert len(created["rule_rows"]) == 1
        assert len(created["link_rows"]) == 1

        rule = created["rule_rows"][0]
        link = created["link_rows"][0]
        assert rule["category"] == "standard_derived_spatial_policy"
        assert rule["severity"] == "high"
        assert rule["review_policy"] == "review_required"
        assert rule["enabled"] is False
        assert str(rule["std_derived_link_id"]) == str(link["id"])

        body = _json(rule["rule_body"])
        validation = validate_rule_body(body)
        assert validation["valid"] is True
        assert body["subject"]["object_type"] == "project"
        assert body["constraint"]["target_role"] == "pbf"
        assert body["constraint"]["spatial_predicate"] == "intersects"
        assert body["hit_when"]["overlap_area_m2"]["gt"] == 1

        legal_basis = _json(rule["legal_basis"])
        assert legal_basis["std_version_id"] == ver_id
        assert legal_basis["std_data_element_id"] == element_id

        metadata = _json(rule["metadata"])
        assert metadata["derived_status"] == "active"
        assert metadata["derived_from"] == "std_data_element"

        assert link["source_kind"] == "data_element"
        assert str(link["source_id"]) == element_id
        assert link["target_kind"] == "spatial_policy_rule"
        assert link["target_table"] == "twm_policy_rule"
        assert str(link["target_id"]) == rule["id"]
        assert link["status"] == "active"
    finally:
        _cleanup(engine, doc_id)


def test_non_spatial_bound_field_is_skipped(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_element(
        engine,
        ver_id,
        name_zh="地类编码",
        bound_table="parcel_current",
        bound_column="dlbm",
        representation_class="code",
        datatype="string",
    )
    try:
        results = runner.dispatch(
            version_id=ver_id,
            by_user="admin",
            strategies=["to_spatial_policy_rule"],
        )
        assert results["to_spatial_policy_rule"]["ok"] is True
        assert results["to_spatial_policy_rule"]["new"] == 0
        created = _collect(engine, ver_id)
        assert created["rule_set_ids"] == []
        assert created["rule_rows"] == []
        assert created["link_rows"] == []
    finally:
        _cleanup(engine, doc_id)


def test_rerun_stales_prior_link_and_preserves_rule_history(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id)
    try:
        runner.dispatch(
            version_id=ver_id,
            by_user="admin",
            strategies=["to_spatial_policy_rule"],
        )
        runner.dispatch(
            version_id=ver_id,
            by_user="admin",
            strategies=["to_spatial_policy_rule"],
        )

        created = _collect(engine, ver_id)
        assert len(created["rule_set_ids"]) == 1
        assert len(created["rule_rows"]) == 2
        assert len(created["link_rows"]) == 2

        link_statuses = sorted(r["status"] for r in created["link_rows"])
        assert link_statuses == ["active", "stale"]

        metadata_statuses = sorted(
            _json(r["metadata"])["derived_status"]
            for r in created["rule_rows"]
        )
        assert metadata_statuses == ["active", "stale"]
        assert all(r["enabled"] is False for r in created["rule_rows"])
    finally:
        _cleanup(engine, doc_id)

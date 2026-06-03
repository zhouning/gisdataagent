from __future__ import annotations

import uuid

from sqlalchemy import text

from data_agent.standards_platform.derivation.strategies.data_model import (
    DataModelStrategy,
)
from data_agent.standards_platform.derivation.strategies.semantic_hint import (
    SemanticHintStrategy,
)
from data_agent.standards_platform.derivation.strategies.synonym import (
    SynonymStrategy,
)
from data_agent.standards_platform.derivation.strategies.value_domain import (
    ValueDomainStrategy,
)
from data_agent.standards_platform.evaluation.extractor import (
    extract_prediction_set,
)


def _seed_bound_element(
    engine,
    ver_id,
    *,
    name_zh="land_class_code",
    bound_table="cq_dltb",
    bound_column="dlbm",
    obligation="mandatory",
    value_domain_id=None,
):
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column, "
            "value_domain_id) "
            "VALUES (:i, :v, :c, :n, 'string', :ob, :bt, :bc, :vd)"
        ), {
            "i": eid,
            "v": ver_id,
            "c": f"E-{eid[:6]}",
            "n": name_zh,
            "ob": obligation,
            "bt": bound_table,
            "bc": bound_column,
            "vd": value_domain_id,
        })
    return eid


def _seed_value_domain(
    engine,
    ver_id,
    *,
    kind="enumeration",
    code="TEST_ENUM",
    name="test enum",
    items: list[tuple[str, str]] | None = None,
):
    domain_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_value_domain (id, document_version_id, code, "
            "name, kind) VALUES (:i, :v, :c, :n, :k)"
        ), {"i": domain_id, "v": ver_id, "c": code, "n": name, "k": kind})
        for ordinal, (value, label) in enumerate(items or []):
            conn.execute(text(
                "INSERT INTO std_value_domain_item (id, value_domain_id, "
                "value, label_zh, ordinal) VALUES (:i, :d, :v, :l, :o)"
            ), {
                "i": str(uuid.uuid4()),
                "d": domain_id,
                "v": value,
                "l": label,
                "o": ordinal,
            })
    return domain_id


def _seed_semantic_source(engine, *, table_name: str):
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO agent_semantic_sources "
            "(table_name, display_name, description, owner_username) "
            "VALUES (:t, :d, '', 'test_evaluation_extractor') "
            "RETURNING id"
        ), {"t": table_name, "d": table_name}).first()
    return row[0]


def _cleanup(engine, doc_id, ver_id, *, semantic_source_ids=None):
    with engine.connect() as conn:
        hint_ids = [r[0] for r in conn.execute(text(
            "SELECT id FROM agent_semantic_hints WHERE std_version_id=:v"
        ), {"v": ver_id}).fetchall()]
        link_ids = [str(r[0]) for r in conn.execute(text(
            "SELECT id FROM std_derived_link WHERE source_version_id=:v"
        ), {"v": ver_id}).fetchall()]
        snap_ids = [str(r[0]) for r in conn.execute(text(
            "SELECT id FROM std_data_model_snapshot "
            "WHERE document_version_id=:v"
        ), {"v": ver_id}).fetchall()]
    with engine.begin() as conn:
        if hint_ids:
            conn.execute(text(
                "DELETE FROM agent_semantic_hints WHERE id = ANY(:ids)"
            ), {"ids": hint_ids})
        if snap_ids:
            conn.execute(text(
                "DELETE FROM std_data_model_snapshot "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": snap_ids})
        if link_ids:
            conn.execute(text(
                "DELETE FROM std_derived_link "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": link_ids})
        if semantic_source_ids:
            conn.execute(text(
                "DELETE FROM agent_semantic_sources WHERE id = ANY(:ids)"
            ), {"ids": list(semantic_source_ids)})
        conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                     {"i": doc_id})


def test_extracts_active_semantic_hint_prediction(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id)
    try:
        SemanticHintStrategy().run(version_id=ver_id, by_user="admin")

        predictions = extract_prediction_set(engine, version_id=ver_id)

        assert predictions.dataset_id == f"predictions:{ver_id}"
        assert any(
            i.strategy == "to_semantic_hint"
            and i.source_key.startswith("data_element:")
            and i.target_kind == "semantic_hint"
            and i.target_key == "cq_dltb.dlbm:other"
            and i.match == {"hint_kind": "other"}
            for i in predictions.items
        )
    finally:
        _cleanup(engine, doc_id, ver_id)


def test_extracts_value_semantics_with_value_domain_identity(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    domain_id = _seed_value_domain(
        engine,
        ver_id,
        code="LAND_USE_ENUM",
        name="Land use",
        items=[("0101", "paddy"), ("0102", "irrigated")],
    )
    _seed_bound_element(
        engine,
        ver_id,
        bound_table="cq_dltb",
        bound_column="dlbm",
        value_domain_id=domain_id,
    )
    try:
        ValueDomainStrategy().run(version_id=ver_id, by_user="admin")

        predictions = extract_prediction_set(engine, version_id=ver_id)

        item = next(i for i in predictions.items
                    if i.strategy == "to_value_semantics")
        assert item.target_key == "cq_dltb.dlbm:value_enum"
        assert item.match == {
            "hint_kind": "value_enum",
            "domain_kind": "enumeration",
            "domain_code": "LAND_USE_ENUM",
            "values": ["0101", "0102"],
        }
    finally:
        _cleanup(engine, doc_id, ver_id)


def test_extracts_synonym_prediction_per_token(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    table_name = f"eval_synonym_{uuid.uuid4().hex[:8]}"
    source_id = _seed_semantic_source(engine, table_name=table_name)
    _seed_bound_element(
        engine,
        ver_id,
        name_zh="land_class_code",
        bound_table=table_name,
        bound_column="dlbm",
        obligation="optional",
    )
    try:
        SynonymStrategy().run(version_id=ver_id, by_user="admin")

        predictions = extract_prediction_set(engine, version_id=ver_id)
        synonym_items = [
            i for i in predictions.items if i.strategy == "to_synonym"
        ]

        assert {i.target_key for i in synonym_items} == {
            f"{table_name}:land_class_code",
        }
        assert synonym_items[0].source_key == f"semantic_source:{table_name}"
        assert synonym_items[0].match == {"synonym": "land_class_code"}
    finally:
        _cleanup(engine, doc_id, ver_id, semantic_source_ids=[source_id])


def test_extracts_data_model_prediction(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id, bound_column="dlbm")
    try:
        DataModelStrategy().run(version_id=ver_id, by_user="admin")

        predictions = extract_prediction_set(engine, version_id=ver_id)

        item = next(i for i in predictions.items
                    if i.strategy == "to_data_model")
        assert item.source_key == f"document_version:{ver_id}"
        assert item.target_kind == "data_model"
        assert item.match["entity_count"] == 1
        assert item.match["attribute_count"] == 1
        assert item.payload["has_ddl"] is True
    finally:
        _cleanup(engine, doc_id, ver_id)

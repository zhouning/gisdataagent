"""Repository tests for the version-level cross-standard impact graph."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from data_agent.standards_platform.analysis import impact_graph


def _nodes_by_id(graph):
    return {n["id"]: n for n in graph["nodes"]}


def _edges_by_type(graph, edge_type):
    return [e for e in graph["edges"] if e["edge_type"] == edge_type]


def test_graph_contains_version_root_and_derivation_edge(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    target_id = str(uuid.uuid4())
    link_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_derived_link "
            "(id, source_kind, source_id, source_version_id, target_kind, "
            "target_table, target_id, derivation_strategy, status) "
            "VALUES (:i, 'clause', :c, :v, 'semantic_hint', "
            "'agent_semantic_hints', :t, 'to_semantic_hint', 'active')"
        ), {"i": link_id, "c": cid, "v": ver_id, "t": target_id})

    graph = impact_graph.version_impact_graph(ver_id, include_similar=False)

    nodes = _nodes_by_id(graph)
    assert graph["version_id"] == ver_id
    assert f"version:{ver_id}" in nodes
    assert nodes[f"version:{ver_id}"]["metadata"]["doc_code"].startswith(
        "T-CONFTEST-"
    )
    derives = _edges_by_type(graph, "derives")
    assert len(derives) == 1
    assert derives[0]["id"] == f"derive:{link_id}"
    assert derives[0]["source"] == f"clause:{cid}"
    assert derives[0]["target"] == f"semantic_hint:{target_id}"
    assert graph["summary"]["by_edge_type"]["derives"] == 1


def test_graph_contains_cross_version_reference_edge(engine, fresh_clause):
    source_clause_id, _, ver_id = fresh_clause
    target_doc_id = str(uuid.uuid4())
    target_ver_id = str(uuid.uuid4())
    target_clause_id = str(uuid.uuid4())
    ref_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_document (id, doc_code, title, source_type, "
                "status, owner_user_id) VALUES (:i, :c, 'target doc', "
                "'draft', 'ingested', 'admin')"
            ), {"i": target_doc_id, "c": f"T-XREF-{target_doc_id[:6]}"})
            conn.execute(text(
                "INSERT INTO std_document_version (id, document_id, "
                "version_label, status, semver_major) VALUES (:i, :d, "
                "'v2.0', 'draft', 2)"
            ), {"i": target_ver_id, "d": target_doc_id})
            conn.execute(text(
                "INSERT INTO std_clause (id, document_id, document_version_id, "
                "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
                "CAST('2' AS ltree), '2', 'clause', 'target')"
            ), {"i": target_clause_id, "d": target_doc_id, "v": target_ver_id})
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, target_kind, "
                "target_clause_id, citation_text, verification_status) "
                "VALUES (:i, :s, 'std_clause', :t, 'cross cite', 'approved')"
            ), {"i": ref_id, "s": source_clause_id, "t": target_clause_id})

        graph = impact_graph.version_impact_graph(ver_id, include_similar=False)

        references = _edges_by_type(graph, "references")
        assert len(references) == 1
        assert references[0]["id"] == f"reference:{ref_id}"
        assert references[0]["source"] == f"clause:{source_clause_id}"
        assert references[0]["target"] == f"clause:{target_clause_id}"
        assert references[0]["metadata"]["target_version_id"] == target_ver_id
        assert graph["summary"]["cross_version_edge_count"] == 1
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": target_doc_id})


def test_graph_contains_source_data_element_reference_edge(engine, fresh_clause):
    _, _, ver_id = fresh_clause
    source_de_id = str(uuid.uuid4())
    target_doc_id = str(uuid.uuid4())
    target_ver_id = str(uuid.uuid4())
    target_clause_id = str(uuid.uuid4())
    ref_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_data_element (id, document_version_id, code, "
                "name_zh) VALUES (:i, :v, 'DE-IMPACT', '影响数据元')"
            ), {"i": source_de_id, "v": ver_id})
            conn.execute(text(
                "INSERT INTO std_document (id, doc_code, title, source_type, "
                "status, owner_user_id) VALUES (:i, :c, 'target doc', "
                "'draft', 'ingested', 'admin')"
            ), {"i": target_doc_id, "c": f"T-XDE-{target_doc_id[:6]}"})
            conn.execute(text(
                "INSERT INTO std_document_version (id, document_id, "
                "version_label, status, semver_major) VALUES (:i, :d, "
                "'v2.0', 'draft', 2)"
            ), {"i": target_ver_id, "d": target_doc_id})
            conn.execute(text(
                "INSERT INTO std_clause (id, document_id, document_version_id, "
                "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
                "CAST('2' AS ltree), '2', 'clause', 'target')"
            ), {"i": target_clause_id, "d": target_doc_id, "v": target_ver_id})
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, "
                "source_data_element_id, target_kind, target_clause_id, "
                "citation_text) "
                "VALUES (:i, :other_clause, :s, 'std_clause', :t, "
                "'data element cite')"
            ), {
                "i": ref_id,
                "other_clause": target_clause_id,
                "s": source_de_id,
                "t": target_clause_id,
            })

        graph = impact_graph.version_impact_graph(ver_id, include_similar=False)

        references = _edges_by_type(graph, "references")
        edge = next(e for e in references if e["id"] == f"reference:{ref_id}")
        assert edge["source"] == f"data_element:{source_de_id}"
        assert edge["target"] == f"clause:{target_clause_id}"
        assert edge["metadata"]["target_version_id"] == target_ver_id
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": target_doc_id})


def test_graph_includes_similar_clause_edges(monkeypatch, fresh_clause):
    source_clause_id, _, ver_id = fresh_clause
    target_clause_id = str(uuid.uuid4())
    target_ver_id = str(uuid.uuid4())

    def fake_find_similar_clauses(*, version_id, top_k, min_similarity):
        assert version_id == ver_id
        assert top_k == 7
        assert min_similarity == 0.91
        return [{
            "source_clause_id": source_clause_id,
            "target_clause_id": target_clause_id,
            "document_version_id": target_ver_id,
            "body_md": "similar target",
            "similarity": 0.9321,
        }]

    monkeypatch.setattr(
        impact_graph.deduper, "find_similar_clauses", fake_find_similar_clauses
    )

    graph = impact_graph.version_impact_graph(
        ver_id, min_similarity=0.91, top_k=7
    )

    similar = _edges_by_type(graph, "similar_clause")
    assert len(similar) == 1
    assert similar[0]["source"] == f"clause:{source_clause_id}"
    assert similar[0]["target"] == f"clause:{target_clause_id}"
    assert similar[0]["score"] == 0.9321
    assert similar[0]["metadata"]["target_version_id"] == target_ver_id
    assert graph["summary"]["by_edge_type"]["similar_clause"] == 1
    assert graph["summary"]["cross_version_edge_count"] == 1


def test_graph_excludes_similar_edges_when_disabled(monkeypatch, fresh_clause):
    _, _, ver_id = fresh_clause

    def fail_find_similar_clauses(**_kwargs):
        raise AssertionError("similar lookup should not be called")

    monkeypatch.setattr(
        impact_graph.deduper, "find_similar_clauses", fail_find_similar_clauses
    )

    graph = impact_graph.version_impact_graph(ver_id, include_similar=False)

    assert _edges_by_type(graph, "similar_clause") == []
    assert "similar_clause" not in graph["summary"]["by_edge_type"]

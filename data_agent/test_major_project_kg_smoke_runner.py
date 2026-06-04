import json

from scripts.synthetic_major_projects.smoke_major_project_kg_nl2sql import (
    _load_questions,
    _missing_expected_fragments,
    _row_count,
    _summarize_result,
)


def test_load_questions_preserves_requested_order(tmp_path):
    bench = tmp_path / "questions.jsonl"
    rows = [
        {"id": "q1", "question": "first"},
        {"id": "q2", "question": "second"},
    ]
    bench.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )

    loaded = _load_questions(bench, ["q2", "q1"])

    assert [row["id"] for row in loaded] == ["q2", "q1"]
    assert [row["question"] for row in loaded] == ["second", "first"]


def test_row_count_accepts_executor_rows_and_data_shapes():
    assert _row_count({"execution": {"rows": 28, "data": []}}) == 28
    assert _row_count({"execution": {"data": [{"a": 1}, {"a": 2}]}}) == 2
    assert _row_count({"rows": 3}) == 3
    assert _row_count({"data": [{"a": 1}]}) == 1


def test_summarize_result_flags_missing_expected_kg_fragments():
    payload = {
        "status": "ok",
        "sql": (
            "SELECT p.project_name FROM mp_project_list p "
            "JOIN kg_nodes n ON p.project_id = n.biz_id "
            "JOIN kg_edges e ON n.node_id = e.source_node_id "
            "WHERE e.edge_type = 'MISSING_STAGE'"
        ),
        "execution": {"rows": 28},
        "semantic": {"candidate_tables": ["mp_project_list", "kg_edges", "kg_nodes"]},
    }

    record = _summarize_result("mp_bench_graph_missing_001", "q", payload)

    assert record["status"] == "ok"
    assert record["row_count"] == 28
    assert record["missing_expected_fragments"] == []


def test_missing_expected_fragments_detects_spatial_overlap_regression():
    assert _missing_expected_fragments("mp_bench_hybrid_spatial_002", "SELECT 1") == [
        "mp_spatial_overlap"
    ]

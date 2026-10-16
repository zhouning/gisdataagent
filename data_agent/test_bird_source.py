"""BIRD source SQL boundary and privilege tests."""

from unittest.mock import MagicMock, patch

import pytest

from data_agent.bird_source import _validated_sql, query_rows, registered_database, visible_bird_sources
from data_agent.nl2sql_grounding import (
    _bird_fk_join_paths, _build_candidate_table, _format_grounding_prompt_compact,
)
from data_agent.runtime_guards import is_safe_sql
from data_agent.semantic_layer import _semantic_source_kind
from data_agent.user_context import current_user_id, current_user_role


@pytest.fixture(autouse=True)
def isolated_identity():
    """Authorization assertions must start from an anonymous request."""
    user = current_user_id.set("anonymous")
    role = current_user_role.set("anonymous")
    try:
        yield
    finally:
        current_user_role.reset(role)
        current_user_id.reset(user)


def test_bird_source_kind_is_not_postgis():
    assert _semantic_source_kind("bird_california_schools.frpm") == "bird_postgres"
    assert _semantic_source_kind("public.roads") == "postgis"


def test_bird_source_requires_owner_or_authenticated_admin():
    conn = MagicMock()
    conn.execute.return_value.first.return_value = ("bird_sample",)
    control = MagicMock()
    control.connect.return_value.__enter__.return_value = conn
    with patch("data_agent.bird_source.get_engine", return_value=control):
        with pytest.raises(PermissionError):
            registered_database("sample")
        user_token = current_user_id.set("bird_benchmark")
        role_token = current_user_role.set("analyst")
        try:
            assert registered_database("sample") == "bird_sample"
            assert conn.execute.call_args.args[1]["username"] == "bird_benchmark"
            assert conn.execute.call_args.args[1]["is_admin"] is False
            current_user_id.set("admin_user")
            current_user_role.set("admin")
            assert registered_database("sample") == "bird_sample"
            assert conn.execute.call_args.args[1]["is_admin"] is True
        finally:
            current_user_role.reset(role_token)
            current_user_id.reset(user_token)


def test_bird_source_visibility_requires_identity():
    conn = MagicMock()
    conn.execute.return_value = [("bird_sample",)]
    assert visible_bird_sources(conn) == set()
    conn.execute.assert_not_called()
    token = current_user_id.set("bird_benchmark")
    try:
        assert visible_bird_sources(conn) == {"bird_sample"}
    finally:
        current_user_id.reset(token)


def test_bird_sql_rewrites_registered_table_and_column():
    sql = _validated_sql("sample", 'SELECT name FROM bird_sample."Team"', {"Team": ["Name"]})
    assert '"Team"' in sql
    assert '"Name"' in sql


def test_bird_sql_normalizes_qualifiers_in_each_scope():
    sql = _validated_sql("sample", '''
        SELECT Patient.id, e.id FROM bird_sample.Patient
        JOIN public.Examination AS e ON Patient.id=e.id
        WHERE EXISTS (SELECT 1 FROM Examination x WHERE x.id=Patient.id)
    ''', {"Patient": ["ID"], "Examination": ["Id"]})
    assert '"Patient"."ID"' in sql
    assert 'e."Id"' in sql
    assert 'x."Id" = "Patient"."ID"' in sql
    assert "bird_sample." not in sql
    assert "public." not in sql


def test_bird_sql_preserves_cte_output_and_quoted_alias():
    sql = _validated_sql("sample", '''
        WITH t AS (SELECT Patient.id AS identifier FROM Patient)
        SELECT t.identifier, "P".id FROM t JOIN Patient "P" ON t.identifier="P".id
    ''', {"Patient": ["ID"]})
    assert 't.identifier' in sql
    assert '"P"."ID"' in sql
    assert 'AS identifier' in sql


@pytest.mark.parametrize("ordering", [
    "DESC NULLS LAST", "ASC NULLS FIRST", "ASC NULLS LAST", "DESC NULLS FIRST",
])
def test_bird_named_parameter_sql_preserves_postgres_null_order(ordering):
    import sqlglot

    sql = f"SELECT Name FROM Team WHERE Score >= :minimum ORDER BY Score {ordering} FETCH FIRST 1 ROW WITH TIES"
    columns = {"Team": ["Name", "Score"]}
    plain = _validated_sql("sample", sql, columns)
    bound = _validated_sql("sample", sql, columns, named_parameters=True)
    assert ":minimum" in bound
    # A dialect can omit a redundant clause, but it must preserve its meaning.
    assert (sqlglot.parse_one(bound, read="postgres").args["order"]
            == sqlglot.parse_one(plain, read="postgres").args["order"])


def test_bird_sql_removes_matching_column_schema_and_rejects_cross_database():
    assert '"Patient"."ID"' in _validated_sql(
        "sample", "SELECT bird_sample.Patient.ID FROM bird_sample.Patient", {"Patient": ["ID"]})
    with pytest.raises(ValueError, match="different database"):
        _validated_sql("sample", "SELECT bird_other.Patient.ID FROM Patient", {"Patient": ["ID"]})
    with pytest.raises(ValueError, match="unregistered table"):
        _validated_sql("sample", '''SELECT * FROM Unknown WHERE EXISTS (
            WITH Unknown AS (SELECT * FROM Patient) SELECT * FROM Unknown)''', {"Patient": ["ID"]})


def test_bird_selected_database_keeps_bridge_tables_and_excludes_other_sources():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    sources = [{"table_name": f"bird_sample.t{i}", "source_kind": "bird_postgres"}
               for i in range(13)]
    sources.append({"table_name": "bird_other.secret", "source_kind": "bird_postgres"})
    schema = {"status": "success", "columns": [{"column_name": "id", "data_type": "integer"}],
              "source_metadata": {"source_kind": "bird_postgres"}}
    with patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value={}), \
         patch("data_agent.nl2sql_grounding.list_semantic_sources", return_value={"status": "success", "sources": sources}), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", return_value=schema), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=10), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""):
        result = build_nl2sql_context("Where is the event held?", schema_filter="bird_sample", family="gemma")
    assert {t["table_name"] for t in result["candidate_tables"]} == {f"bird_sample.t{i}" for i in range(13)}


@pytest.mark.parametrize("question", [
    "What type of bond is there between atoms TR004_8 and TR004_20?",
    "In which Formula_1 race did Lewis Hamilton rank the highest?",
    "What is the name of Walter?",
])
def test_bird_business_names_and_values_are_not_table_or_write_requests(question):
    from data_agent.nl2sql_executor import _should_refuse_nl2sql_question
    assert not _should_refuse_nl2sql_question(question, {"bird_db_id": "sample", "candidate_tables": []})


def test_bird_semantic_rewrite_preserves_relational_join_roles():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites
    context = {"candidate_tables": [
        {"table_name": "bird_sample.cards", "source_kind": "bird_postgres",
         "table_aliases": ["cards"], "columns": [{"column_name": "uuid"}, {"column_name": "name"}]},
        {"table_name": "bird_sample.rulings", "source_kind": "bird_postgres",
         "table_aliases": ["rulings"], "columns": [{"column_name": "uuid"}, {"column_name": "text"}]},
    ]}
    sql, corrections = apply_semantic_sql_rewrites(
        "Find cards and describe the text of their ruling", "SELECT cards.name, rulings.text FROM cards JOIN rulings ON cards.uuid=rulings.uuid", context)
    assert "JOIN rulings" in sql
    assert "semantic_question_alias_table" not in corrections


def test_bird_ast_table_gate_accepts_bare_reference_and_rejects_unknown():
    sql = "SELECT Name FROM Team"
    assert is_safe_sql(sql)[0]
    assert _validated_sql("sample", sql, {"Team": ["Name"]})
    with pytest.raises(ValueError, match="unregistered table"):
        _validated_sql("sample", "SELECT * FROM Other", {"Team": ["Name"]})


@pytest.mark.parametrize("sql", [
    "SELECT * FROM bird_other.Team",
    "SELECT * FROM other.public.Team",
    "SELECT * FROM Unknown",
    "DELETE FROM Team",
    "SELECT * FROM Team; SELECT * FROM Team",
])
def test_bird_sql_rejects_out_of_scope_statements(sql):
    with pytest.raises(ValueError):
        _validated_sql("sample", sql, {"Team": ["Name"]})


def test_bird_query_drops_superuser_privileges_before_execution():
    control_conn = MagicMock()
    control_conn.execute.return_value = [("Team", [{"column_name": "Name"}])]
    control = MagicMock()
    control.connect.return_value.__enter__.return_value = control_conn
    remote_conn = MagicMock()
    result = MagicMock()
    result.keys.return_value = ["Name"]
    result.fetchall.return_value = [("A",)]
    remote_conn.execute.return_value = result
    remote = MagicMock()
    remote.connect.return_value.__enter__.return_value = remote_conn
    with patch("data_agent.bird_source.registered_database", return_value="bird_sample"), \
         patch("data_agent.bird_source.get_engine", return_value=control), \
         patch("data_agent.bird_source._remote_engine", return_value=remote):
        columns, rows, truncated = query_rows("sample", "SELECT Name FROM Team")
    assert (columns, rows, truncated) == (["Name"], [("A",)], False)
    calls = [call.args[0] for call in remote_conn.exec_driver_sql.call_args_list]
    assert calls == ["SET TRANSACTION READ ONLY", "SET LOCAL ROLE pg_read_all_data"]


def test_bird_semantic_metadata_reaches_model_context():
    source = {"table_name": "bird_sample.Orders", "source_kind": "bird_postgres",
              "description": "Orders placed by customers"}
    schema = {
        "columns": [{"column_name": "CustomerID", "data_type": "integer",
                     "sample_values": ["42"]}],
        "source_metadata": {
            "source_kind": "bird_postgres", "primary_keys": ["OrderID"],
            "foreign_keys": [{"column": "CustomerID", "target_table": "Customers",
                              "target_column": "ID"}],
        },
    }
    with patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=10):
        orders = _build_candidate_table(source, schema)
    customers = {"table_name": "bird_sample.Customers", "source_kind": "bird_postgres",
                 "columns": [], "confidence": 0, "row_count_hint": 10}
    other_db = {**customers, "table_name": "bird_other.Customers"}
    paths = _bird_fk_join_paths([orders, customers])
    assert orders["columns"][0]["sample_values"] == ["42"]
    assert orders["primary_keys"] == ["OrderID"]
    assert paths == ['Orders."CustomerID" -> Customers."ID"']
    assert _bird_fk_join_paths([orders, other_db]) == []
    prompt = _format_grounding_prompt_compact({
        "candidate_tables": [orders, customers],
        "warehouse_join_hints": {"table_roles": {}, "join_paths": paths},
    })
    assert "Orders placed by customers" in prompt
    assert 'CustomerID" :: integer' in prompt
    assert paths[0] in prompt

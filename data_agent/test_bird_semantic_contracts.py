import pytest

from data_agent.bird_semantic_contracts import contract_for_tables
from data_agent.seed_semantic_hints_bird import SOURCE_TAG, _rows


def _candidate(db_id: str, name: str, *, foreign_keys=None, columns=()) -> dict:
    return {
        "table_name": f"bird_{db_id}.{name}",
        "source_kind": "bird_postgres",
        "foreign_keys": foreign_keys or [],
        "columns": [{"column_name": column, "quoted_ref": f'"{column}"', "pg_type": "text"}
                    for column in columns],
    }


def test_contract_only_mentions_tables_in_authorized_candidate_set():
    contract = contract_for_tables([
        _candidate("toxicology", "atom"),
        _candidate("toxicology", "molecule"),
    ])
    rendered = " ".join([contract["population"], *contract["rules"]])
    assert "bond -> connected" not in rendered
    assert not contract["population"]
    assert "connected" not in rendered


def test_financial_contract_uses_the_registered_balance_column():
    tables = [_candidate("financial", name, columns=("amount", "payments", "balance", "type")) for name in
              ("account", "card", "client", "disp", "district", "loan", "order", "trans")]
    contract = contract_for_tables(tables)
    rendered = " ".join([contract["population"], *contract["rules"]])
    assert "trans.balance" in rendered
    assert "account.balance" not in rendered


def test_contract_relationships_are_restricted_to_candidate_tables():
    contract = contract_for_tables([
        _candidate("card_games", "cards", foreign_keys=[
            {"column": "setCode", "target_table": "sets", "target_column": "code"},
        ]),
    ])
    assert contract["relationships"] == []


def test_seed_covers_nine_public_databases_without_benchmark_queries():
    rows = _rows()
    assert len(rows) > 9
    assert all(row["scope_type"] == "dataset" for row in rows)
    assert {row["scope_ref"] for row in rows} == {
        "bird_california_schools", "bird_card_games", "bird_codebase_community",
        "bird_european_football_2", "bird_financial", "bird_formula_1",
        "bird_superhero", "bird_thrombosis_prediction", "bird_toxicology",
    }
    assert SOURCE_TAG == "bird_public_semantics_v1"
    assert all("Gold SQL" not in row["hint_text_en"] for row in rows)


@pytest.mark.parametrize("variant", ["compact", "legacy"])
def test_grounding_refresh_removes_rules_for_removed_tables_and_columns(monkeypatch, variant):
    from data_agent.nl2sql_grounding import refresh_nl2sql_grounding_prompt

    monkeypatch.setenv("GDA_NL2SQL_SEMANTIC_RETRIEVAL", "0")
    monkeypatch.setattr("data_agent.nl2sql_metric_grounding.registered_metrics", lambda payload: [])
    hint = {"scope_ref": "bird_financial", "hint_kind": "other", "severity": "info",
            "hint_text_en": "trans.balance is the recorded account balance.",
            "hint_text_zh": "trans.balance is the recorded account balance."}
    calls = []

    def load_hints(candidates, question):
        calls.append([table["table_name"] for table in candidates])
        return [hint]

    monkeypatch.setattr("data_agent.semantic_layer.registered_bird_dataset_hints", load_hints)
    account = _candidate("financial", "account", columns=("account_id",))
    trans = _candidate("financial", "trans", columns=("account_id", "balance"))
    payload = {"user_question": "account balance", "candidate_tables": [account, trans]}
    refresh_nl2sql_grounding_prompt(payload, variant=variant)
    assert hint["hint_text_en"] in payload["grounding_prompt"]
    trans["columns"] = [{"column_name": "account_id", "quoted_ref": '"account_id"', "pg_type": "text"}]
    refresh_nl2sql_grounding_prompt(payload, variant=variant)
    assert not payload["dataset_hints"]
    assert hint["hint_text_en"] not in payload["grounding_prompt"]
    payload["candidate_tables"] = [account]
    refresh_nl2sql_grounding_prompt(payload, variant=variant)
    assert not payload["dataset_hints"]
    assert "trans.balance" not in payload["grounding_prompt"]
    assert calls[-1] == ["bird_financial.account"]


def test_dataset_hints_require_authenticated_identity(monkeypatch):
    from data_agent.semantic_layer import registered_bird_dataset_hints
    from data_agent.user_context import current_user_id

    def unexpected_engine():
        raise AssertionError("Anonymous hint lookup must not open a database connection")

    monkeypatch.setattr("data_agent.semantic_layer.get_engine", unexpected_engine)
    token = current_user_id.set("anonymous")
    try:
        assert registered_bird_dataset_hints([_candidate("financial", "trans")]) == []
    finally:
        current_user_id.reset(token)

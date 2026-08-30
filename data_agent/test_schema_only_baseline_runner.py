from __future__ import annotations


def test_schema_only_prompt_contains_only_schema_and_question():
    from scripts.nl2sql_bench_cq.run_cq_schema_only_matrix import build_user_prompt

    schema = 'CREATE TABLE public.cq_example ("value" integer);'
    question = "统计记录数"
    prompt = build_user_prompt(schema, question)

    assert schema in prompt
    assert question in prompt
    assert "golden_sql" not in prompt
    assert "few-shot" not in prompt
    assert "semantic" not in prompt.casefold()


def test_schema_only_model_matrix_is_seven_distinct_models():
    from scripts.nl2sql_bench_cq.run_cq_schema_only_matrix import MODEL_PROFILES

    assert len(MODEL_PROFILES) == 7
    assert len({profile.model for profile in MODEL_PROFILES.values()}) == 7
    assert sum(profile.local_ollama for profile in MODEL_PROFILES.values()) == 4


def test_schema_only_pipeline_contract_disables_product_assistance():
    from scripts.nl2sql_bench_cq.run_cq_schema_only_matrix import SCHEMA_ONLY_SYSTEM_PROMPT

    forbidden = (
        "CQ_GEO_",
        "golden_sql",
        "cq_buildings_2021",
        "DLBM",
        "DLMC",
        "BSM",
        "TBMJ",
    )
    assert not any(value in SCHEMA_ONLY_SYSTEM_PROMPT for value in forbidden)

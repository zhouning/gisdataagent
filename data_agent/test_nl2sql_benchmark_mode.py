"""Smoke tests for benchmark NL2SQL agent prompt guardrails."""
import importlib.util
from pathlib import Path


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_cq_eval_has_enhanced_mode_constant():
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_cq" / "run_cq_eval.py"),
        "run_cq_eval_mod",
    )
    assert hasattr(mod, "PROMPT_ENHANCED")


def test_run_cq_eval_import_is_lazy_runtime():
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_cq" / "run_cq_eval.py"),
        "run_cq_eval_mod_lazy",
    )
    assert hasattr(mod, "_init_runtime")
    assert mod._client is None


def test_cq_prompt_discourages_limit_for_exact_filtered_answers():
    """Production NL2SQL prompt's LIMIT policy must discourage default-LIMIT
    on exact/filtered queries. Post-v7-P0-pre the gemini prompt is the
    canonical source.
    """
    from data_agent import prompts_nl2sql
    instruction = prompts_nl2sql.load_system_instruction("gemini")

    assert "add LIMIT only for full-table browsing/previews" in instruction
    assert "Do NOT add LIMIT when the question asks for filtered result sets or exact answers" in instruction
    assert "ALWAYS add LIMIT unless aggregating" not in instruction


def test_cq_prompt_prefers_exact_match_over_code_expansion():
    """Semantic-layer workflow mandates exact-value filter preference over
    hierarchy/code expansion. Post-v7-P0-pre this is expressed generically
    (no DLMC/DLBM literals) because dataset-specific column names come from
    the runtime-injected grounding context, not the prompt.
    """
    from data_agent import prompts_nl2sql
    instruction = prompts_nl2sql.load_system_instruction("gemini")

    # Generic form: "prefer exact filter" + hierarchy-only-for-category-semantics
    assert "prefer exact filter" in instruction
    assert "hierarchy/code expansion" in instruction and "category-level semantics" in instruction
    # Negative: must NOT name CQ-specific columns
    assert "DLMC" not in instruction
    assert "DLBM LIKE" not in instruction


def test_bird_prompt_does_not_force_limit_for_all_selects():
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "nl2sql_agent.py"),
        "bird_nl2sql_agent_mod",
    )
    instruction = mod.build_nl2sql_agent().instruction

    assert "LIMIT only for preview/full-scan situations" in instruction
    assert "对于精确过滤或聚合问题，应返回精确答案，不要强制添加 LIMIT" in instruction
    assert "所有 SELECT 查询必须包含 LIMIT" not in instruction


def test_production_nl2sql_prompt_aligned_with_bird_limit_policy():
    """Production @NL2SQL agent must carry the LIMIT-only-for-preview policy.

    After v7 alignment, agent.py no longer hard-codes the prompt — it is loaded
    from prompts_nl2sql/<family>/system_instruction.md. Test the loaded prompt
    text directly.
    """
    from data_agent import prompts_nl2sql
    instruction = prompts_nl2sql.load_system_instruction("gemini")

    assert "add LIMIT only for full-table browsing/previews" in instruction
    assert "Do NOT add LIMIT when the question asks for filtered result sets or exact answers" in instruction
    assert "所有 SELECT 查询必须包含 LIMIT" not in instruction


def test_cq_prompt_uses_knn_operator_for_nearest_neighbor():
    """KNN ranking must use <-> not ST_Distance. Tested against production
    Gemini prompt (the same file that backs both production @NL2SQL and
    the v7 full benchmark agent).
    """
    from data_agent import prompts_nl2sql
    instruction = prompts_nl2sql.load_system_instruction("gemini")

    # Must explicitly mandate <-> for KNN ORDER BY ranking
    assert "<->" in instruction, "Prompt must mention the PostGIS KNN operator <->"

    # Must contain an explicit NEVER/do-not rule forbidding ORDER BY ST_Distance for KNN
    # (allow for optional backtick formatting around the function name)
    import re
    has_explicit_ban = bool(re.search(
        r"(NEVER|never|do NOT|not)\s+use\s+`?ORDER\s+BY\s+ST_Distance",
        instruction,
    ))
    assert has_explicit_ban, (
        "Prompt must explicitly forbid 'ORDER BY ST_Distance' for KNN ranking."
    )

    # Must state that ST_Distance belongs in the SELECT list (for reporting distance)
    has_select_guidance = (
        "SELECT list" in instruction
        or "in the SELECT" in instruction
        or "SELECT 列" in instruction
    )
    assert has_select_guidance, (
        "Prompt must clarify that ST_Distance is for the SELECT list (reported distance), "
        "not for ORDER BY ranking."
    )


def test_run_cq_eval_record_includes_intent_field():
    """run_one() in run_cq_eval.py should populate `intent` and `intent_source`."""
    src = (Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_cq" / "run_cq_eval.py").read_text(encoding="utf-8")
    assert 'rec["intent"]' in src or "rec['intent']" in src
    assert 'rec["intent_source"]' in src or "rec['intent_source']" in src


def test_run_bird_eval_record_includes_intent_field():
    """run_one() in run_pg_eval.py should populate `intent` and `intent_source`."""
    src = (Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "run_pg_eval.py").read_text(encoding="utf-8")
    assert 'rec["intent"]' in src or "rec['intent']" in src
    assert 'rec["intent_source"]' in src or "rec['intent_source']" in src



def test_production_nl2sql_prompt_mentions_intent_routing():
    """Production @NL2SQL prompt should establish intent-driven grounding.

    Post-v7: the "intent routing" concept is realised by mandating that the
    agent FIRST call resolve_semantic_context (which classifies intent and
    returns scoped hints) before generating SQL. Verify the prompt enforces
    this workflow rather than the old free-form "根据意图 ..." prose.
    """
    from data_agent import prompts_nl2sql
    instruction = prompts_nl2sql.load_system_instruction("gemini")

    assert "resolve_semantic_context" in instruction
    assert "Mandatory Workflow" in instruction


# ---------------------------------------------------------------------------
# v7 P0-pre: de-hardcoding CQ business knowledge into the semantic-layer DB
# ---------------------------------------------------------------------------

_CQ_HARDCODE_FINGERPRINTS = [
    "行政区划代码", "SHAPE_Area", "SHAPE_Length",
    "maxspeed", "500000", "全市总计",
    "cq_amap_poi_2024", "cq_district_population",
    "cq_baidu_aoi_2024", "cq_buildings_2021",
    "第一分类", "扩样后人口", "职住格网是否重合",
    "DLMC", "DLBM", "TBMJ", "BSM",
]


def test_prompts_do_not_contain_cq_specific_dataset_rules():
    """Regression guard: system_instruction.md for every family must be
    dataset-agnostic. CQ-specific business rules belong in the
    agent_semantic_hints DB table, not in the prompt source.
    """
    from data_agent import prompts_nl2sql
    leaks = {}
    for family in ("gemini", "deepseek", "qwen", "gemma"):
        instruction = prompts_nl2sql.load_system_instruction(family)
        hit = [fp for fp in _CQ_HARDCODE_FINGERPRINTS if fp in instruction]
        if hit:
            leaks[family] = hit
    assert not leaks, (
        "CQ-specific dataset knowledge leaked into system_instruction.md. "
        "Move it to agent_semantic_hints / agent_semantic_registry.value_semantics "
        f"via seed_semantic_hints_cq.py. Leaks: {leaks}"
    )


def test_common_schema_quoting_rules_file_removed():
    """common/schema_quoting_rules.md was CQ-specific and is deprecated.
    Its content is now DB-backed."""
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "data_agent" / "prompts_nl2sql" / "common" / "schema_quoting_rules.md"
    assert not p.exists(), (
        "common/schema_quoting_rules.md must be removed post-v7-P0-pre; "
        "its content has been externalised to the semantic-layer DB."
    )


def test_seed_semantic_hints_cq_has_expected_rules():
    """Seed payload must cover the 20 Category-A rules identified in the
    P0-pre audit. We assert structure here; DB-write idempotency is
    separately exercised in integration tests.
    """
    from data_agent.seed_semantic_hints_cq import _HINTS, _VALUE_SEMANTICS

    # At least 12 hint rows (we collapsed some rules into value_semantics)
    assert len(_HINTS) >= 12

    # Every hint carries required keys
    required = {"scope_type", "scope_ref", "hint_kind", "hint_text_zh", "severity"}
    for h in _HINTS:
        assert required.issubset(h.keys()), f"Missing keys in hint: {h}"
        assert h["scope_type"] in ("table", "column", "dataset")
        assert h["severity"] in ("info", "warn", "critical")

    # Key rules are present by scope_ref
    scope_refs = {h["scope_ref"] for h in _HINTS}
    assert "cq_district_population.行政区划代码" in scope_refs
    assert "cq_osm_roads_2021.maxspeed" in scope_refs
    assert "cq_land_use_dltb.SHAPE_Area" in scope_refs
    assert "cq_historic_districts" in scope_refs

    # value_semantics covers expected columns
    vs_cols = {(t, c) for t, c, _ in _VALUE_SEMANTICS}
    assert ("cq_land_use_dltb", "SHAPE_Area") in vs_cols
    assert ("cq_osm_roads_2021", "maxspeed") in vs_cols
    assert ("cq_baidu_aoi_2024", "第一分类") in vs_cols


def test_resolve_semantic_context_returns_new_hint_keys():
    """resolve_semantic_context payload must now expose table_hints,
    column_hints, and (via build_nl2sql_context) large_tables — regardless
    of whether any hints match the specific query.
    """
    from unittest.mock import patch
    from data_agent.semantic_layer import resolve_semantic_context
    # Force the no-DB short-circuit so this test does not depend on
    # cached state or pollute downstream tests.
    with patch.dict("os.environ", {"NL2SQL_DISABLE_SEMANTIC": "1"}):
        result = resolve_semantic_context("列出所有地类")
    assert "table_hints" in result
    assert "column_hints" in result
    assert isinstance(result["table_hints"], list)
    assert isinstance(result["column_hints"], dict)


def test_grounding_prompt_emits_business_rules_section_when_hints_present():
    """When resolve_semantic_context returns non-empty hints, the formatted
    grounding prompt must include a `## [业务规则]` or `## Business rules`
    section so the LLM sees them.
    """
    from data_agent.nl2sql_grounding import _format_grounding_prompt_legacy, _format_grounding_prompt_compact

    payload = {
        "candidate_tables": [],
        "semantic_hints": {
            "spatial_ops": [], "region_filter": None,
            "hierarchy_matches": [], "metric_hints": [], "sql_filters": [],
        },
        "table_hints": [{
            "scope_ref": "cq_district_population",
            "hint_kind": "exclusion",
            "hint_text_zh": "测试：全市总计排除",
            "hint_text_en": "test: exclude city total",
            "severity": "warn",
        }],
        "column_hints": {
            "cq_osm_roads_2021.maxspeed": [{
                "scope_ref": "cq_osm_roads_2021.maxspeed",
                "hint_kind": "value_enum",
                "hint_text_zh": "maxspeed=0 表示未设置",
                "hint_text_en": "maxspeed=0 means unset",
                "severity": "warn",
            }],
        },
        "large_tables": ["cq_amap_poi_2024"],
        "few_shots": [],
        "intent": "UNKNOWN",
    }

    legacy_out = _format_grounding_prompt_legacy(payload)
    assert "## [业务规则]" in legacy_out
    assert "测试：全市总计排除" in legacy_out
    assert "maxspeed=0 表示未设置" in legacy_out
    assert "## 大表" in legacy_out
    assert "cq_amap_poi_2024" in legacy_out

    compact_out = _format_grounding_prompt_compact(payload)
    assert "## Business rules" in compact_out
    assert "test: exclude city total" in compact_out  # EN preferred for compact
    assert "## Large tables" in compact_out

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
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_cq" / "nl2sql_agent.py"),
        "cq_nl2sql_agent_mod",
    )
    instruction = mod.build_nl2sql_agent().instruction

    assert "For large tables (>100K rows): add LIMIT only for full-table browsing/previews" in instruction
    assert "Do NOT add LIMIT when the question asks for filtered result sets or exact answers" in instruction
    assert "ALWAYS add LIMIT unless aggregating" not in instruction


def test_cq_prompt_prefers_dlmc_exact_match_over_code_expansion():
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_cq" / "nl2sql_agent.py"),
        "cq_nl2sql_agent_mod_dlmc",
    )
    instruction = mod.build_nl2sql_agent().instruction

    assert "If the question explicitly names DLMC/地类名称, prefer exact filter on \"DLMC\"" in instruction
    assert "Use hierarchy/code expansion (e.g., DLBM LIKE ...) only when user asks category-level semantics" in instruction
    assert "USE the `sql_filters` directly in your SQL" not in instruction


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
    content = (Path(__file__).resolve().parents[1] / "data_agent" / "agent.py").read_text(encoding="utf-8")

    assert "LIMIT 仅用于预览/全表浏览场景" in content
    assert "对于精确过滤或聚合问题，应返回精确答案，不要强制加 LIMIT" in content
    assert "所有 SELECT 查询必须包含 LIMIT" not in content


def test_cq_prompt_uses_knn_operator_for_nearest_neighbor():
    """CQ_GEO_HARD_02: KNN queries must use <-> operator for ORDER BY, not ST_Distance.

    The prompt must contain an explicit prohibition against ORDER BY ST_Distance for
    nearest-neighbor ranking, and must state that ST_Distance belongs only in the
    SELECT list for reporting the computed distance value.
    """
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_cq" / "nl2sql_agent.py"),
        "cq_nl2sql_agent_mod_knn",
    )
    instruction = mod.build_nl2sql_agent().instruction

    # Must explicitly mandate <-> for KNN ORDER BY ranking
    assert "<->" in instruction, "Prompt must mention the PostGIS KNN operator <->"

    # Must contain an explicit NEVER/do-not rule forbidding ORDER BY ST_Distance for KNN
    has_explicit_ban = (
        "NEVER use ORDER BY ST_Distance" in instruction
        or "never use ORDER BY ST_Distance" in instruction
        or "do NOT use ORDER BY ST_Distance" in instruction
        or "not use ORDER BY ST_Distance" in instruction
    )
    assert has_explicit_ban, (
        "Prompt must explicitly forbid 'ORDER BY ST_Distance' for KNN ranking. "
        "Add a rule like: NEVER use ORDER BY ST_Distance(...) for nearest-neighbor ranking."
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


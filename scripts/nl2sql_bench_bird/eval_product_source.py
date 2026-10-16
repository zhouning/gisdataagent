"""Score the registered BIRD source through the production NL2Semantic2SQL call."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(ROOT / "data_agent" / ".env", override=False)
load_dotenv(ROOT / "data_agent" / ".bird.env", override=False)

from data_agent.bird_source import query_rows, registered_database  # noqa: E402
from data_agent.nl2sql_executor import run_nl2semantic2sql  # noqa: E402
from data_agent.user_context import current_user_id, current_user_role  # noqa: E402
from data_agent.user_context import current_nl2sql_llm_calls  # noqa: E402
from data_agent.openai_compatible_llm import OpenAICompatibleLLMConfig  # noqa: E402
from data_agent.llm_call_budget import (  # noqa: E402
    BudgetDenied, active_budget, budget_question, evaluation_budget, use_budget,
)
from product_manifest import deployed_model, public_settings  # noqa: E402
from check_product_acceptance import model_call_errors, query_route_errors  # noqa: E402
from run_remote_bird_eval import RemoteBirdRuntime, compare_results  # noqa: E402

BENCHMARK = ROOT / "benchmarks" / "bird_pg_heldout_150.json"
DEFAULT_OUT = ROOT / "data_agent" / "nl2sql_eval_results" / "bird_product_heldout_150"


class ProductIntegrationFault(RuntimeError):
    def __init__(self, code: str, question_id: int):
        self.code = code
        self.question_id = question_id
        super().__init__(code)


def integration_fault(result: dict, manifest: dict | None = None) -> str | None:
    """Stop a diagnostic on broken contracts/transport, not an incorrect SQL result."""
    if manifest is not None and query_route_errors(manifest, [result]):
        return "query_route_contract"
    plan = result.get("answer_plan") or {}
    if plan.get("status") in {"rejected", "interrupted"} and any(
        r.get("kind") == "response_schema" for r in plan.get("rejections") or []
    ):
        return "answer_plan_response_schema"
    if any(call.get("status") == "failed" for call in result.get("llm_calls") or []):
        return "model_transport_failure"
    return None


def _fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def run_manifest(benchmark: Path, questions: list[dict]) -> dict:
    from sqlalchemy import text
    from data_agent.db_engine import get_engine
    from data_agent.nl2sql_model_profile import resolve_nl2sql_model_profile

    code_files = ["data_agent/bird_source.py", "data_agent/nl2sql_executor.py",
                  "data_agent/nl2sql_grounding.py", "data_agent/nl2sql_semantic_rewrite.py",
                  "data_agent/sql_postprocessor.py", "data_agent/runtime_guards.py",
                  "data_agent/nl2sql_model_profile.py", "data_agent/openai_compatible_llm.py",
                  "data_agent/llm_reasoning.py", "data_agent/nl2sql_generation_policy.py",
                  "data_agent/nl2sql_relational_review.py", "data_agent/nl2sql_literal_grounding.py",
                  "data_agent/nl2sql_review_pipeline.py", "data_agent/semantic_layer.py",
                  "data_agent/semantic_catalog.yaml",
                  "data_agent/nl2sql_metric_grounding.py",
                  "data_agent/nl2sql_metric_compiler.py", "data_agent/nl2sql_field_roles.py",
                  "data_agent/nl2sql_metric_grain.py", "data_agent/nl2sql_answer_bindings.py",
                  "data_agent/nl2sql_relational_bindings.py",
                  "data_agent/nl2sql_condition_roles.py",
                  "data_agent/nl2sql_value_presence.py",
                  "data_agent/llm_call_budget.py",
                  "data_agent/nl2sql_semantic_retrieval.py",
                  "data_agent/nl2sql_relationship_retrieval.py",
                  "data_agent/nl2sql_prompt_metadata.py", "data_agent/nl2sql_output_contracts.py",
                  "data_agent/bird_semantic_contracts.py",
                  "data_agent/seed_semantic_hints_bird.py",
                  "data_agent/nl2sql_answer_plan.py",
                  "data_agent/nl2sql_ranking_contract.py",
                  "data_agent/nl2sql_dimension_contract.py",
                  "data_agent/nl2sql_output_contract.py",
                  "data_agent/nl2sql_output_projection.py",
                  "data_agent/nl2sql_ratio_contract.py",
                  "data_agent/nl2sql_literal_contract.py",
                  "data_agent/nl2sql_categorical_contract.py",
                  "data_agent/nl2sql_reference_ranges.py",
                  "data_agent/nl2sql_registered_ir.py",
                  "data_agent/nl2sql_route_policy.py",
                  "data_agent/nl2sql_observability.py",
                  "data_agent/nl2sql_candidates.py",
                  "data_agent/nl2sql_intent.py",
                  "data_agent/semantic_query_ir.py",
                  "scripts/nl2sql_bench_bird/product_manifest.py",
                  "scripts/nl2sql_bench_bird/check_product_acceptance.py",
                  "scripts/nl2sql_bench_bird/snapshot_product_data.py",
                  "scripts/nl2sql_bench_bird/eval_product_source.py",
                  "scripts/nl2sql_bench_bird/run_online_product.py",
                  "scripts/nl2sql_bench_bird/run_remote_bird_eval.py"]
    code = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in code_files}
    databases = sorted({q["db_id"] for q in questions})
    with get_engine().connect() as conn:
        tables = [tuple(row) for row in conn.execute(text("""
            SELECT db_id,table_name,columns_json,foreign_keys_json,primary_keys_json,description,estimated_rows
            FROM agent_bird_tables WHERE db_id=ANY(:ids) ORDER BY db_id,table_name
        """), {"ids": databases})]
        fields = [tuple(row) for row in conn.execute(text("""
            SELECT table_name,column_name,semantic_domain,aliases,description,unit,value_semantics
            FROM agent_semantic_registry WHERE split_part(table_name,'.',1)=ANY(:sources)
            ORDER BY table_name,column_name
        """), {"sources": [f"bird_{db}" for db in databases]})]
        sources = [tuple(row) for row in conn.execute(text("""
            SELECT table_name,display_name,description,synonyms,suggested_analyses,owner_username
            FROM agent_semantic_sources WHERE split_part(table_name,'.',1)=ANY(:sources)
            ORDER BY table_name
        """), {"sources": [f"bird_{db}" for db in databases]})]
        registry_anchors = [tuple(row) for row in conn.execute(text("""
            SELECT id,table_name,owner_username FROM agent_semantic_sources
            WHERE split_part(table_name,'.',1)=ANY(:sources) ORDER BY table_name
        """), {"sources": [f"bird_{db}" for db in databases]})]
        hints = [tuple(row) for row in conn.execute(text("""
            SELECT scope_type,scope_ref,hint_kind,hint_text_zh,hint_text_en,severity,trigger_keywords
            FROM agent_semantic_hints WHERE split_part(scope_ref,'.',1)=ANY(:sources)
            ORDER BY scope_ref,scope_type,hint_kind,hint_text_en,hint_text_zh
        """), {"sources": [f"bird_{db}" for db in databases]})]
        metrics = [tuple(row) for row in conn.execute(text("""
            SELECT metric_name,definition,domain,description,unit,aliases,owner_username,semantic_contract
            FROM agent_semantic_metrics WHERE split_part(domain,'.',1)=ANY(:sources)
            ORDER BY domain,metric_name,owner_username
        """), {"sources": [f"bird_{db}" for db in databases]})]
    config = OpenAICompatibleLLMConfig.from_env()
    settings = public_settings()
    from data_agent.nl2sql_route_policy import resolve_bird_query_policy
    from snapshot_product_data import fingerprint_sources
    snapshot = fingerprint_sources(databases)
    # Snapshot timestamps are deliberately excluded from the stable manifest.
    # The raw table counts and ordered row digests remain reviewable.
    source_data = {key: snapshot[key] for key in ("version", "tables", "fingerprint_sha256")}
    return {"benchmark": benchmark.name, "benchmark_sha256": hashlib.sha256(benchmark.read_bytes()).hexdigest(),
            "question_ids": [q["question_id"] for q in questions], "databases": databases,
            "semantic_sha256": _fingerprint({"tables": tables, "fields": fields, "sources": sources,
                                             "hints": hints, "metrics": metrics}),
            "registered_source_anchors_sha256": _fingerprint(registry_anchors),
            "metric_sha256": _fingerprint(metrics), "metric_count": len(metrics),
            "code_sha256": code,
            "model_profile": resolve_nl2sql_model_profile(config.model, provider=config.provider).to_dict(),
            "deployed_model": deployed_model(config),
            "source_data": source_data,
            "settings": settings, "query_policy": resolve_bird_query_policy().evidence(),
            "product_inputs": "question text and authorized database only",
            "grading_version": "bird-unordered-five-decimal-v1",
            "call_budget_policy": active_budget().policy if active_budget() else None}


def _bucket(records: list[dict], field: str) -> dict:
    groups = defaultdict(list)
    for record in records:
        groups[record[field]].append(record)
    return {key: {"n": len(items), "correct": sum(x["correct"] for x in items),
                  "execution_accuracy": round(sum(x["correct"] for x in items) / len(items), 4)}
            for key, items in sorted(groups.items())}


def summarize(records: list[dict]) -> dict:
    n = len(records)
    correct = sum(item["correct"] for item in records)
    valid = sum(item["prediction_status"] == "ok" for item in records)
    categories = Counter(item["failure_category"] for item in records if not item["correct"])
    return {"n": n, "correct": correct,
            "execution_accuracy": round(correct / n, 4) if n else None,
            "valid_sql": valid, "valid_sql_rate": round(valid / n, 4) if n else None,
            "gold_executable": sum(item["gold_status"] == "ok" for item in records),
            "by_database": _bucket(records, "db_id"),
            "by_difficulty": _bucket(records, "difficulty"),
            "failure_categories": dict(categories),
            "query_profiles": dict(Counter((r.get("query_policy") or {}).get("profile", "unrecorded") for r in records)),
            "registered_ir_statuses": dict(Counter((r.get("registered_ir") or {}).get("status", "unrecorded") for r in records)),
            "sql_fallback_count": sum((r.get("registered_ir") or {}).get("fallback") == "existing_sql_generator" for r in records),
            "unsupported_count": sum(r.get("product_status") == "unsupported" for r in records),
            "rejected_count": sum(r.get("product_status") == "rejected" for r in records),
            "model": os.environ.get("NL2SQL_AGENT_MODEL") or os.environ.get("GDA_LLM_MODEL"),
            "provider": os.environ.get("GDA_LLM_PROVIDER"),
            "product_entrypoint": "data_agent.nl2sql_executor.run_nl2semantic2sql",
            "grading": "unordered multiset (bag) equality, including duplicate counts; numeric values rounded to five decimals",
            "gold_adaptation": "BIRD source SQL identifiers and imported text date columns adapted for PostgreSQL only during gold execution",
            "notes": "Only question text was passed to the product. Benchmark evidence and gold SQL were used solely for scoring.",
            "generated_at": datetime.now(timezone.utc).isoformat()}


def evaluate_one(question: dict, runtime: RemoteBirdRuntime) -> dict:
    db_id = question["db_id"]
    registered_database(db_id)
    started = time.perf_counter()
    try:
        with budget_question(str(question["question_id"])):
            product = json.loads(run_nl2semantic2sql(question["question"], bird_db_id=db_id))
    except BudgetDenied as exc:
        exc.evidence = {"question_id":question["question_id"],
                        "llm_calls":current_nl2sql_llm_calls.get()}
        raise
    except Exception as exc:
        product = {"status": "error", "error": str(exc), "sql": ""}
    # The product may return a structured failure after catching an admission
    # error. Stop the batch before scoring/continuing instead of silently
    # turning budget exhaustion into hundreds of unsuccessful requests.
    if active_budget() and active_budget().last_denial:
        error = BudgetDenied(active_budget().last_denial)
        error.evidence = {"question_id":question["question_id"],
                          "llm_calls":product.get("llm_calls") or current_nl2sql_llm_calls.get(),
                          "answer_plan":product.get("answer_plan") or {}}
        raise error
    latency = round((time.perf_counter() - started) * 1000)
    execution = product.get("execution") or {}
    semantic = product.get("semantic") or {}
    if os.environ.get("NL2SQL_DISABLE_FEWSHOT") == "1" and product.get("sql"):
        policy = semantic.get("few_shot_policy") or {}
        if (semantic.get("few_shot_count") != 0 or policy.get("enabled") is not False
                or policy.get("retrieved") is not False):
            raise RuntimeError("Product reference-query retrieval differs from the disabled evaluation contract")
    calls = product.get("llm_calls") or current_nl2sql_llm_calls.get()
    sql = product.get("sql") or ""
    pred_status = execution.get("status") or product.get("status") or "error"
    pred_error = execution.get("error") or product.get("error")
    pred_rows = None
    pred_truncated = False
    if pred_status == "ok" and sql:
        try:
            if "sql_parameters" in product:
                _, pred_rows, pred_truncated = query_rows(db_id, sql, parameters=product["sql_parameters"])
            else:
                _, pred_rows, pred_truncated = query_rows(db_id, sql)
        except Exception as exc:
            pred_status, pred_error = "error", str(exc)
    gold = runtime.execute(db_id, question["SQL"], gold_compat=True)
    correct = bool(pred_status == "ok" and gold["status"] == "ok" and not pred_truncated
                   and compare_results(gold["rows"], pred_rows))
    if correct:
        category = "correct"
    elif gold["status"] != "ok":
        category = "gold_execution_error"
    elif pred_status != "ok":
        category = "generation_or_execution_error"
    elif pred_truncated:
        category = "result_limit"
    else:
        category = "wrong_result"
    return {"question_id": question["question_id"], "db_id": db_id,
            "difficulty": question.get("difficulty", "unknown"),
            "question": question["question"], "sql": sql,
            "raw_sql": product.get("raw_sql"),
            "retry_attempts": (product.get("self_correction") or {}).get("attempts") or [],
            "gold_sql": question["SQL"], "gold_execution_sql": gold.get("sql"),
            "product_status": product.get("status"), "prediction_status": pred_status,
            "prediction_error": pred_error, "gold_status": gold["status"],
            "gold_error": gold.get("error"), "correct": int(correct),
            "failure_category": category, "latency_ms": latency,
            "candidate_tables": (product.get("semantic") or {}).get("candidate_tables") or [],
            "few_shot_count": semantic.get("few_shot_count"),
            "few_shot_policy": semantic.get("few_shot_policy") or {},
            "semantic_retrieval": semantic.get("retrieval") or {},
            "corrections": product.get("corrections") or [],
            "llm_usage": product.get("llm_usage") or {},
            "observability": product.get("observability") or {},
            "llm_calls": calls,
            "semantic_review": product.get("semantic_review") or {},
            "answer_plan": product.get("answer_plan") or {},
            "binding_audits": product.get("binding_audits") or [],
            "output_projection_audits": product.get("output_projection_audits") or [],
            "registered_ir": product.get("registered_ir") or {},
            "query_policy": product.get("query_policy") or {},
            "metric_compilation": product.get("metric_compilation") or {},
            "condition_roles": product.get("condition_roles") or [],
            "candidate_selection": product.get("candidate_selection") or {},
            "sql_parameters": product.get("sql_parameters"),
            "reference_range_review": product.get("reference_range_review") or {},
            "structural_review": product.get("structural_review") or {},
            "categorical_review": product.get("categorical_review") or [],
            "dimension_review": product.get("dimension_review") or [],
            "output_review": product.get("output_review") or [],
            "initial_output_review": product.get("initial_output_review") or [],
            "prediction_row_count": len(pred_rows) if pred_rows is not None else None,
            "gold_row_count": len(gold["rows"]) if gold["rows"] is not None else None}


def main() -> None:
    current_user_id.set("bird_benchmark")
    current_user_role.set("analyst")
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--benchmark", type=Path, default=BENCHMARK)
    parser.add_argument("--ids", help="Comma-separated question IDs; regression diagnosis only")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--budget-policy", type=Path, help="Reviewed public request/cost ceiling policy JSON")
    parser.add_argument("--budget-ledger", type=Path, help="Absolute persistent SQLite ledger; reuse across restarts")
    args = parser.parse_args()
    online = OpenAICompatibleLLMConfig.from_env().provider not in {"ollama", "lm_studio"}
    if bool(args.budget_policy) != bool(args.budget_ledger) or (online and not args.budget_policy):
        parser.error("Online evaluation requires --budget-policy and --budget-ledger before any evaluation")
    questions = json.loads(args.benchmark.read_text(encoding="utf-8"))
    if args.ids:
        selected_ids = {int(item.strip()) for item in args.ids.split(",")}
        questions = [q for q in questions if q["question_id"] in selected_ids]
        if selected_ids != {q["question_id"] for q in questions}:
            parser.error("Some selected question IDs are absent from the benchmark")
    if args.limit:
        questions = questions[:args.limit]
    if args.budget_policy:
        budget = evaluation_budget(args.out_dir, args.budget_ledger, json.loads(args.budget_policy.read_text()))
        with use_budget(budget):
            try:
                _run_evaluation(args, questions)
            except BudgetDenied as exc:
                args.out_dir.mkdir(parents=True, exist_ok=True)
                (args.out_dir / "stopped.json").write_text(json.dumps({
                    "status": "stopped_budget", "reason": exc.code,
                    "planned_n": len(questions), "budget": budget.snapshot(),
                    "interrupted_question": exc.evidence,
                    "is_complete_accuracy_result": False,
                }, indent=2) + "\n")
                raise
            except ProductIntegrationFault as exc:
                (args.out_dir / "stopped.json").write_text(json.dumps({
                    "status": "stopped_integration_fault", "reason": exc.code,
                    "interrupted_question_id": exc.question_id, "planned_n": len(questions),
                    "budget": budget.snapshot(), "is_complete_accuracy_result": False,
                }, indent=2) + "\n")
                raise
            finally:
                args.out_dir.mkdir(parents=True, exist_ok=True)
                (args.out_dir / "budget_summary.json").write_text(json.dumps(budget.snapshot(), indent=2) + "\n")
    else:
        _run_evaluation(args, questions)


def _run_evaluation(args, questions):
    args.out_dir.mkdir(parents=True, exist_ok=True)
    record_path = args.out_dir / "records.jsonl"
    manifest_path = args.out_dir / "manifest.json"
    manifest = run_manifest(args.benchmark, questions)
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise RuntimeError("Evaluation configuration changed; use a new output directory")
    elif record_path.exists():
        raise RuntimeError("Existing records have no configuration manifest; use a new output directory")
    else:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    records = {}
    if record_path.exists():
        for line in record_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                records[record["question_id"]] = record
    # Restarting the same run cannot skip a persisted integration fault and
    # silently spend the remaining budget on later questions.
    for question in questions:
        prior = records.get(question["question_id"])
        fault = integration_fault(prior, manifest) if prior else None
        if fault:
            raise ProductIntegrationFault(fault, question["question_id"])
    runtime = RemoteBirdRuntime(
        os.environ["BIRD_PG_HOST"], int(os.environ.get("BIRD_PG_PORT", "5432")),
        os.environ["BIRD_PG_USER"], os.environ["BIRD_PG_PASSWORD"],
        int(os.environ.get("BIRD_STATEMENT_TIMEOUT_MS", "60000")))
    for index, question in enumerate(questions, 1):
        qid = question["question_id"]
        if qid in records:
            continue
        result = evaluate_one(question, runtime)
        route_errors = model_call_errors(manifest["deployed_model"], result["llm_calls"])
        if route_errors:
            raise RuntimeError("; ".join(route_errors))
        with record_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
        records[qid] = result
        selected = [records[q["question_id"]] for q in questions if q["question_id"] in records]
        report = summarize(selected)
        report.update(planned_n=len(questions), is_complete_accuracy_result=False)
        report["manifest_sha256"] = _fingerprint(manifest)
        (args.out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"[{index}/{len(questions)}] {qid} {result['db_id']} "
              f"{result['failure_category']} {result['latency_ms']}ms", flush=True)
        fault = integration_fault(result, manifest)
        if fault:
            raise ProductIntegrationFault(fault, qid)
    selected = [records[q["question_id"]] for q in questions if q["question_id"] in records]
    if run_manifest(args.benchmark, questions) != manifest:
        raise RuntimeError("Runtime, model artifact, semantics or source data changed during evaluation; results are not a frozen acceptance run")
    report = summarize(selected)
    report.update(planned_n=len(questions), is_complete_accuracy_result=True)
    report["manifest_sha256"] = _fingerprint(manifest)
    (args.out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # A partial report can already contain every question before final runtime
    # validation succeeds. Publish this marker only after the freeze check,
    # binding the complete records and their manifest for the acceptance gate.
    completion = {"status": "complete", "runtime_freeze_verified": True,
                  "source_data_freeze_verified": True,
                  "source_data_sha256": manifest["source_data"]["fingerprint_sha256"],
                  "n": len(selected), "question_ids": [q["question_id"] for q in questions],
                  "manifest_sha256": _fingerprint(manifest),
                  "records_sha256": hashlib.sha256(record_path.read_bytes()).hexdigest(),
                  "completed_at": datetime.now(timezone.utc).isoformat()}
    (args.out_dir / "completion.json").write_text(json.dumps(completion, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("n", "correct", "execution_accuracy", "valid_sql", "gold_executable")}), flush=True)


if __name__ == "__main__":
    main()

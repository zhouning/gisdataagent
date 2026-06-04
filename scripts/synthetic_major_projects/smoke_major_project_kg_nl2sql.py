"""End-to-end smoke runner for synthetic major-project KG NL2SQL.

The runner reads synthetic benchmark questions, calls the production
run_nl2semantic2sql() path, and checks key SQL fragments for KG-backed cases.
It expects database, Neo4j, and LLM settings to come from environment variables
or data_agent/.env. No credentials are embedded here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

DEFAULT_BENCHMARK = (
    ROOT / "data_agent" / "synthetic" / "major_projects" / "nl2sql_benchmark_questions.jsonl"
)
OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"

DEFAULT_SMOKE_IDS = [
    "mp_bench_sql_type_001",
    "mp_bench_graph_missing_001",
    "mp_bench_hybrid_pre_no_conv_001",
    "mp_bench_hybrid_spatial_002",
    "mp_bench_farmland_001",
]

EXPECTED_SQL_FRAGMENTS = {
    "mp_bench_graph_missing_001": ("kg_edges", "kg_nodes", "MISSING_STAGE"),
    "mp_bench_hybrid_spatial_002": ("mp_spatial_overlap",),
    "mp_bench_farmland_001": ("mp_relation_confidence", "mp_parcel"),
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test synthetic major-project KG NL2Semantic2SQL."
    )
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=DEFAULT_BENCHMARK,
        help="Path to nl2sql_benchmark_questions.jsonl.",
    )
    parser.add_argument(
        "--ids",
        default=",".join(DEFAULT_SMOKE_IDS),
        help="Comma-separated benchmark ids to run.",
    )
    parser.add_argument(
        "--backend",
        choices=("neo4j", "postgres_projection"),
        default="neo4j",
        help="Major-project KG backend to use.",
    )
    parser.add_argument(
        "--model",
        default="gemma4-26b-host9",
        help="NL2SQL_AGENT_MODEL value.",
    )
    parser.add_argument(
        "--ollama-base",
        default="http://192.168.43.9:11434",
        help="OLLAMA_API_BASE value for unpinned local models.",
    )
    parser.add_argument(
        "--neo4j-uri",
        default="neo4j://127.0.0.1:7687",
        help="NEO4J_URI value.",
    )
    parser.add_argument(
        "--neo4j-database",
        default="zdxmdb",
        help="NEO4J_DATABASE value.",
    )
    parser.add_argument(
        "--neo4j-user",
        default="neo4j",
        help="NEO4J_USER value.",
    )
    parser.add_argument(
        "--enable-fewshot",
        action="store_true",
        help="Enable few-shot retrieval/auto-curation. Disabled by default.",
    )
    parser.add_argument(
        "--enable-auto-curate",
        action="store_true",
        help="Allow successful SQL to be auto-curated. Disabled by default.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to data_agent/nl2sql_eval_results/major_project_kg_smoke_<timestamp>.",
    )
    parser.add_argument(
        "--no-strict-fragments",
        action="store_true",
        help="Do not fail when expected SQL fragments are missing.",
    )
    return parser.parse_args(argv)


def _load_questions(path: Path, ids: list[str]) -> list[dict[str, str]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        qid = row.get("id")
        if qid:
            rows[str(qid)] = row

    missing = [qid for qid in ids if qid not in rows]
    if missing:
        raise SystemExit(f"benchmark ids not found: {missing}")

    return [
        {"id": qid, "question": str(rows[qid].get("question") or "")}
        for qid in ids
    ]


def _row_count(payload: dict[str, Any]) -> int | None:
    execution = payload.get("execution")
    if isinstance(execution, dict):
        rows_value = execution.get("rows")
        if isinstance(rows_value, int):
            return rows_value
        for key in ("data", "result", "results"):
            value = execution.get(key)
            if isinstance(value, list):
                return len(value)

    rows_value = payload.get("rows")
    if isinstance(rows_value, int):
        return rows_value

    for key in ("data", "result", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def _missing_expected_fragments(qid: str, sql: str) -> list[str]:
    fragments = EXPECTED_SQL_FRAGMENTS.get(qid, ())
    return [fragment for fragment in fragments if fragment not in sql]


def _summarize_result(qid: str, question: str, payload: dict[str, Any]) -> dict[str, Any]:
    sql = str(payload.get("sql") or "")
    semantic = payload.get("semantic") if isinstance(payload.get("semantic"), dict) else {}
    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    error = payload.get("error") or execution.get("error")

    return {
        "id": qid,
        "question": question,
        "status": payload.get("status"),
        "row_count": _row_count(payload),
        "sql": sql,
        "raw_sql": str(payload.get("raw_sql") or "")[:1200],
        "error": error,
        "candidate_tables": semantic.get("candidate_tables"),
        "missing_expected_fragments": _missing_expected_fragments(qid, sql),
    }


def _configure_environment(args: argparse.Namespace) -> None:
    load_dotenv(str(ROOT / "data_agent" / ".env"), override=False)

    os.environ["NL2SQL_AGENT_MODEL"] = args.model
    os.environ["NL2SQL_GEMMA_SQL_RETRIES"] = os.environ.get(
        "NL2SQL_GEMMA_SQL_RETRIES", "1"
    )
    os.environ["OLLAMA_API_BASE"] = args.ollama_base
    os.environ["MAJOR_PROJECT_KG_BACKEND"] = args.backend

    if not args.enable_fewshot:
        os.environ["NL2SQL_DISABLE_FEWSHOT"] = "1"

    if args.backend == "neo4j":
        os.environ["NEO4J_URI"] = args.neo4j_uri
        os.environ["NEO4J_USER"] = args.neo4j_user
        os.environ["NEO4J_DATABASE"] = args.neo4j_database
        if not os.environ.get("NEO4J_PASSWORD"):
            raise SystemExit(
                "NEO4J_PASSWORD is required when --backend neo4j. "
                "Set it in the environment or data_agent/.env."
            )

    no_proxy_parts = [
        "127.0.0.1",
        "localhost",
        "192.168.43.9",
        "119.3.175.198",
    ]
    current_no_proxy = os.environ.get("NO_PROXY", "")
    os.environ["NO_PROXY"] = ",".join(
        part for part in [current_no_proxy, *no_proxy_parts] if part
    )
    os.environ["no_proxy"] = os.environ["NO_PROXY"]


def _run_cases(cases: list[dict[str, str]], enable_auto_curate: bool) -> list[dict[str, Any]]:
    import data_agent.nl2sql_executor as executor
    from data_agent.nl2sql_executor import run_nl2semantic2sql

    if not enable_auto_curate:
        executor._auto_curate = lambda question, sql: None

    records: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        qid = case["id"]
        question = case["question"]
        print(f"[major-project-smoke {index}/{len(cases)}] {qid}", flush=True)
        raw = run_nl2semantic2sql(question)
        try:
            payload = json.loads(raw)
        except Exception as exc:
            payload = {
                "status": "json_error",
                "error": str(exc),
                "sql": "",
                "raw_sql": raw[:1200],
            }
        record = _summarize_result(qid, question, payload)
        records.append(record)
        print(
            f"  status={record['status']} rows={record['row_count']} "
            f"missing_fragments={record['missing_expected_fragments']}",
            flush=True,
        )
    return records


def _write_summary(out_dir: Path, args: argparse.Namespace, records: list[dict[str, Any]]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now().isoformat(),
        "benchmark": str(args.benchmark),
        "backend": args.backend,
        "model": args.model,
        "ollama_base": args.ollama_base,
        "neo4j_uri": args.neo4j_uri if args.backend == "neo4j" else None,
        "neo4j_database": args.neo4j_database if args.backend == "neo4j" else None,
        "n_cases": len(records),
        "n_ok": sum(1 for record in records if record.get("status") == "ok"),
        "n_missing_expected_fragments": sum(
            1 for record in records if record.get("missing_expected_fragments")
        ),
        "records": records,
    }
    path = out_dir / "summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    ids = [item.strip() for item in str(args.ids).split(",") if item.strip()]
    if not ids:
        raise SystemExit("at least one benchmark id is required")

    _configure_environment(args)
    cases = _load_questions(args.benchmark, ids)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = args.out_dir or OUT_ROOT / f"major_project_kg_smoke_{timestamp}"
    records = _run_cases(cases, enable_auto_curate=args.enable_auto_curate)
    summary_path = _write_summary(out_dir, args, records)

    failed = [record for record in records if record.get("status") != "ok"]
    missing_fragments = [
        record for record in records if record.get("missing_expected_fragments")
    ]

    print(f"[major-project-smoke] summary: {summary_path}", flush=True)
    print(
        f"[major-project-smoke] ok={len(records) - len(failed)}/{len(records)} "
        f"missing_fragments={len(missing_fragments)}",
        flush=True,
    )

    if failed:
        return 1
    if missing_fragments and not args.no_strict_fragments:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

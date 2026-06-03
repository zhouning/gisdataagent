from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(r"D:\adk")
OLLAMA_API_BASE = "http://192.168.1.164:11434"
MODEL_NAME = "gemma4-26b-host164"
EMBEDDING_NAME = "nomic-embed-text-v2-moe-host164"
BENCHMARK = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"
OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"
FAMILY = "family12_gemma4_26b_host164_productized_full"


def configure_environment() -> None:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))
    os.environ["PYTHONPATH"] = str(ROOT)
    os.environ["OLLAMA_API_BASE"] = OLLAMA_API_BASE
    os.environ["NL2SQL_AGENT_MODEL"] = MODEL_NAME
    os.environ["NL2SQL_BASELINE_MODEL"] = MODEL_NAME
    os.environ["EMBEDDING_MODEL"] = EMBEDDING_NAME
    os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "720"
    os.environ["NL2SQL_GEMMA_SQL_RETRIES"] = "3"
    os.environ.pop("NL2SQL_PROMPT_FAMILY_OVERRIDE", None)

    no_proxy_hosts = ["192.168.1.164", "119.3.175.198", "localhost", "127.0.0.1"]
    existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    merged = []
    for item in existing.split(",") + no_proxy_hosts:
        item = item.strip()
        if item and item not in merged:
            merged.append(item)
    os.environ["NO_PROXY"] = ",".join(merged)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]


def register_runtime_models() -> None:
    from data_agent.model_gateway import ModelRegistry
    from data_agent.embedding_gateway import EmbeddingRegistry

    ModelRegistry._ensure_initialized()
    base = dict(ModelRegistry.models.get("gemma4-26b-host9", {}))
    base.update({
        "backend": "litellm",
        "tier": "standard",
        "online": False,
        "api_base": OLLAMA_API_BASE,
        "api_base_pinned": True,
        "model_id": "ollama_chat/Gemma4:26b",
        "extra_body": {"think": False},
        "request_timeout": 600,
        "max_context_tokens": 128_000,
    })
    ModelRegistry.models[MODEL_NAME] = base

    EmbeddingRegistry.register_model(
        EMBEDDING_NAME,
        backend="ollama",
        dimension=768,
        online=False,
        ollama_model_id="nomic-embed-text-v2-moe:latest",
        api_base=OLLAMA_API_BASE,
        api_base_pinned=True,
        description="Nomic Embed Text v2 MoE via Ollama @ 192.168.1.164",
    )


def load_questions() -> list[dict]:
    with BENCHMARK.open(encoding="utf-8") as f:
        return json.load(f)


def summarize(records: list[dict], n_total: int, started_at: str, wall_minutes: float) -> dict:
    by_difficulty: dict[str, dict] = defaultdict(lambda: {"n": 0, "ex": 0, "valid": 0})
    by_category: dict[str, dict] = defaultdict(lambda: {"n": 0, "ex": 0, "valid": 0})
    for rec in records:
        for bucket, key in ((by_difficulty, rec.get("difficulty", "")),
                            (by_category, rec.get("category", ""))):
            bucket[key]["n"] += 1
            bucket[key]["ex"] += int(bool(rec.get("ex")))
            bucket[key]["valid"] += int(bool(rec.get("valid")))

    def rates(bucket: dict[str, dict]) -> dict[str, dict]:
        out = {}
        for key in sorted(bucket):
            item = dict(bucket[key])
            n = item["n"] or 1
            item["ex_rate"] = round(item["ex"] / n, 4)
            item["valid_rate"] = round(item["valid"] / n, 4)
            out[key] = item
        return out

    n_done = len(records)
    ex = sum(int(bool(r.get("ex"))) for r in records)
    valid = sum(int(bool(r.get("valid"))) for r in records)
    return {
        "family": FAMILY,
        "mode": "full",
        "model_registry_name": MODEL_NAME,
        "llm_model": "Gemma4:26b",
        "embedding_model": EMBEDDING_NAME,
        "ollama_api_base": OLLAMA_API_BASE,
        "benchmark": str(BENCHMARK.relative_to(ROOT)),
        "n_questions": n_total,
        "n_completed": n_done,
        "ex": ex,
        "valid": valid,
        "execution_accuracy": round(ex / n_done, 4) if n_done else 0.0,
        "valid_rate": round(valid / n_done, 4) if n_done else 0.0,
        "by_difficulty": rates(by_difficulty),
        "by_category": rates(by_category),
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(),
        "wall_minutes": round(wall_minutes, 2),
    }


def persist(out_dir: Path, records: list[dict], n_total: int,
            started_at: str, wall_minutes: float, final: bool = False) -> None:
    summary = summarize(records, n_total, started_at, wall_minutes)
    name = "full_results.json" if final else "full_results_partial.json"
    (out_dir / name).write_text(
        json.dumps({"summary": summary, "records": records},
                   indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    if final:
        (out_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )


async def main() -> int:
    configure_environment()
    register_runtime_models()

    import run_cq_eval

    run_cq_eval._init_runtime()
    questions = load_questions()
    resume_dir_env = os.environ.get("RESUME_DIR")
    if resume_dir_env:
        out_dir = Path(resume_dir_env)
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        out_dir = OUT_ROOT / f"{FAMILY}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    partial_path = out_dir / "full_results_partial.json"
    records: list[dict] = []
    started_at = datetime.now().isoformat()
    previous_wall = 0.0
    if resume_dir_env and partial_path.exists():
        partial = json.loads(partial_path.read_text(encoding="utf-8"))
        records = list(partial.get("records") or [])
        summary = partial.get("summary") or {}
        started_at = summary.get("started_at") or started_at
        previous_wall = float(summary.get("wall_minutes") or 0.0)
    t_start = time.time() - previous_wall * 60

    print(f"[runner] family={FAMILY}", flush=True)
    print(f"[runner] model={MODEL_NAME} base={OLLAMA_API_BASE}", flush=True)
    print(f"[runner] embedding={EMBEDDING_NAME}", flush=True)
    print(f"[runner] benchmark={BENCHMARK} n={len(questions)}", flush=True)
    print(f"[runner] out_dir={out_dir}", flush=True)
    if records:
        print(f"[runner] resume_records={len(records)}", flush=True)

    for i, q in enumerate(questions[len(records):], len(records) + 1):
        t0 = time.time()
        try:
            rec = await asyncio.wait_for(run_cq_eval.run_one(q, "full"), timeout=780)
        except asyncio.TimeoutError:
            rec = {
                "qid": q.get("id", "?"),
                "category": q.get("category", ""),
                "difficulty": q.get("difficulty", ""),
                "question": q.get("question", ""),
                "gold_sql": q.get("golden_sql", ""),
                "pred_sql": "",
                "ex": 0,
                "valid": 0,
                "reason": "outer timeout",
                "tokens": 0,
                "pred_error": "outer timeout",
                "gen_status": "timeout",
                "gen_error": "outer timeout",
            }
        except Exception as exc:
            rec = {
                "qid": q.get("id", "?"),
                "category": q.get("category", ""),
                "difficulty": q.get("difficulty", ""),
                "question": q.get("question", ""),
                "gold_sql": q.get("golden_sql", ""),
                "pred_sql": "",
                "ex": 0,
                "valid": 0,
                "reason": str(exc)[:500],
                "tokens": 0,
                "pred_error": str(exc)[:500],
                "gen_status": "exception",
                "gen_error": str(exc)[:500],
            }

        rec["family"] = FAMILY
        rec["mode"] = "full"
        rec["model_registry_name"] = MODEL_NAME
        rec["embedding_model"] = EMBEDDING_NAME
        rec["duration_seconds"] = round(time.time() - t0, 2)
        records.append(rec)

        status = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
        print(
            f"[productized-full {i:03d}/{len(questions)}] {status} {rec.get('qid')} "
            f"ex={rec.get('ex')} valid={rec.get('valid')} "
            f"dur={rec['duration_seconds']:.1f}s reason={str(rec.get('reason', ''))[:130]}",
            flush=True,
        )
        persist(out_dir, records, len(questions), started_at,
                (time.time() - t_start) / 60, final=False)

    wall = (time.time() - t_start) / 60
    persist(out_dir, records, len(questions), started_at, wall, final=True)
    summary = summarize(records, len(questions), started_at, wall)
    print(
        f"[done/productized-full] EX={summary['ex']}/{summary['n_completed']} "
        f"acc={summary['execution_accuracy']:.4f} "
        f"valid={summary['valid_rate']:.4f} wall={summary['wall_minutes']:.2f}min",
        flush=True,
    )
    print(f"[final] summary={out_dir / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BIRD_ROOT = PROJECT_ROOT / "data" / "bird_mini_dev"
RESULTS_ROOT = PROJECT_ROOT / "data_agent" / "nl2sql_eval_results"

SQLITE_QUESTIONS_CANDIDATES: tuple[Path, ...] = (
    Path("finetuning/inference/mini_dev_prompt.jsonl"),
)
PG_QUESTIONS_CANDIDATES: tuple[Path, ...] = (
    Path("llm/mini_dev_data/minidev/MINIDEV/mini_dev_postgresql.json"),
    Path("finetuning/inference/mini_dev_prompt_with_gold_for_pg.jsonl"),
    Path("finetuning/inference/mini_dev_prompt.jsonl"),
)
DEV_DATABASES_CANDIDATES: tuple[Path, ...] = (
    Path("llm/mini_dev_data/minidev/MINIDEV/dev_databases"),
    Path("dev_databases"),
)


def _resolve_candidate(root: Path, candidates: tuple[Path, ...], label: str) -> Path:
    for rel in candidates:
        candidate = root / rel
        if candidate.exists():
            return candidate
    attempted = ", ".join(str(root / rel) for rel in candidates)
    raise FileNotFoundError(f"BIRD layout incomplete: missing {label}. Tried: {attempted}")


def resolve_bird_layout(bird_root: str | Path | None = None) -> dict[str, Path]:
    root = Path(bird_root) if bird_root is not None else DEFAULT_BIRD_ROOT
    root = root.resolve()

    sqlite_questions = _resolve_candidate(root, SQLITE_QUESTIONS_CANDIDATES, "sqlite_questions")
    pg_questions = _resolve_candidate(root, PG_QUESTIONS_CANDIDATES, "pg_questions")
    dev_databases = _resolve_candidate(root, DEV_DATABASES_CANDIDATES, "dev_databases")

    return {
        "project_root": PROJECT_ROOT,
        "bird_root": root,
        "sqlite_questions": sqlite_questions,
        "pg_questions": pg_questions,
        "dev_databases": dev_databases,
        "results_root": RESULTS_ROOT,
    }

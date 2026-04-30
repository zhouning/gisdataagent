# BIRD NL2SQL Evaluation Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将仓库中已有的 BIRD mini_dev 原型脚本整理为一套可重复执行、可报告、可回归测试的 PostgreSQL Benchmark Track，用于评估 GIS Data Agent 的通用数据仓库 NL2SQL 能力。

**Architecture:** 复用现有 `scripts/nl2sql_bench_bird/` 原型，而不是重写评估链路。先抽取共享的数据集定位与预检逻辑，再让导入、语义注册、SQLite baseline、PostgreSQL A/B 评估都通过同一套 helper 访问数据，最后补上 PostgreSQL 报告生成器和双轨评估文档，使 BIRD Track 与现有 FloodSQL Track 并存。

**Tech Stack:** Python 3.13, PostgreSQL, SQLite, SQLAlchemy, Google GenAI SDK, Google ADK pipeline runner, pytest.

---

## File Structure

### Create
- `scripts/nl2sql_bench_bird/bird_paths.py` — BIRD 数据集路径解析与预检 helper，统一管理 repo 根路径、questions 文件、数据库目录、结果目录。
- `scripts/nl2sql_bench_bird/report_pg_eval.py` — PostgreSQL A/B 评估结果汇总器，生成 Markdown 报告和简要 JSON 摘要。
- `data_agent/test_bird_benchmark_scripts.py` — 针对 BIRD helper、CLI 参数、报告生成逻辑的单元测试。

### Modify
- `scripts/nl2sql_bench_bird/import_to_pg.py` — 改为使用共享 helper，并支持 `--bird-root` 覆盖数据目录。
- `scripts/nl2sql_bench_bird/register_semantic.py` — 保持现有语义注册逻辑，但增加对空 schema / 缺失 schema 的更明确输出。
- `scripts/nl2sql_bench_bird/run_bird_eval.py` — 改为使用共享 helper，并支持 `--bird-root`。
- `scripts/nl2sql_bench_bird/run_pg_eval.py` — 改为使用共享 helper，并支持 `--bird-root`。
- `scripts/nl2sql_bench_bird/README.md` — 改写为完整 BIRD Track 操作文档，区分 SQLite baseline 与 PostgreSQL A/B。
- `docs/nl2semantic2sql_architecture.md` — 增补“双轨评估”章节，明确 BIRD 对通用仓库 NL2SQL、FloodSQL 对空间 NL2SQL 的职责分工。

---

### Task 1: 抽取共享的 BIRD 路径与数据集预检模块

**Files:**
- Create: `scripts/nl2sql_bench_bird/bird_paths.py`
- Test: `data_agent/test_bird_benchmark_scripts.py`

- [ ] **Step 1: 先写失败测试，锁定数据集路径解析行为**

在 `data_agent/test_bird_benchmark_scripts.py` 中新增这组测试，要求 helper 能同时解析 SQLite questions、PostgreSQL questions、dev_databases 路径。

```python
import importlib.util
from pathlib import Path


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bird_paths_resolve_dataset_layout(tmp_path):
    root = tmp_path / "bird_mini_dev"
    (root / "finetuning" / "inference").mkdir(parents=True)
    (root / "llm" / "mini_dev_data" / "minidev" / "MINIDEV" / "dev_databases").mkdir(parents=True)
    (root / "llm" / "mini_dev_data" / "minidev" / "MINIDEV").mkdir(parents=True, exist_ok=True)

    sqlite_questions = root / "finetuning" / "inference" / "mini_dev_prompt.jsonl"
    sqlite_questions.write_text("{}\n", encoding="utf-8")

    pg_questions = root / "llm" / "mini_dev_data" / "minidev" / "MINIDEV" / "mini_dev_postgresql.json"
    pg_questions.write_text("[]", encoding="utf-8")

    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "bird_paths.py"),
        "bird_paths_mod",
    )

    layout = mod.resolve_bird_layout(root)
    assert layout["bird_root"] == root
    assert layout["sqlite_questions"] == sqlite_questions
    assert layout["pg_questions"] == pg_questions
    assert layout["dev_databases"].name == "dev_databases"


def test_bird_paths_raise_clear_error_when_layout_incomplete(tmp_path):
    root = tmp_path / "bird_mini_dev"
    root.mkdir()

    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "bird_paths.py"),
        "bird_paths_mod_missing",
    )

    try:
        mod.resolve_bird_layout(root)
    except FileNotFoundError as e:
        assert "mini_dev_prompt.jsonl" in str(e) or "mini_dev_postgresql.json" in str(e)
    else:
        raise AssertionError("Expected FileNotFoundError for incomplete BIRD layout")
```

- [ ] **Step 2: 运行测试，确认当前仓库缺少该模块**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_bird_benchmark_scripts.py -k bird_paths -v`

Expected: FAIL with `FileNotFoundError` or module import failure for `bird_paths.py`.

- [ ] **Step 3: 写最小实现，集中管理 BIRD 路径**

创建 `scripts/nl2sql_bench_bird/bird_paths.py`，内容按下面结构实现：

```python
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BIRD_ROOT = PROJECT_ROOT / "data" / "bird_mini_dev"
RESULTS_ROOT = PROJECT_ROOT / "data_agent" / "nl2sql_eval_results"


SQLITE_QUESTIONS_CANDIDATES = [
    ("finetuning", "inference", "mini_dev_prompt.jsonl"),
]

PG_QUESTIONS_CANDIDATES = [
    ("llm", "mini_dev_data", "minidev", "MINIDEV", "mini_dev_postgresql.json"),
]

DEV_DATABASES_CANDIDATES = [
    ("llm", "mini_dev_data", "minidev", "MINIDEV", "dev_databases"),
]


def _resolve_candidate(root: Path, candidates: list[tuple[str, ...]], label: str) -> Path:
    for parts in candidates:
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    tried = [str(root.joinpath(*parts)) for parts in candidates]
    raise FileNotFoundError(f"BIRD {label} not found. Tried: {tried}")


def resolve_bird_layout(bird_root: str | Path | None = None) -> dict[str, Path]:
    root = Path(bird_root) if bird_root else DEFAULT_BIRD_ROOT
    root = root.resolve()
    return {
        "project_root": PROJECT_ROOT,
        "bird_root": root,
        "sqlite_questions": _resolve_candidate(root, SQLITE_QUESTIONS_CANDIDATES, "SQLite questions"),
        "pg_questions": _resolve_candidate(root, PG_QUESTIONS_CANDIDATES, "PostgreSQL questions"),
        "dev_databases": _resolve_candidate(root, DEV_DATABASES_CANDIDATES, "dev_databases"),
        "results_root": RESULTS_ROOT,
    }
```

- [ ] **Step 4: 再跑测试，确认 helper 行为稳定**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_bird_benchmark_scripts.py -k bird_paths -v`

Expected: PASS with 2 passed.

- [ ] **Step 5: 提交这一小步**

```bash
git add scripts/nl2sql_bench_bird/bird_paths.py data_agent/test_bird_benchmark_scripts.py
git commit -m "refactor: centralize bird benchmark path resolution"
```

---

### Task 2: 让四个 BIRD CLI 共享同一套数据定位与预检

**Files:**
- Modify: `scripts/nl2sql_bench_bird/import_to_pg.py`
- Modify: `scripts/nl2sql_bench_bird/run_bird_eval.py`
- Modify: `scripts/nl2sql_bench_bird/run_pg_eval.py`
- Modify: `scripts/nl2sql_bench_bird/register_semantic.py`
- Test: `data_agent/test_bird_benchmark_scripts.py`

- [ ] **Step 1: 先写失败测试，锁定 CLI 新参数与 helper 接线**

在 `data_agent/test_bird_benchmark_scripts.py` 追加测试，要求 baseline evaluator 与 PG evaluator 都暴露 `--bird-root` 参数，并且在 questions 路径缺失时抛出明确异常。

```python
def test_run_bird_eval_parser_accepts_bird_root():
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "run_bird_eval.py"),
        "run_bird_eval_mod",
    )
    parser = mod.build_arg_parser()
    args = parser.parse_args(["--bird-root", "D:/tmp/bird", "--limit", "3"])
    assert args.bird_root == "D:/tmp/bird"
    assert args.limit == 3


def test_run_pg_eval_parser_accepts_bird_root():
    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "run_pg_eval.py"),
        "run_pg_eval_mod",
    )
    parser = mod.build_arg_parser()
    args = parser.parse_args(["--bird-root", "D:/tmp/bird", "--mode", "both"])
    assert args.bird_root == "D:/tmp/bird"
    assert args.mode == "both"
```

- [ ] **Step 2: 运行测试，确认当前脚本还不支持该参数**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_bird_benchmark_scripts.py -k "accepts_bird_root" -v`

Expected: FAIL because `build_arg_parser()` does not exist and `--bird-root` is not accepted.

- [ ] **Step 3: 在 `run_bird_eval.py` 中抽出 parser 并接入共享 layout**

将 `run_bird_eval.py` 的参数解析重构为单独函数，并用 `resolve_bird_layout()` 取代硬编码路径：

```python
from scripts.nl2sql_bench_bird.bird_paths import resolve_bird_layout


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--bird-root", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--difficulty", default=None, help="simple,moderate,challenging")
    p.add_argument("--out-dir", default=None)
    return p


def load_questions(questions_path: Path, limit: int | None = None, difficulties: set[str] | None = None) -> list[dict]:
    out: list[dict] = []
    with questions_path.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line.strip())
            if difficulties and rec.get("difficulty") not in difficulties:
                continue
            out.append(rec)
            if limit and len(out) >= limit:
                break
    return out


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    layout = resolve_bird_layout(args.bird_root)
    questions = load_questions(layout["sqlite_questions"], limit=args.limit, difficulties=diffs)
```

- [ ] **Step 4: 在 `run_pg_eval.py` 中做同样改造**

把 PG evaluator 也重构为 `build_arg_parser()`，并让 `load_questions()` 改为显式接收 questions path：

```python
from scripts.nl2sql_bench_bird.bird_paths import resolve_bird_layout


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--bird-root", default=None)
    p.add_argument("--mode", choices=["baseline", "full", "both"], default="both")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--difficulty", default=None)
    p.add_argument("--db-id", default=None, help="filter by single db_id")
    p.add_argument("--out-dir", default=None)
    return p


def load_questions(questions_path: Path, limit: int | None = None,
                   difficulties: set[str] | None = None,
                   db_ids: set[str] | None = None) -> list[dict]:
    with questions_path.open(encoding="utf-8") as f:
        data = json.load(f)
    ...


async def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    layout = resolve_bird_layout(args.bird_root)
    questions = load_questions(layout["pg_questions"], limit=args.limit, difficulties=diffs, db_ids=dbs)
    out_dir = Path(args.out_dir) if args.out_dir else (
        layout["results_root"] / f"bird_pg_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    )
```

- [ ] **Step 5: 在 `import_to_pg.py` 中接入共享 layout 与 CLI**

让导入脚本也支持 `--bird-root`，并从 helper 提供的 `dev_databases` 读取路径：

```python
import argparse
from scripts.nl2sql_bench_bird.bird_paths import resolve_bird_layout


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--bird-root", default=None)
    return p


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    layout = resolve_bird_layout(args.bird_root)
    db_root = layout["dev_databases"]
    sqlite_dirs = [p for p in db_root.iterdir() if p.is_dir()]
    ...
```

- [ ] **Step 6: 在 `register_semantic.py` 中补明确输出，避免空注册静默通过**

保持现有 SQL 注册逻辑，但在未发现任何 `bird_` schema 时直接失败：

```python
schemas = [r[0] for r in conn.execute(text(
    "SELECT schema_name FROM information_schema.schemata "
    "WHERE schema_name LIKE 'bird_%' ORDER BY schema_name"
)).fetchall()]
if not schemas:
    raise RuntimeError("No bird_* schemas found. Run import_to_pg.py first.")
```

- [ ] **Step 7: 运行单元测试，确认 CLI 接线完成**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_bird_benchmark_scripts.py -k "bird_root or parser" -v`

Expected: PASS.

- [ ] **Step 8: 提交这一小步**

```bash
git add scripts/nl2sql_bench_bird/import_to_pg.py scripts/nl2sql_bench_bird/run_bird_eval.py scripts/nl2sql_bench_bird/run_pg_eval.py scripts/nl2sql_bench_bird/register_semantic.py data_agent/test_bird_benchmark_scripts.py
git commit -m "refactor: harden bird benchmark cli entrypoints"
```

---

### Task 3: 为 PostgreSQL A/B 评估补上正式报告生成器

**Files:**
- Create: `scripts/nl2sql_bench_bird/report_pg_eval.py`
- Test: `data_agent/test_bird_benchmark_scripts.py`

- [ ] **Step 1: 先写失败测试，锁定报告摘要输出格式**

在 `data_agent/test_bird_benchmark_scripts.py` 中新增测试，要求报告脚本能读取 `baseline_results.json` 和 `full_results.json`，输出 `comparison_report.md`。

```python
def test_report_pg_eval_writes_comparison_report(tmp_path):
    run_dir = tmp_path / "bird_pg_2026-04-30_120000"
    run_dir.mkdir()

    baseline = {
        "summary": {"mode": "baseline", "execution_accuracy": 0.25, "execution_valid_rate": 0.5, "by_difficulty": {"simple": 0.5}},
        "records": [{"qid": 1, "difficulty": "simple", "db_id": "db1", "ex": 0, "valid": 1, "gen_status": "ok"}],
    }
    full = {
        "summary": {"mode": "full", "execution_accuracy": 0.5, "execution_valid_rate": 0.75, "by_difficulty": {"simple": 1.0}},
        "records": [{"qid": 1, "difficulty": "simple", "db_id": "db1", "ex": 1, "valid": 1, "gen_status": "ok"}],
    }

    (run_dir / "baseline_results.json").write_text(json.dumps(baseline), encoding="utf-8")
    (run_dir / "full_results.json").write_text(json.dumps(full), encoding="utf-8")

    mod = _load_module(
        str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_bird" / "report_pg_eval.py"),
        "bird_report_mod",
    )

    mod.write_report(run_dir, baseline, full)
    report = (run_dir / "comparison_report.md").read_text(encoding="utf-8")
    assert "# BIRD PostgreSQL Evaluation Report" in report
    assert "delta=+0.2500" in report
    assert "| simple | 0.5000 | 1.0000 | +0.5000 |" in report
```

- [ ] **Step 2: 运行测试，确认报告脚本还不存在**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_bird_benchmark_scripts.py -k report_pg_eval -v`

Expected: FAIL because `report_pg_eval.py` does not exist.

- [ ] **Step 3: 写最小实现，生成 Markdown 报告**

创建 `scripts/nl2sql_bench_bird/report_pg_eval.py`，至少包含下面结构：

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.nl2sql_bench_bird.bird_paths import RESULTS_ROOT


def load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _format_diff_table(baseline: dict, full: dict) -> str:
    diffs = sorted(set(baseline["summary"]["by_difficulty"]) | set(full["summary"]["by_difficulty"]))
    lines = ["| Difficulty | Baseline EX | Full EX | Delta |", "|---|---:|---:|---:|"]
    for diff in diffs:
        b = baseline["summary"]["by_difficulty"].get(diff, 0.0)
        f = full["summary"]["by_difficulty"].get(diff, 0.0)
        lines.append(f"| {diff} | {b:.4f} | {f:.4f} | {f - b:+.4f} |")
    return "\n".join(lines)


def write_report(run_dir: Path, baseline: dict, full: dict) -> Path:
    b = baseline["summary"]["execution_accuracy"]
    f = full["summary"]["execution_accuracy"]
    markdown = f"""# BIRD PostgreSQL Evaluation Report

## Summary

- baseline EX={b:.4f}
- full EX={f:.4f}
- delta={f - b:+.4f}
- baseline valid={baseline['summary']['execution_valid_rate']:.4f}
- full valid={full['summary']['execution_valid_rate']:.4f}

## By Difficulty

{_format_diff_table(baseline, full)}
"""
    out = run_dir / "comparison_report.md"
    out.write_text(markdown, encoding="utf-8")
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", required=True)
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    run_dir = Path(args.run_dir)
    baseline = load_payload(run_dir / "baseline_results.json")
    full = load_payload(run_dir / "full_results.json")
    out = write_report(run_dir, baseline, full)
    print(f"[bird-pg-report] Wrote {out}")
    return 0
```

- [ ] **Step 4: 再跑测试，确认报告生成正确**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_bird_benchmark_scripts.py -k report_pg_eval -v`

Expected: PASS.

- [ ] **Step 5: 用真实结果目录做一次 smoke run**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_bird/report_pg_eval.py --run-dir data_agent/nl2sql_eval_results/<existing-bird-run-dir>`

Expected:
- 输出 `[bird-pg-report] Wrote ...comparison_report.md`
- 目标目录内出现 `comparison_report.md`

- [ ] **Step 6: 提交这一小步**

```bash
git add scripts/nl2sql_bench_bird/report_pg_eval.py data_agent/test_bird_benchmark_scripts.py
git commit -m "feat: add bird postgres evaluation report generator"
```

---

### Task 4: 改写 BIRD Track 文档并补充双轨评估说明

**Files:**
- Modify: `scripts/nl2sql_bench_bird/README.md`
- Modify: `docs/nl2semantic2sql_architecture.md`

- [ ] **Step 1: 先改写 BIRD README，明确两种运行模式**

把 `scripts/nl2sql_bench_bird/README.md` 改成下面结构，不再只描述 SQLite baseline：

```markdown
# BIRD mini_dev Benchmark Track

用于评估 GIS Data Agent 的通用数据仓库 NL2SQL 能力。

## Track 目标

- `run_bird_eval.py`: SQLite baseline，测裸 LLM 的通用 SQL 能力
- `import_to_pg.py`: 将 BIRD SQLite 库导入 PostgreSQL `bird_<db_id>` schema
- `register_semantic.py`: 把导入后的 schema 注册到 semantic layer
- `run_pg_eval.py`: PostgreSQL A/B，比较 baseline vs full pipeline
- `report_pg_eval.py`: 汇总 PostgreSQL A/B 结果

## 一次完整流程

```bash
cd D:\adk
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_bird/import_to_pg.py
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_bird/register_semantic.py
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_bird/run_pg_eval.py --mode both --limit 10
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_bird/report_pg_eval.py --run-dir data_agent/nl2sql_eval_results/<run_dir>
```
```

- [ ] **Step 2: 在架构文档中增补“双轨评估”章节**

在 `docs/nl2semantic2sql_architecture.md` 末尾新增一节，写明：

```markdown
## 8. Benchmark Strategy

系统采用双轨评估：

1. **BIRD mini_dev Track**
   - 目标：验证常规企业/数据仓库 NL2SQL 能力
   - SQL 方言：SQLite baseline + PostgreSQL A/B
   - 重点：joins, aggregation, nested query, warehouse-style schema grounding
   - 脚本目录：`scripts/nl2sql_bench_bird/`

2. **FloodSQL / GIS Track**
   - 目标：验证 PostGIS 空间 NL2SQL 能力
   - SQL 方言：PostgreSQL/PostGIS
   - 重点：ST_Intersects, ST_Buffer, ST_Area, SRID, geometry reasoning
   - 脚本目录：`scripts/nl2sql_bench/`

二者共同构成 GIS Data Agent 的 NL2SQL 评估基线：
- BIRD 回答“是否具备通用仓库问答能力”
- FloodSQL 回答“是否具备空间问答差异化能力”
```

- [ ] **Step 3: 检查 README 与架构文档中的命令一致性**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "from pathlib import Path; print(Path('scripts/nl2sql_bench_bird/README.md').read_text(encoding='utf-8')[:500]); print('---'); print(Path('docs/nl2semantic2sql_architecture.md').read_text(encoding='utf-8')[-800:])"`

Expected:
- README 中包含 5 个脚本职责说明
- 架构文档末尾出现“双轨评估”章节

- [ ] **Step 4: 提交这一小步**

```bash
git add scripts/nl2sql_bench_bird/README.md docs/nl2semantic2sql_architecture.md
git commit -m "docs: document dual-track nl2sql benchmark strategy"
```

---

### Task 5: 跑一次最小端到端验证，确认 scaffold 可用

**Files:**
- Modify: none
- Verify: `scripts/nl2sql_bench_bird/*.py`
- Verify: `data_agent/test_bird_benchmark_scripts.py`

- [ ] **Step 1: 跑新增单元测试**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_bird_benchmark_scripts.py -v`

Expected: PASS.

- [ ] **Step 2: 跑 SQLite baseline smoke test**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_bird/run_bird_eval.py --limit 3`

Expected:
- 成功加载 3 条问题
- 输出 `bird_baseline_results.json`
- 无 `db_not_found`

- [ ] **Step 3: 跑 PostgreSQL A/B smoke test**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_bird/run_pg_eval.py --mode both --limit 3`

Expected:
- baseline / full 两个模式都执行
- 输出目录中出现 `baseline_results.json` 与 `full_results.json`
- 控制台输出 `A/B baseline EX=... full EX=... delta=...`

- [ ] **Step 4: 基于刚才的输出目录生成 Markdown 报告**

Run:
`PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_bird/report_pg_eval.py --run-dir data_agent/nl2sql_eval_results/<latest-bird-pg-dir>`

Expected:
- 目录内出现 `comparison_report.md`
- 报告中包含 Summary 与 By Difficulty 表格

- [ ] **Step 5: 最后提交**

```bash
git add scripts/nl2sql_bench_bird/bird_paths.py scripts/nl2sql_bench_bird/report_pg_eval.py scripts/nl2sql_bench_bird/import_to_pg.py scripts/nl2sql_bench_bird/register_semantic.py scripts/nl2sql_bench_bird/run_bird_eval.py scripts/nl2sql_bench_bird/run_pg_eval.py scripts/nl2sql_bench_bird/README.md docs/nl2semantic2sql_architecture.md data_agent/test_bird_benchmark_scripts.py
git commit -m "feat: harden bird nl2sql benchmark framework"
```

---

## Self-Review

- **Spec coverage:**
  - 通用数据仓库 NL2SQL benchmark：由 BIRD mini_dev Track 覆盖。
  - 可执行评估框架：由共享路径 helper、CLI 预检、报告脚本、测试与 README 覆盖。
  - 与现有 GIS benchmark 共存：由架构文档“双轨评估”章节覆盖。

- **Placeholder scan:**
  - 没有使用 TBD / TODO / “类似 Task N” 之类占位描述。
  - 每个代码步骤都给出了明确代码或命令。

- **Type consistency:**
  - 共享 helper 命名固定为 `resolve_bird_layout()`。
  - 新增 parser 工厂统一命名为 `build_arg_parser()`。
  - 报告脚本统一读取 `baseline_results.json` 与 `full_results.json`。

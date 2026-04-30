# BIRD mini_dev Benchmark Track

用于评估 GIS Data Agent 的**通用数据仓库 NL2SQL 能力**。

基于 [BIRD mini_dev](https://github.com/bird-bench/mini_dev) V2（780 题，11+ 数据库，3 难度级别），
对标 [BIRD 官方 leaderboard](https://bird-bench.github.io/)。

## 脚本职责

| 脚本 | 用途 |
|------|------|
| `bird_paths.py` | 共享路径解析与数据集预检 |
| `import_to_pg.py` | 将 BIRD SQLite 库导入 PostgreSQL `bird_<db_id>` schema |
| `register_semantic.py` | 把导入后的 schema 注册到 semantic layer |
| `nl2sql_agent.py` | 构建专注 NL2SQL 的评估 Agent（DatabaseToolset + SemanticLayerToolset） |
| `run_bird_eval.py` | SQLite baseline — 测裸 LLM 的通用 SQL 能力 |
| `run_pg_eval.py` | PostgreSQL A/B — 比较 baseline vs full pipeline |
| `report_pg_eval.py` | 汇总 PostgreSQL A/B 结果为 Markdown 报告 |

## 前置条件

1. 克隆 BIRD mini_dev 数据集：
   ```bash
   git clone --depth 1 https://github.com/bird-bench/mini_dev.git data/bird_mini_dev
   ```

2. 下载并解压 SQLite 数据库：
   ```bash
   # 从 https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip 下载
   # 解压到 data/bird_mini_dev/llm/mini_dev_data/minidev/MINIDEV/dev_databases/
   ```

3. `.env` 中配置 PostgreSQL 连接（用于 PG 模式）和 `GOOGLE_API_KEY`

## 一次完整流程

```bash
cd D:\adk
$env:PYTHONPATH="D:\adk"

# Step 1: 导入 SQLite → PostgreSQL
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/import_to_pg.py

# Step 2: 注册到 semantic layer
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/register_semantic.py

# Step 3: 运行 PostgreSQL A/B 评估
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/run_pg_eval.py --mode both --limit 10

# Step 4: 生成对比报告
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/report_pg_eval.py --run-dir data_agent/nl2sql_eval_results/<run_dir>
```

## 仅 SQLite Baseline（无需 PostgreSQL）

```bash
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/run_bird_eval.py --limit 10
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/run_bird_eval.py --difficulty simple
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/run_bird_eval.py  # 全量 500 题
```

## CLI 参数

所有脚本支持 `--bird-root <path>` 覆盖默认数据目录（默认 `data/bird_mini_dev`）。

| 脚本 | 额外参数 |
|------|---------|
| `run_bird_eval.py` | `--limit`, `--difficulty`, `--out-dir` |
| `run_pg_eval.py` | `--mode {baseline,full,both}`, `--limit`, `--difficulty`, `--db-id`, `--out-dir` |
| `report_pg_eval.py` | `--run-dir` (必填) |
| `import_to_pg.py` | (无额外参数) |

## 输出

结果保存在 `data_agent/nl2sql_eval_results/bird_<timestamp>/`：
- `baseline_results.json` / `full_results.json` — 逐题记录
- `comparison_report.md` — A/B 对比摘要
- `run_state.db` — SQLite 断点续跑缓存

## 参考分数（BIRD leaderboard, 2025-2026）

| 系统 | EX (mini_dev) |
|------|---:|
| Agentar-Scale-SQL (SOTA) | ~75% |
| CHESS Agent | ~73% |
| GPT-4o (zero-shot) | ~67% |
| Gemini 2.5 Flash (baseline) | 待测 |
| GIS Data Agent full pipeline | 待测 |

## 双轨评估定位

本 Track 与 `scripts/nl2sql_bench/`（FloodSQL/GIS Track）共同构成 NL2SQL 评估基线：
- **BIRD Track** → 通用仓库问答能力（joins, aggregation, nested query）
- **FloodSQL Track** → PostGIS 空间问答能力（ST_Intersects, ST_Buffer, SRID）

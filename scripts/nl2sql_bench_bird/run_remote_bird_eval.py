"""Evaluate the GIS Data Agent NL2SQL path on a remote PostgreSQL BIRD split.

The customer's BIRD deployment uses one PostgreSQL database per ``db_id``
(``bird_<db_id>``), while the historical benchmark runner expected one
database with many schemas.  This runner keeps the benchmark connection layer
separate from the application's control database and exposes the current
grounding/post-processing path through a small in-process semantic adapter.

The adapter is intentionally ephemeral: it reads table/column metadata from
the selected BIRD database and does not write semantic metadata or benchmark
records to the customer's server.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

load_dotenv(str(ROOT / "data_agent" / ".env"), override=False)

from sqlalchemy import create_engine, text  # noqa: E402

from data_agent.openai_compatible_llm import (  # noqa: E402
    OpenAICompatibleLLMConfig,
    chat_completion,
)


DEFAULT_BENCH = ROOT / "benchmarks" / "bird_pg_heldout_150.json"
DEFAULT_OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


def _strip_fences(value: str) -> str:
    value = (value or "").strip()
    match = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", value, re.I | re.S)
    if match:
        value = match.group(1).strip()
    return value.rstrip(";").strip()


def _strip_database_qualifier(sql: str, db_id: str) -> str:
    """Allow a model to echo the benchmark database name in a table ref."""
    schema = re.escape(f"bird_{db_id}")
    return re.sub(rf'(?i)(?:"{schema}"|{schema})\s*\.\s*', "", sql or "")


def _norm_value(value: Any):
    if value is None:
        return ("NULL",)
    if isinstance(value, bool):
        return ("BOOL", int(value))
    if isinstance(value, (int, float, Decimal)):
        try:
            return ("NUM", round(float(value), 5))
        except (TypeError, ValueError, OverflowError):
            return ("TEXT", str(value))
    if hasattr(value, "isoformat"):
        try:
            return ("DATE", value.isoformat())
        except Exception:
            pass
    return ("TEXT", str(value))


def compare_results(gold_rows: list[tuple] | None, pred_rows: list[tuple] | None) -> bool:
    """Compare unordered result sets with tolerant numeric/date normalisation."""
    if gold_rows is None or pred_rows is None or len(gold_rows) != len(pred_rows):
        return False
    gold = sorted(tuple(_norm_value(item) for item in row) for row in gold_rows)
    pred = sorted(tuple(_norm_value(item) for item in row) for row in pred_rows)
    return gold == pred


class RemoteBirdRuntime:
    """Read-only engines and schema metadata for the customer's BIRD server."""

    def __init__(self, host: str, port: int, user: str, password: str, timeout_ms: int):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.timeout_ms = timeout_ms
        self._engines: dict[str, Any] = {}
        self._tables: dict[str, list[str]] = {}
        self._schemas: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def engine(self, db_id: str):
        if db_id not in self._engines:
            db_name = f"bird_{db_id}"
            url = (
                f"postgresql+psycopg2://{quote_plus(self.user)}:{quote_plus(self.password)}"
                f"@{self.host}:{self.port}/{quote_plus(db_name)}"
            )
            self._engines[db_id] = create_engine(
                url,
                pool_size=1,
                max_overflow=0,
                pool_pre_ping=True,
                pool_recycle=600,
            )
        return self._engines[db_id]

    @staticmethod
    def _bare(table_name: str) -> str:
        return table_name.rsplit(".", 1)[-1].strip('"')

    def tables(self, db_id: str) -> list[str]:
        if db_id not in self._tables:
            with self.engine(db_id).connect() as conn:
                rows = conn.execute(text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_type='BASE TABLE' "
                    "ORDER BY table_name"
                )).fetchall()
            self._tables[db_id] = [str(row[0]) for row in rows]
        return self._tables[db_id]

    def schema(self, db_id: str, table_name: str) -> list[dict[str, Any]]:
        bare = self._bare(table_name)
        key = (db_id, bare)
        if key not in self._schemas:
            with self.engine(db_id).connect() as conn:
                rows = conn.execute(text(
                    "SELECT column_name, data_type, udt_name "
                    "FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=:table "
                    "ORDER BY ordinal_position"
                ), {"table": bare}).fetchall()
            self._schemas[key] = [
                {
                    "column_name": str(row[0]),
                    "data_type": str(row[1]),
                    "udt_name": str(row[2]),
                    "aliases": [],
                    "description": "",
                    "semantic_domain": None,
                    "is_geometry": False,
                }
                for row in rows
            ]
        return self._schemas[key]

    def schema_dump(self, db_id: str) -> str:
        blocks = []
        for table in self.tables(db_id):
            cols = self.schema(db_id, table)
            lines = [f'CREATE TABLE "{table}" (']
            lines.append(",\n".join(
                f'  "{col["column_name"]}" {col["data_type"]}' for col in cols
            ))
            lines.append(");")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def row_count(self, db_id: str, table_name: str) -> int:
        bare = self._bare(table_name)
        try:
            with self.engine(db_id).connect() as conn:
                value = conn.execute(text(
                    "SELECT COALESCE(reltuples::bigint, 0) FROM pg_class "
                    "WHERE relnamespace='public'::regnamespace AND relname=:table"
                ), {"table": bare}).scalar()
            return max(0, int(value or 0))
        except Exception:
            return 0

    def sample_values(self, db_id: str, table_name: str, column_name: str, limit: int = 5) -> list[str]:
        bare = self._bare(table_name)
        # Identifiers come from information_schema, never from user input.
        if bare not in self.tables(db_id):
            return []
        known = {c["column_name"] for c in self.schema(db_id, bare)}
        if column_name not in known:
            return []
        try:
            identifier = '"' + column_name.replace('"', '""') + '"'
            table_ref = '"' + bare.replace('"', '""') + '"'
            with self.engine(db_id).connect() as conn:
                rows = conn.execute(text(
                    f"SELECT DISTINCT {identifier} FROM {table_ref} "
                    f"WHERE {identifier} IS NOT NULL ORDER BY 1 LIMIT {int(limit)}"
                )).fetchall()
            return [str(row[0]) for row in rows if isinstance(row[0], str) and row[0]]
        except Exception:
            return []

    def canonicalize_identifiers(self, db_id: str, sql: str) -> str:
        """Quote BIRD's mixed-case table and column identifiers for PostgreSQL.

        The public BIRD PostgreSQL gold files use source-style identifiers such
        as ``Patient``.  The customer's import preserves those names as quoted
        identifiers, so PostgreSQL otherwise resolves ``Patient`` as lowercase
        ``patient``.  SQLGlot lets us quote only identifiers known to this
        database without changing SQL keywords, literals, or function names.
        """
        try:
            import sqlglot
            from sqlglot import exp

            tree = sqlglot.parse_one(sql, read="postgres")
            tables = {name.casefold(): name for name in self.tables(db_id)}
            columns: dict[str, str] = {}
            for table in self.tables(db_id):
                for col in self.schema(db_id, table):
                    actual = col["column_name"]
                    columns.setdefault(actual.casefold(), actual)

            def transform(node):
                if isinstance(node, exp.Table):
                    name = str(node.name or "").strip('"')
                    actual = tables.get(name.casefold())
                    if actual:
                        node.set("this", exp.Identifier(this=actual, quoted=True))
                    return node
                if isinstance(node, exp.Column):
                    name = str(node.name or "").strip('"')
                    actual = columns.get(name.casefold())
                    if actual:
                        node.set("this", exp.Identifier(this=actual, quoted=True))
                    return node
                return node

            return tree.transform(transform).sql(dialect="postgres")
        except Exception:
            # The database remains the final SQL parser. This fallback still
            # handles the common unquoted table references when SQLGlot cannot
            # parse a provider-specific expression.
            result = sql
            for actual in self.tables(db_id):
                result = re.sub(
                    rf"(?<![\w\"]){re.escape(actual)}(?![\w\"])",
                    f'"{actual}"', result,
                    flags=re.IGNORECASE,
                )
            return result

    def _column_type(self, db_id: str, table_name: str, column_name: str) -> str:
        """Return the provider type for a known column, case-insensitively."""
        wanted = column_name.strip('"').casefold()
        for column in self.schema(db_id, table_name):
            if column["column_name"].casefold() == wanted:
                return str(column.get("data_type", "")).casefold()
        return ""

    def compat_gold_sql(self, db_id: str, sql: str) -> str:
        """Adapt source BIRD Gold SQL to the PostgreSQL import's physical types.

        BIRD's public SQL is authored against source databases.  This customer's
        PostgreSQL import preserves mixed-case identifiers and stores some source
        date fields as text.  The adaptation is deliberately applied only to
        Gold SQL, never to model output, and does not change the benchmark
        question or the original SQL stored in the result record.
        """
        normalized = _strip_database_qualifier(_strip_fences(sql), db_id)
        normalized = self.canonicalize_identifiers(db_id, normalized)
        try:
            import sqlglot
            from sqlglot import exp

            tree = sqlglot.parse_one(normalized, read="postgres")
            aliases: dict[str, str] = {}
            for table in tree.find_all(exp.Table):
                table_name = str(table.name or "").strip('"')
                alias = str(table.alias or "").strip('"')
                if alias:
                    aliases[alias.casefold()] = table_name
                aliases[table_name.casefold()] = table_name

            def column_table(column: exp.Column) -> str | None:
                qualifier = str(column.table or "").strip('"')
                if qualifier:
                    return aliases.get(qualifier.casefold())
                candidates = []
                name = str(column.name or "").strip('"').casefold()
                for table_name in self.tables(db_id):
                    if any(c["column_name"].casefold() == name for c in self.schema(db_id, table_name)):
                        candidates.append(table_name)
                return candidates[0] if len(candidates) == 1 else None

            def is_text_column(node: exp.Expression) -> bool:
                if not isinstance(node, exp.Column):
                    return False
                table_name = column_table(node)
                if not table_name:
                    return False
                return self._column_type(db_id, table_name, str(node.name)) in {
                    "text", "character varying", "character", "varchar", "char"
                }

            def transform(node: exp.Expression):
                if isinstance(node, exp.Extract):
                    expression = node.args.get("expression")
                    if is_text_column(expression):
                        node.set("expression", exp.Cast(this=expression.copy(), to=exp.DataType.build("TIMESTAMP")))
                    return node
                if isinstance(node, exp.Anonymous) and str(node.name).casefold() == "strftime":
                    args = list(node.args.get("expressions") or [])
                    if len(args) == 2 and isinstance(args[0], exp.Literal) and args[0].is_string:
                        fmt = str(args[0].this)
                        if fmt in {"%Y", "%m", "%d"} and is_text_column(args[1]):
                            postgres_fmt = {"%Y": "YYYY", "%m": "MM", "%d": "DD"}[fmt]
                            return exp.ToChar(
                                this=exp.Cast(this=args[1].copy(), to=exp.DataType.build("TIMESTAMP")),
                                format=exp.Literal.string(postgres_fmt),
                            )
                return node

            return tree.transform(transform).sql(dialect="postgres")
        except Exception:
            return normalized

    def execute(self, db_id: str, sql: str, *, gold_compat: bool = False) -> dict[str, Any]:
        sql = _strip_database_qualifier(_strip_fences(sql), db_id)
        head = sql.lstrip("(").lstrip().lower()
        if not sql:
            return {"status": "error", "rows": None, "error": "empty SQL", "sql": sql}
        if not (head.startswith("select") or head.startswith("with")):
            return {"status": "error", "rows": None, "error": "non-SELECT SQL", "sql": sql}
        sql = self.compat_gold_sql(db_id, sql) if gold_compat else self.canonicalize_identifiers(db_id, sql)
        try:
            with self.engine(db_id).connect() as conn:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text(f"SET LOCAL statement_timeout={int(self.timeout_ms)}"))
                rows = conn.execute(text(sql)).fetchall()
            return {"status": "ok", "rows": [tuple(row) for row in rows], "error": None, "sql": sql}
        except Exception as exc:
            message = str(exc)
            return {
                "status": "timeout" if "timeout" in message.lower() else "error",
                "rows": None,
                "error": message[:2000],
                "sql": sql,
            }


def install_semantic_adapter(runtime: RemoteBirdRuntime, db_id: str) -> None:
    """Expose the selected remote database through the grounding interfaces."""
    import data_agent.nl2sql_grounding as grounding
    import data_agent.semantic_layer as semantic_layer

    prefix = f"bird_{db_id}"

    def sources() -> dict[str, Any]:
        items = []
        for table in runtime.tables(db_id):
            items.append({
                "table_name": f"{prefix}.{table}",
                "display_name": table,
                "description": f"BIRD benchmark table {table}",
                "synonyms": [table],
                "suggested_analyses": [],
                "geometry_type": None,
                "srid": None,
                "source_kind": "postgres",
                "nl2sql_enabled": True,
                "nl2sql_priority": 0,
                "confidence": 1.0,
            })
        return {"status": "success", "sources": items, "message": "remote BIRD adapter"}

    def describe(table_name: str) -> dict[str, Any]:
        bare = runtime._bare(table_name)
        columns = runtime.schema(db_id, bare)
        if not columns:
            return {"status": "error", "message": f"Table {table_name} not found"}
        metadata = {
            "display_name": bare,
            "description": f"BIRD benchmark table {bare}",
            "synonyms": [bare],
            "source_kind": "postgres",
            "nl2sql_enabled": True,
            "nl2sql_priority": 0,
        }
        return {
            "status": "success",
            "table_name": table_name,
            "columns": columns,
            "source": metadata,
            "source_metadata": metadata,
            "message": "remote BIRD adapter",
        }

    # build_nl2sql_context imported these names into its own module, so patch
    # both the source module and the already-imported aliases.
    semantic_layer.list_semantic_sources = sources
    semantic_layer.describe_table_semantic = describe
    grounding.list_semantic_sources = sources
    grounding.describe_table_semantic = describe
    grounding.resolve_semantic_context = lambda _question: {"sources": []}
    grounding._estimate_table_size = lambda table_name: runtime.row_count(db_id, table_name)
    grounding._sample_distinct_values = (
        lambda table_name, column_name, limit=5: runtime.sample_values(
            db_id, table_name, column_name, limit
        )
    )


BASELINE_SYSTEM = (
    "You are a PostgreSQL SQL expert. Convert the user question into one read-only "
    "SELECT query. Output SQL only, with no commentary or markdown fences. Use bare "
    "table names from the supplied public schema. Use PostgreSQL syntax. Do not add "
    "LIMIT unless the question explicitly asks for top-K or a preview."
)


def llm_sql(prompt: str, config: OpenAICompatibleLLMConfig, max_tokens: int = 1280) -> tuple[str, dict[str, Any]]:
    raw, evidence = chat_completion(
        system_prompt=BASELINE_SYSTEM,
        user_prompt=prompt,
        config=config,
        max_tokens=max_tokens,
    )
    return _strip_fences(raw), evidence


def baseline_generate(runtime: RemoteBirdRuntime, config: OpenAICompatibleLLMConfig, q: dict) -> dict[str, Any]:
    prompt = (
        f"SCHEMA:\n{runtime.schema_dump(q['db_id'])}\n\n"
        + (f"EVIDENCE/HINTS:\n{q.get('evidence', '')}\n\n" if q.get("evidence") else "")
        + f"QUESTION: {q['question']}\n\nSQL:"
    )
    started = time.perf_counter()
    try:
        sql, evidence = llm_sql(prompt, config)
        return {"status": "ok", "sql": sql, "error": None,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "llm": evidence}
    except Exception as exc:
        return {"status": "error", "sql": "", "error": str(exc)[:2000],
                "latency_ms": round((time.perf_counter() - started) * 1000), "llm": {}}


async def full_generate(runtime: RemoteBirdRuntime, config: OpenAICompatibleLLMConfig, q: dict) -> dict[str, Any]:
    """Run grounding, local SQL generation, post-processing and two repairs."""
    import data_agent.nl2sql_grounding as grounding
    from data_agent.nl2sql_executor import _retry_with_llm
    from data_agent.sql_postprocessor import postprocess_sql
    from data_agent.nl2sql_intent import classify_intent

    db_id = q["db_id"]
    install_semantic_adapter(runtime, db_id)
    started = time.perf_counter()
    try:
        ctx = grounding.build_nl2sql_context(
            q["question"],
            schema_filter=f"bird_{db_id}",
            family="gemma",
            execution_engine="postgis",
        )
        schema_dump = runtime.schema_dump(db_id)
        grounding_text = ctx.get("grounding_prompt", "")
        table_schemas = {
            str(table["table_name"]): table.get("columns", [])
            for table in ctx.get("candidate_tables", [])
        }
        large_tables = {
            str(table["table_name"])
            for table in ctx.get("candidate_tables", [])
            if int(table.get("row_count_hint", 0) or 0) >= 1_000_000
        }
        intent = classify_intent(q["question"], strategy="rule_only").primary
        prompt = (
            f"Database: PostgreSQL database bird_{db_id}, public schema.\n"
            f"SCHEMA:\n{schema_dump}\n\n"
            + (f"EVIDENCE/HINTS:\n{q.get('evidence', '')}\n\n" if q.get("evidence") else "")
            + f"[GIS Data Agent NL2SQL Grounding]\n{grounding_text}\n\n"
            "Rules:\n"
            "- Output ONLY one SELECT/WITH SQL query.\n"
            "- Use bare public table names; do not prefix tables with bird_ database name.\n"
            "- Preserve PostgreSQL case-sensitive identifiers with double quotes.\n"
            "- Do not add LIMIT unless the question explicitly requests top-K or preview.\n"
            f"QUESTION: {q['question']}\n\nSQL:"
        )
        raw_sql, llm_evidence = llm_sql(prompt, config)
        pp = postprocess_sql(raw_sql, table_schemas, large_tables, intent=intent)
        if pp.rejected:
            return {"status": "rejected", "sql": "", "error": pp.reject_reason,
                    "grounding": ctx, "latency_ms": round((time.perf_counter() - started) * 1000),
                    "llm": llm_evidence}
        sql = pp.sql
        last = runtime.execute(db_id, sql)
        repairs = 0
        for _ in range(2):
            if last.get("status") == "ok":
                break
            fixed = _retry_with_llm(
                q["question"], sql, str(last.get("error", "")), table_schemas,
                execution_engine="postgis",
            )
            if not fixed:
                break
            repaired = postprocess_sql(fixed, table_schemas, large_tables, intent=intent)
            if repaired.rejected:
                break
            sql = repaired.sql
            last = runtime.execute(db_id, sql)
            repairs += 1
        return {"status": "ok" if sql else "no_sql", "sql": sql, "error": None,
                "repairs": repairs, "grounding": ctx,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "llm": llm_evidence}
    except Exception as exc:
        return {"status": "error", "sql": "", "error": str(exc)[:2000],
                "latency_ms": round((time.perf_counter() - started) * 1000), "llm": {}}


def load_questions(path: Path, limit: int | None, difficulties: set[str] | None, db_ids: set[str] | None) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    selected = []
    seen = set()
    for item in raw:
        if item["question_id"] in seen:
            continue
        seen.add(item["question_id"])
        if difficulties and item.get("difficulty") not in difficulties:
            continue
        if db_ids and item.get("db_id") not in db_ids:
            continue
        selected.append(item)
        if limit and len(selected) >= limit:
            break
    return selected


def result_record(
    runtime: RemoteBirdRuntime,
    q: dict,
    generated: dict[str, Any],
    mode: str,
    gold_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db_id = q["db_id"]
    predicted = runtime.execute(db_id, generated.get("sql", "")) if generated.get("sql") else {
        "status": "error", "rows": None, "error": "empty SQL", "sql": ""
    }
    gold = gold_result or runtime.execute(db_id, q.get("SQL", ""), gold_compat=True)
    valid = predicted["status"] == "ok"
    correct = bool(valid and gold["status"] == "ok" and compare_results(gold["rows"], predicted["rows"]))
    return {
        "qid": q["question_id"],
        "db_id": db_id,
        "difficulty": q.get("difficulty", "?"),
        "question": q["question"],
        "evidence": q.get("evidence", ""),
        "gold_sql": q.get("SQL", ""),
        "gold_exec_sql": gold.get("sql", ""),
        "pred_sql": predicted.get("sql", generated.get("sql", "")),
        "ex": int(correct),
        "valid": int(valid),
        "mode": mode,
        "gen_status": generated.get("status"),
        "gen_error": generated.get("error"),
        "pred_status": predicted.get("status"),
        "pred_error": predicted.get("error"),
        "gold_status": gold.get("status"),
        "gold_error": gold.get("error"),
        "repairs": generated.get("repairs", 0),
        "latency_ms": generated.get("latency_ms", 0),
        "grounding_tables": [
            table.get("table_name")
            for table in generated.get("grounding", {}).get("candidate_tables", [])
        ],
    }


def summarize(records: list[dict], mode: str, config: OpenAICompatibleLLMConfig, benchmark: Path) -> dict[str, Any]:
    n = len(records)
    by_diff: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    by_db: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for record in records:
        for bucket, key in ((by_diff, record["difficulty"]), (by_db, record["db_id"])):
            bucket[key][0] += 1
            bucket[key][1] += record["ex"]
            bucket[key][2] += record["valid"]

    def finish(bucket: dict[str, list[int]]) -> dict[str, dict[str, Any]]:
        return {
            key: {"n": vals[0], "ex": vals[1], "valid": vals[2],
                  "execution_accuracy": round(vals[1] / vals[0], 4),
                  "valid_sql_rate": round(vals[2] / vals[0], 4)}
            for key, vals in sorted(bucket.items())
        }

    ex = sum(item["ex"] for item in records)
    valid = sum(item["valid"] for item in records)
    gold_valid = sum(1 for item in records if item.get("gold_status") == "ok")
    gold_errors = Counter(
        (item.get("gold_error") or "").splitlines()[0][:240]
        for item in records
        if item.get("gold_status") != "ok"
    )
    return {
        "mode": mode,
        "benchmark": str(benchmark),
        "n": n,
        "correct": ex,
        "valid_sql": valid,
        "execution_accuracy": round(ex / n, 4) if n else 0.0,
        "valid_sql_rate": round(valid / n, 4) if n else 0.0,
        "gold_sql_executable": gold_valid,
        "gold_sql_failed": n - gold_valid,
        "gold_failure_types": dict(gold_errors.most_common()),
        "by_difficulty": finish(by_diff),
        "by_database": finish(by_db),
        "model": config.model,
        "provider": config.provider,
        "ollama_base_url": config.base_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold_comparison": "unordered execution-result equivalence; numeric values rounded to 5 decimals",
        "gold_sql_adaptation": "identifiers canonicalized and text date columns cast for EXTRACT/strftime only during Gold execution",
    }


def write_report(out_dir: Path, summaries: dict[str, dict], records: dict[str, list[dict]], args: argparse.Namespace) -> None:
    payload = {
        "benchmark": str(Path(args.bench).resolve()),
        "connection": {"host": args.host, "port": args.port, "database_pattern": "bird_<db_id>", "user": args.user},
        "model": {"provider": "ollama", "model": args.model, "base_url": args.ollama_base_url},
        "notes": [
            "Remote BIRD databases are queried read-only with statement_timeout.",
            "Full mode uses the current NL2SQL grounding and SQL postprocessor with an ephemeral remote metadata adapter; no semantic metadata is written remotely.",
            "BIRD databases do not contain the GIS Data Agent control-plane semantic registry, so benchmark-specific few-shot retrieval and persisted semantic annotations are excluded.",
            "Gold SQL is preserved verbatim in each record. Gold execution uses a compatibility adapter for mixed-case imported identifiers and source text date columns; predicted SQL is evaluated without this Gold-only adaptation.",
        ],
        "summaries": summaries,
    }
    (out_dir / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# GIS Data Agent BIRD PostgreSQL Evaluation",
        "",
        f"- Benchmark: `{Path(args.bench).resolve()}`",
        f"- Model: `{args.model}` via Ollama (`args.ollama_base_url`)",
        "- Database layout: one read-only `bird_<db_id>` database per question database",
        "",
    ]
    for mode, summary in summaries.items():
        lines.extend([
            f"## {mode}",
            "",
            f"Execution accuracy: **{summary['correct']}/{summary['n']} = {summary['execution_accuracy']:.2%}**",
            f"Valid SQL rate: **{summary['valid_sql']}/{summary['n']} = {summary['valid_sql_rate']:.2%}**",
            "",
            "| Difficulty | N | Correct | Accuracy | Valid SQL |",
            "|---|---:|---:|---:|---:|",
        ])
        for key, item in summary["by_difficulty"].items():
            lines.append(f"| {key} | {item['n']} | {item['ex']} | {item['execution_accuracy']:.2%} | {item['valid']}/{item['n']} |")
        lines.extend(["", "| Database | N | Correct | Accuracy | Valid SQL |", "|---|---:|---:|---:|---:|"])
        for key, item in summary["by_database"].items():
            lines.append(f"| {key} | {item['n']} | {item['ex']} | {item['execution_accuracy']:.2%} | {item['valid']}/{item['n']} |")
        lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    for mode, items in records.items():
        (out_dir / f"{mode}_results.json").write_text(
            json.dumps({"summary": summaries[mode], "records": items}, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )


async def run(args: argparse.Namespace) -> int:
    bench = Path(args.bench).resolve()
    questions = load_questions(bench, args.limit, set(args.difficulty.split(",")) if args.difficulty else None,
                               set(args.db_id.split(",")) if args.db_id else None)
    password = args.password or os.environ.get("BIRD_PG_PASSWORD", "")
    if not password:
        raise SystemExit("Missing database password: set BIRD_PG_PASSWORD or --password")
    runtime = RemoteBirdRuntime(args.host, args.port, args.user, password, args.statement_timeout_ms)
    config = OpenAICompatibleLLMConfig(
        provider="ollama",
        base_url=args.ollama_base_url.rstrip("/"),
        model=args.model,
        api_key="ollama",
        timeout_seconds=args.llm_timeout_seconds,
        api_style="chat",
    )
    os.environ["GDA_LLM_PROVIDER"] = "ollama"
    os.environ["GDA_LLM_BASE_URL"] = config.base_url
    os.environ["GDA_LLM_MODEL"] = config.model
    os.environ["NL2SQL_AGENT_FAMILY"] = "gemma"
    os.environ["NL2SQL_DISABLE_FEWSHOT"] = "1"
    modes = ["baseline", "full"] if args.mode == "both" else [args.mode]
    out_dir = Path(args.out_dir).resolve() if args.out_dir else DEFAULT_OUT_ROOT / f"bird_remote_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[bird-remote] questions={len(questions)} modes={','.join(modes)} model={config.model}")
    print(f"[bird-remote] output={out_dir}")
    print("[bird-remote] preflighting Gold SQL with PostgreSQL compatibility adapter...")
    gold_results = {}
    gold_error_types = Counter()
    for index, question in enumerate(questions, 1):
        gold = runtime.execute(question["db_id"], question.get("SQL", ""), gold_compat=True)
        gold_results[question["question_id"]] = gold
        if gold.get("status") != "ok":
            gold_error_types[(gold.get("error") or "").splitlines()[0][:240]] += 1
        if index % 25 == 0 or index == len(questions):
            print(f"[gold {index}/{len(questions)}] executable={index - sum(gold_error_types.values())} failed={sum(gold_error_types.values())}")
    print(f"[gold] executable={len(questions) - sum(gold_error_types.values())}/{len(questions)}; "
          f"failed={sum(gold_error_types.values())}")
    if gold_error_types:
        for error, count in gold_error_types.most_common(10):
            print(f"[gold-error] {count}x {error}")
    all_records: dict[str, list[dict]] = {}
    summaries: dict[str, dict] = {}
    for mode in modes:
        records = []
        print(f"\n=== {mode.upper()} ===")
        for index, question in enumerate(questions, 1):
            if mode == "baseline":
                generated = baseline_generate(runtime, config, question)
            else:
                generated = await full_generate(runtime, config, question)
            record = result_record(runtime, question, generated, mode, gold_results.get(question["question_id"]))
            records.append(record)
            tag = "OK" if record["ex"] else ("VAL" if record["valid"] else "ERR")
            print(f"[{index}/{len(questions)}] {tag} qid={record['qid']} db={record['db_id']} "
                  f"difficulty={record['difficulty']} latency={record['latency_ms']}ms")
            # Keep partial output usable if a long local inference run is interrupted.
            if index % 10 == 0:
                partial = summarize(records, mode, config, bench)
                (out_dir / f"{mode}_partial.json").write_text(
                    json.dumps({"summary": partial, "records": records}, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )
        all_records[mode] = records
        summaries[mode] = summarize(records, mode, config, bench)
        item = summaries[mode]
        print(f"[{mode}] execution accuracy={item['correct']}/{item['n']}={item['execution_accuracy']:.2%}; "
              f"valid SQL={item['valid_sql']}/{item['n']}={item['valid_sql_rate']:.2%}")
    write_report(out_dir, summaries, all_records, args)
    if "baseline" in summaries and "full" in summaries:
        print(f"[bird-remote] delta full-baseline="
              f"{summaries['full']['execution_accuracy'] - summaries['baseline']['execution_accuracy']:+.2%}")
    print(f"[bird-remote] report={out_dir / 'report.md'}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bench", default=str(DEFAULT_BENCH))
    p.add_argument("--mode", choices=("baseline", "full", "both"), default="both")
    p.add_argument("--limit", type=int)
    p.add_argument("--difficulty")
    p.add_argument("--db-id")
    p.add_argument("--out-dir")
    p.add_argument("--host", default=os.environ.get("BIRD_PG_HOST", "8.134.70.55"))
    p.add_argument("--port", type=int, default=int(os.environ.get("BIRD_PG_PORT", "32004")))
    p.add_argument("--user", default=os.environ.get("BIRD_PG_USER", "postgres"))
    p.add_argument("--password", default=None)
    p.add_argument("--statement-timeout-ms", type=int, default=30000)
    p.add_argument("--ollama-base-url", default=os.environ.get("BIRD_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"))
    p.add_argument("--model", default=os.environ.get("BIRD_OLLAMA_MODEL", "Gemma4:26b"))
    p.add_argument("--llm-timeout-seconds", type=float, default=180.0)
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parser().parse_args())))

"""Registered, read-only BIRD PostgreSQL sources for NL2SQL."""

from __future__ import annotations

import json
import math
import os
import re
from contextlib import ExitStack
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from .db_engine import get_engine
from .user_context import current_user_id, current_user_role
from .nl2sql_observability import observe_stage, stage, annotate_stage

DB_ID_RE = re.compile(r"^[a-z0-9_]+$")
load_dotenv(Path(__file__).with_name(".bird.env"), override=False)


def visible_bird_sources(conn) -> set[str]:
    username = current_user_id.get()
    if not username or username == "anonymous":
        return set()
    try:
        rows = conn.execute(text("""
            SELECT source_name FROM agent_bird_databases
            WHERE owner_username=:username OR :is_admin
        """), {"username": username, "is_admin": current_user_role.get() == "admin"})
    except SQLAlchemyError:
        return set()
    return {row[0] for row in rows}


@observe_stage("request.source_authorize")
def registered_database(db_id: str) -> str:
    if not DB_ID_RE.fullmatch(db_id or ""):
        raise ValueError("Invalid BIRD database ID")
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Control database is unavailable")
    username = current_user_id.get()
    if not username or username == "anonymous":
        raise PermissionError("BIRD source access requires an authenticated user")
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT database_name FROM agent_bird_databases "
            "WHERE db_id=:db_id AND (owner_username=:username OR :is_admin)"
        ), {"db_id": db_id, "username": username,
            "is_admin": current_user_role.get() == "admin"}).first()
    if row is None or row[0] != f"bird_{db_id}":
        raise PermissionError("BIRD source is unavailable to the current user")
    return row[0]


def authorized_semantic_source_ids(db_id: str) -> dict[str, int]:
    """Return real registry anchors, never a fabricated compiler source ID."""
    database_name = registered_database(db_id)
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT id,table_name FROM agent_semantic_sources
            WHERE split_part(table_name,'.',1)=:source
              AND (owner_username=:username OR :is_admin)
        """), {"source": database_name, "username": current_user_id.get(),
               "is_admin": current_user_role.get() == "admin"})
        return {row[1]: int(row[0]) for row in rows}


@lru_cache(maxsize=16)
def _remote_engine(database_name: str):
    required = ("BIRD_PG_HOST", "BIRD_PG_USER", "BIRD_PG_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("BIRD connection is not configured: " + ", ".join(missing))
    return create_engine(URL.create(
        "postgresql+psycopg2",
        username=os.environ["BIRD_PG_USER"],
        password=os.environ["BIRD_PG_PASSWORD"],
        host=os.environ["BIRD_PG_HOST"],
        port=int(os.environ.get("BIRD_PG_PORT", "5432")),
        database=database_name,
    ), pool_size=1, max_overflow=0, pool_pre_ping=True, connect_args={"connect_timeout": 10})


@observe_stage("catalog.schema_fetch")
def source_schema(table_name: str) -> dict | None:
    if "." not in table_name:
        return None
    source_name, bare_name = table_name.split(".", 1)
    if not source_name.startswith("bird_"):
        return None
    db_id = source_name[5:]
    if not DB_ID_RE.fullmatch(db_id) or not bare_name:
        return None
    try:
        registered_database(db_id)
    except (PermissionError, ValueError) as exc:
        return {"status": "error", "message": str(exc)}
    engine = get_engine()
    if engine is None:
        return None
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT t.columns_json, t.foreign_keys_json, t.primary_keys_json,
                   t.estimated_rows, t.description, s.display_name, s.synonyms
            FROM agent_bird_tables t
            JOIN agent_semantic_sources s
              ON s.table_name = 'bird_' || t.db_id || '.' || t.table_name
            WHERE t.db_id=:db_id AND t.table_name=:table_name
        """), {"db_id": db_id, "table_name": bare_name}).first()
        if row is None:
            return None
        annotations = conn.execute(text("""
            SELECT column_name, semantic_domain, aliases, unit, description, value_semantics
            FROM agent_semantic_registry WHERE table_name=:table_name
        """), {"table_name": table_name}).all()
    by_name = {r[0].casefold(): r for r in annotations}
    columns = []
    for raw in row[0]:
        column = dict(raw)
        annotation = by_name.get(column["column_name"].casefold())
        if annotation:
            column.update(semantic_domain=annotation[1], aliases=annotation[2] or [],
                          unit=annotation[3] or "", description=annotation[4] or column.get("description") or "",
                          value_semantics=annotation[5] or {})
        columns.append(column)
    source = {"display_name": row[5] or bare_name, "description": row[4],
              "synonyms": row[6] or [], "source_kind": "bird_postgres",
              "estimated_rows": row[3], "foreign_keys": row[1], "primary_keys": row[2]}
    lines = [f"Table {table_name}: {row[4]}"]
    lines += [f"- {c['column_name']} ({c['data_type']}): {c.get('description') or ''}" for c in columns]
    return {"status": "success", "columns": columns, "source": source,
            "source_metadata": source, "message": "\n".join(lines)}


def _validated_sql(db_id: str, sql: str, table_columns: dict[str, list[str]],
                   *, named_parameters: bool = False) -> str:
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import Scope, traverse_scope

    statements = sqlglot.parse(sql, read="postgres")
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
        raise ValueError("Only one SELECT statement is allowed")
    tree = statements[0]
    if any(isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Command))
           for node in tree.walk()):
        raise ValueError("SQL contains a forbidden operation")
    known = {name.casefold(): name for name in table_columns}
    scopes = list(traverse_scope(tree))
    physical_tables = {}
    # Resolve each relation in its own scope: a CTE with the same name in a
    # sibling query must not authorize an unknown physical table.
    for scope in scopes:
        for _, (_, source) in scope.selected_sources.items():
            if isinstance(source, exp.Table):
                physical_tables[id(source)] = source
    for table in physical_tables.values():
        name = table.name
        if table.catalog:
            raise ValueError("SQL references a different database")
        if table.db and table.db.casefold() not in {"public", f"bird_{db_id}"}:
            raise ValueError("SQL references a different database")
        actual = known.get(name.casefold())
        if actual is None:
            raise ValueError(f"SQL references an unregistered table: {name}")
        table.set("db", None)
        table.set("this", exp.Identifier(this=actual, quoted=True))

    def source_columns(source):
        if isinstance(source, exp.Table):
            return {name.casefold(): exp.Identifier(this=name, quoted=True)
                    for name in table_columns[source.name]}
        if isinstance(source, Scope):
            # Preserve output aliases, whose casing follows PostgreSQL rules,
            # instead of rewriting them using unrelated physical columns.
            outputs = {}
            for projection in source.expression.selects:
                identifier = projection.args.get("alias")
                if identifier is None and isinstance(projection, exp.Column):
                    identifier = projection.args.get("this")
                if isinstance(identifier, exp.Identifier):
                    outputs[identifier.name.casefold()] = identifier
                elif projection.is_star:
                    for _, (_, inner) in source.selected_sources.items():
                        outputs.update(source_columns(inner))
            return outputs
        return {}

    # Scopes are visited from inner queries to outer queries, so the emitted
    # column names of CTEs/subqueries are available to their consumers.
    seen_columns = set()
    for scope in scopes:
        for column in scope.columns:
            if id(column) in seen_columns:
                continue
            seen_columns.add(id(column))
            if column.catalog or (column.db and column.db.casefold() not in
                                  {"public", f"bird_{db_id}"}):
                raise ValueError("SQL references a different database")
            matches = []
            current = scope
            while current is not None:
                for key, (_, source) in current.selected_sources.items():
                    if column.table and key.casefold() != column.table.casefold():
                        continue
                    if column.db and (not isinstance(source, exp.Table) or source.alias):
                        raise ValueError("Schema-qualified column must reference a physical table")
                    identifier = source_columns(source).get(column.name.casefold())
                    if identifier is not None or column.is_star:
                        matches.append((source, identifier))
                if matches or not column.table:
                    break
                current = current.parent
            if len(matches) == 1:
                source, identifier = matches[0]
                if identifier is not None:
                    column.set("this", identifier.copy())
                if column.table:
                    if isinstance(source, exp.Table):
                        qualifier = (source.args["alias"].args["this"] if source.alias
                                     else source.args["this"])
                    else:
                        # CTE/subquery aliases remain exactly as declared.
                        qualifier = column.args["table"]
                    column.set("table", qualifier.copy())
                column.set("db", None)
            elif matches and not column.table:
                identifiers = [item[1] for item in matches if item[1] is not None]
                if identifiers and len({item.sql() for item in identifiers}) == 1:
                    column.set("this", identifiers[0].copy())
    if named_parameters:
        from sqlglot.dialects.postgres import Postgres

        class BoundPostgresGenerator(Postgres.Generator):
            def placeholder_sql(self, expression):
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", expression.name or ""):
                    raise ValueError("Invalid named query parameter")
                return ":" + expression.name

        # Generator subclasses do not infer their dialect from their class.
        # PostgreSQL sorts NULL first for DESC; the generic default instead
        # removes DESC NULLS LAST as redundant and changes the executed result.
        return BoundPostgresGenerator(dialect=Postgres()).generate(tree)
    return tree.sql(dialect="postgres")


def _validated_parameters(sql: str, parameters: Mapping | None) -> dict:
    """Require an exact set of finite scalar bindings before remote access."""
    import sqlglot
    from sqlglot import exp

    names = {node.name for node in sqlglot.parse_one(sql, read="postgres").find_all(exp.Placeholder)}
    bindings = dict(parameters or {})
    if set(bindings) != names:
        raise ValueError("Query parameters do not match SQL placeholders")
    for name, value in bindings.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("Invalid named query parameter")
        if type(value) not in {str, int, float, bool} or (
            type(value) is float and not math.isfinite(value)
        ):
            raise ValueError("Query parameters must be finite scalar values")
    return bindings


@observe_stage("database.query")
def query_rows(db_id: str, sql: str, *, max_rows: int = 100000,
               parameters: Mapping | None = None) -> tuple[list[str], list[tuple], bool]:
    database_name = registered_database(db_id)
    control = get_engine()
    with control.connect() as conn:
        table_columns = {row[0]: [item["column_name"] for item in row[1]]
                         for row in conn.execute(text(
            "SELECT table_name,columns_json FROM agent_bird_tables WHERE db_id=:db_id"
        ), {"db_id": db_id})}
    if not table_columns:
        raise ValueError("BIRD source has no registered tables")
    with stage("query.source_audit"):
        safe_sql = _validated_sql(db_id, sql, table_columns, named_parameters=parameters is not None)
        bindings = _validated_parameters(safe_sql, parameters)
    limit = max(1, min(int(max_rows), 100000))
    timeout = max(1000, min(int(os.environ.get("BIRD_STATEMENT_TIMEOUT_MS", "60000")), 120000))
    with ExitStack() as resources:
        # SQLAlchemy checkout includes connection creation on a cold pool.
        # Do not claim this separates server/network time from pool queueing.
        engine = _remote_engine(database_name)
        with stage("database.pool_checkout"):
            conn = resources.enter_context(engine.connect())
        with stage("database.session_setup"):
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql("SET LOCAL ROLE pg_read_all_data")
            conn.execute(text("SET LOCAL statement_timeout = :timeout"), {"timeout": timeout})
        statement = text(f"SELECT * FROM ({safe_sql}) AS _bird_result LIMIT {limit + 1}")
        with stage("database.execute"):
            result = conn.execute(statement, bindings) if bindings else conn.execute(statement)
        with stage("database.fetch"):
            columns = list(result.keys())
            rows = [tuple(row) for row in result.fetchall()]
    annotate_stage(result_rows=min(len(rows), limit), truncated=len(rows) > limit)
    return columns, rows[:limit], len(rows) > limit


def execute_bird_sql(db_id: str, sql: str, *, max_rows: int = 100000,
                     parameters: Mapping | None = None) -> str:
    try:
        columns, rows, truncated = query_rows(db_id, sql, max_rows=max_rows, parameters=parameters)
        return json.dumps({"status": "ok", "rows": len(rows), "columns": columns,
                           "data": [dict(zip(columns, row)) for row in rows[:100]],
                           "truncated": truncated, "engine": "bird_postgres"}, default=str)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc), "engine": "bird_postgres"})

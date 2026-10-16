"""Expose registered business formulas within the current source boundary."""
from __future__ import annotations

import json


class MetricCatalogUnavailable(RuntimeError):
    """An enabled semantic compiler must not silently lose its registry."""


def metric_uses_authorized_fields(definition: str, payload: dict) -> bool:
    """A formula must bind each column uniquely to the authorized candidates."""
    import sqlglot
    from sqlglot import exp

    try:
        parsed = sqlglot.parse(definition, read="postgres")
        if len(parsed) != 1 or parsed[0] is None:
            return False
        tree = parsed[0]
        if any(isinstance(node, (exp.Query, exp.Table, exp.Command, exp.Insert,
                                 exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter))
               for node in tree.walk()):
            return False
        # A formula is a mathematical expression, not an arbitrary database
        # function call. Merely validating columns would admit functions such
        # as pg_read_file(amount) or a privileged user-defined function.
        safe_functions = {"ABS", "AVG", "CAST", "CEIL", "CEILING", "COALESCE",
                          "COUNT", "EXTRACT", "FLOOR", "MAX", "MIN", "NULLIF",
                          "ROUND", "SUM", "TRY_CAST", "CASE", "IF", "AND", "OR"}
        for function in tree.find_all(exp.Func):
            name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
            if name.upper() not in safe_functions:
                return False
        tables = {
            table["table_name"].casefold(): {
                column["column_name"].casefold() for column in table.get("columns") or []}
            for table in payload.get("candidate_tables") or [] if table.get("table_name")
        }
        columns = list(tree.find_all(exp.Column))
        if not columns:
            return False
        for column in columns:
            if column.catalog or column.is_star:
                return False
            if column.db:
                names = [f"{column.db}.{column.table}".casefold()]
            elif column.table:
                names = [name for name in tables if name.rsplit(".", 1)[-1] == column.table.casefold()]
            else:
                names = list(tables)
            matches = [name for name in names if name in tables and column.name.casefold() in tables[name]]
            if len(matches) != 1:
                return False
        return True
    except Exception:
        return False


def registered_metrics(payload: dict, *, required: bool = False) -> list[dict]:
    """Return owned/system metrics whose declared source and fields are in scope.

    This registry query is separate from the static metric template catalog.
    It never retrieves reference SQL or benchmark content. A domain used here
    is a registered source/table name, giving formulas a concrete source scope.
    """
    from sqlalchemy import text
    from .db_engine import get_engine
    from .user_context import current_user_id, current_user_role

    user = current_user_id.get()
    if not user or user == "anonymous":
        return []
    scopes = set()
    for table in payload.get("candidate_tables") or []:
        name = table.get("table_name") or ""
        if name:
            scopes.add(name)
            if "." in name:
                scopes.add(name.split(".", 1)[0])
    if not scopes:
        return []
    engine = get_engine()
    if engine is None:
        if required:
            raise MetricCatalogUnavailable("metric_catalog_unavailable")
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT metric_name,definition,domain,description,unit,aliases,semantic_contract
                FROM agent_semantic_metrics
                WHERE domain=ANY(:scopes)
                  AND (owner_username=:username OR owner_username='system' OR :is_admin)
                ORDER BY metric_name
            """), {"scopes": sorted(scopes), "username": user,
                   "is_admin": current_user_role.get() == "admin"}).all()
        metrics = [
            {"name": row[0], "definition": row[1], "source_scope": row[2],
             "description": row[3], "unit": row[4],
             "aliases": [value.strip() for value in (row[5] or "").split(",") if value.strip()],
             "semantic_contract": row[6] or {}}
            for row in rows if metric_uses_authorized_fields(row[1], payload)
        ]
        return metrics
    except Exception as exc:
        if required:
            # Do not return connection strings or registry contents in errors.
            raise MetricCatalogUnavailable("metric_catalog_unavailable") from exc
        return []


def registered_metric_context(payload: dict, metrics: list[dict] | None = None) -> str:
    """Render the same governed definitions used by the optional compiler."""
    metrics = registered_metrics(payload) if metrics is None else metrics
    from .nl2sql_semantic_retrieval import semantic_retrieval_enabled, select_metric_hits
    if semantic_retrieval_enabled() and payload.get("user_question"):
        metrics = select_metric_hits(payload["user_question"], metrics)
    if not metrics:
        return ""
    context = ("\nRegistered source-scoped business metrics:\n"
               + json.dumps(metrics, ensure_ascii=False)
               + "\nUse a formula only for the requested metric and stated population. "
               "Preserve its unit. Ratios differ from percentages; convert only "
               "when the requested output unit requires it. Do not add metric "
               "output columns that the question did not request. Registered metrics "
               "are reusable contracts, not permission to change the requested population "
               "or multiply an entity by joined detail rows.\n")
    from .nl2sql_metric_compiler import metric_compilation_enabled, metric_compilation_guidance
    if metric_compilation_enabled():
        context += metric_compilation_guidance(metrics)
    return context

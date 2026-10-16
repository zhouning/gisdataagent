"""Observe real values for user-supplied literals within authorized BIRD tables."""
from __future__ import annotations

import re


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _lookup_bird_literal(db_id: str, table: str, column: str, literal: str) -> dict:
    from sqlalchemy import text
    from .bird_source import _remote_engine, registered_database, source_schema

    database = registered_database(db_id)
    schema = source_schema(f"{database}.{table}")
    if not schema or schema.get("status") != "success":
        raise PermissionError("Literal lookup source is unavailable")
    fields = {c["column_name"]: c for c in schema["columns"]}
    field = fields.get(column)
    if not field or field.get("data_type") not in {"text", "character varying", "character"}:
        raise ValueError("Literal lookup requires a registered text field")
    quote = lambda identifier: '"' + identifier.replace('"', '""') + '"'
    table_ref, field_ref = quote(table), quote(column)
    tokens = re.findall(r"[^\W_]+", literal, flags=re.UNICODE)
    pattern = "%" + "%".join(_escape_like(token) for token in tokens) + "%"
    with _remote_engine(database).connect() as conn:
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        conn.exec_driver_sql("SET LOCAL ROLE pg_read_all_data")
        conn.execute(text("SET LOCAL statement_timeout = 2000"))
        exact = conn.execute(text(
            f"SELECT DISTINCT {field_ref} FROM {table_ref} "
            f"WHERE {field_ref}=:literal LIMIT 5"
        ), {"literal": literal}).scalars().all()
        observed = exact
        if not exact and tokens:
            observed = conn.execute(text(
                f"SELECT DISTINCT {field_ref} FROM {table_ref} "
                f"WHERE {field_ref} ILIKE :pattern ORDER BY {field_ref} LIMIT 8"
            ), {"pattern": pattern}).scalars().all()
    return {"table": f"{database}.{table}", "column": column, "requested_literal": literal,
            "exact_match": bool(exact), "observed_values": [str(v)[:200] for v in observed],
            "provenance": "authorized read-only source lookup", "complete_domain": False}


def _related_field_names(left: str, right: str, *, include_identifier_labels: bool = False) -> bool:
    """Conservative singular/plural neighbor discovery, never semantic binding."""
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.casefold())
    first, second = normalize(left), normalize(right)
    if include_identifier_labels:
        def role(value):
            if value in {"name", "title", "label", "displayname", "fullname"} or value.endswith("name"):
                return "label"
            if value == "code" or value.endswith("code"):
                return "code"
            return "other"
        if {role(first), role(second)} == {"label", "code"}:
            return True
    return bool(first and second and first != second
                and (first + "s" == second or second + "s" == first))


def collect_literal_evidence(question: str, sql: str, payload: dict, *, max_lookups: int = 6,
                             include_identifier_labels: bool = False) -> list[dict]:
    """Look up equality literals mentioned by the user, never arbitrary values."""
    db_id = payload.get("bird_db_id")
    if not db_id or max_lookups <= 0:
        return []
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import traverse_scope

    try:
        tree = sqlglot.parse_one(sql, read="postgres")
        namespace = f"bird_{db_id}"
        known = {t["table_name"].rsplit(".", 1)[-1].casefold(): t
                 for t in payload.get("candidate_tables") or []
                 if t.get("table_name", "").split(".", 1)[0] == namespace}
        evidence, seen = [], set()
        normalized_question = question.casefold()
        for scope in traverse_scope(tree):
            sources = {alias.casefold(): source for alias, (_, source) in scope.selected_sources.items()
                       if isinstance(source, exp.Table)}
            for predicate in scope.expression.find_all(exp.EQ):
                if predicate.find_ancestor(exp.Select) is not scope.expression:
                    continue
                left, right = predicate.this, predicate.expression
                if isinstance(left, exp.Literal):
                    left, right = right, left
                if not (isinstance(left, exp.Column) and isinstance(right, exp.Literal) and right.is_string):
                    continue
                literal = right.this
                if (len(literal) < 3 or len(literal) > 120 or not re.search(
                        r"(?<!\w)" + re.escape(literal.casefold()) + r"(?!\w)", normalized_question)):
                    continue
                source = sources.get(left.table.casefold()) if left.table else None
                if source is None and not left.table and len(sources) == 1:
                    source = next(iter(sources.values()))
                if source is None:
                    continue
                if source.catalog or (source.db and source.db.casefold() not in {"public", namespace.casefold()}):
                    continue
                table = known.get(source.name.casefold())
                if not table:
                    continue
                fields = {c["column_name"].casefold(): c["column_name"] for c in table.get("columns") or []}
                column = fields.get(left.name.casefold())
                if not column:
                    continue
                table_name = table["table_name"].rsplit(".", 1)[-1]
                identity = (table_name, column, literal)
                if identity in seen:
                    continue
                seen.add(identity)
                try:
                    observed = _lookup_bird_literal(db_id, table_name, column, literal)
                    evidence.append(observed)
                    # A full display string and a similarly named classification
                    # field can encode the same user value differently. Observe
                    # both within this table; the reviewer must still choose by
                    # the governed definition. Never rewrite the SQL here.
                    if observed.get("exact_match") is False:
                        for other in table.get("columns") or []:
                            alternative = other["column_name"]
                            other_type = str(other.get("pg_type") or other.get("data_type") or "").casefold()
                            if (len(evidence) >= max_lookups or alternative == column
                                    or other_type not in {"text", "character varying", "character", "varchar"}
                                    or not _related_field_names(column, alternative, include_identifier_labels=include_identifier_labels)
                                    or (table_name, alternative, literal) in seen):
                                continue
                            seen.add((table_name, alternative, literal))
                            try:
                                candidate = _lookup_bird_literal(db_id, table_name, alternative, literal)
                                candidate["comparison_to_column"] = column
                                candidate["comparison_reason"] = "authorized label/code or spelling neighbor, not an automatic substitution"
                                evidence.append(candidate)
                            except Exception as exc:
                                evidence.append({"table": table["table_name"], "column": alternative,
                                                 "requested_literal": literal, "status": "unavailable",
                                                 "error": str(exc)[:200]})
                except Exception as exc:
                    evidence.append({"table": table["table_name"], "column": column,
                                     "requested_literal": literal, "status": "unavailable",
                                     "error": str(exc)[:200]})
                if len(evidence) >= max_lookups:
                    return evidence
        return evidence
    except Exception:
        return []

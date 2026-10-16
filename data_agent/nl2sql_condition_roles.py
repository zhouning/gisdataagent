"""Keep explicitly optional annotations from narrowing an all-row request.

Only remove a direct, duplicated WHERE equality that already appears in a
projected CASE and is explicitly mentioned in an optional annotation clause.
No field, join, output, aggregation or unmentioned condition is invented.
"""
from __future__ import annotations

import os
import re


def condition_roles_enabled() -> bool:
    return os.environ.get('GDA_NL2SQL_CONDITION_ROLES', '0').casefold() in {'1', 'true', 'yes', 'on'}


def _annotation_clause(question: str) -> tuple[str, str] | None:
    patterns = [
        r'\b(?:and|then)\s+(?:also\s+)?(?:mark|indicate|state|flag|identify|find|show)\b',
        r'(?:并且|同时|并)(?:标记|标注|注明|说明)',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, question, re.I):
            before, annotation = question[:match.start()], question[match.start():]
            if (re.search(r'\b(?:list|show|give|return)\b|列出|显示|返回', before, re.I)
                    and re.search(r'\ball\b|所有|全部', before, re.I)
                    and re.search(r'\b(?:whether|if|any)\b|是否', annotation, re.I)):
                return before, annotation
    return None


def apply_condition_roles(question: str, sql: str, payload: dict) -> tuple[str, list[dict]]:
    if not condition_roles_enabled():
        return sql, []
    clauses = _annotation_clause(question or '')
    if not clauses:
        return sql, []
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import build_scope

    try:
        statements = sqlglot.parse(sql, read='postgres')
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return sql, []
        tree = statements[0]
        if any(tree.args.get(k) for k in ('group', 'having', 'qualify', 'into')):
            return sql, []
        if any(tree.find_all((exp.AggFunc, exp.Window))):
            return sql, []
        where = tree.args.get('where')
        scope = build_scope(tree)
        if where is None or scope is None:
            return sql, []
        # Treat an OR, NOT or nested select as an opaque condition. Removing
        # one of its branches would change Boolean meaning or another scope.
        def conjuncts(node):
            if isinstance(node, exp.Paren):
                return conjuncts(node.this)
            if isinstance(node, exp.And):
                return conjuncts(node.this) + conjuncts(node.expression)
            return [node]

        catalog = {t['table_name'].casefold(): t for t in payload.get('candidate_tables') or []}
        sources = {}
        for alias, (_, source) in scope.selected_sources.items():
            if not isinstance(source, exp.Table) or source.catalog:
                return sql, []
            if source.args.get('alias') and source.args['alias'].args.get('columns'):
                return sql, []
            name = (source.db + '.' + source.name) if source.db else source.name
            table = catalog.get(name.casefold())
            if table is None and not source.db:
                possible = [t for n, t in catalog.items() if n.rsplit('.', 1)[-1] == source.name.casefold()]
                table = possible[0] if len(possible) == 1 else None
            if table is None:
                return sql, []
            sources[alias.casefold()] = table

        def bound_equality(node):
            if not isinstance(node, exp.EQ):
                return None
            column, literal = node.this, node.expression
            if isinstance(column, exp.Literal):
                column, literal = literal, column
            if (not isinstance(column, exp.Column) or column.catalog or column.db
                    or not isinstance(literal, exp.Literal) or not literal.is_string
                    or len(literal.this) < 3):
                return None
            candidates = ([sources[column.table.casefold()]] if column.table.casefold() in sources
                          else [] if column.table else list(sources.values()))
            matches = [(t, c) for t in candidates for c in t.get('columns') or []
                       if c['column_name'].casefold() == column.name.casefold()]
            if len(matches) != 1:
                return None
            table, field = matches[0]
            return (table['table_name'], field['column_name'], column.table.casefold(), literal.this)

        annotation_conditions = set()
        for projection in tree.selects:
            for case in projection.find_all(exp.Case):
                if case.find_ancestor(exp.Select) is not tree:
                    continue
                # A simple CASE field WHEN value needs a separate proof.
                if case.this is not None:
                    continue
                for branch in case.args.get('ifs') or []:
                    binding = bound_equality(branch.this)
                    if binding:
                        annotation_conditions.add(binding)
        kept, changes = [], []
        for condition in conjuncts(where.this):
            binding = bound_equality(condition)
            if binding not in annotation_conditions:
                kept.append(condition.copy())
                continue
            value = binding[3]
            pattern = r'(?<!\w)' + re.escape(value) + r'(?!\w)'
            if (not re.search(pattern, clauses[1], re.I) or re.search(pattern, clauses[0], re.I)
                    or re.search(r'\b(?:only|exclude|excluding|except|without|not)\b|只要|仅|排除|不要', clauses[1], re.I)):
                kept.append(condition.copy())
                continue
            changes.append({'kind': 'optional_annotation_is_not_population_filter',
                            'table': binding[0], 'column': binding[1], 'value': value,
                            'removed_predicate': condition.sql(dialect='postgres'),
                            'population_clause': clauses[0], 'annotation_clause': clauses[1]})
        if not changes:
            return sql, []
        tree.set('where', exp.Where(this=exp.and_(*kept)) if kept else None)
        return tree.sql(dialect='postgres'), changes
    except (sqlglot.errors.SqlglotError, sqlglot.errors.OptimizeError):
        return sql, []

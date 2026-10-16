"""Compile an explicit category-value request from governed field roles.

Only flat projections consisting entirely of source-provenanced categorical
dimensions are eligible. Measures, entity rows and unbound projections retain
their multiplicity. This pass never chooses a field, join or filter.
"""
from __future__ import annotations

import re


def apply_dimension_contract(question: str, sql: str, payload: dict) -> tuple[str, list[dict]]:
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import build_scope

    question = question or ''
    if (not re.search(r'\b(?:what|which|list|state|show|give)\b|列出|有哪些|哪种', question, re.I)
            or re.search(r'\b(?:each|every|per|rows?|records?|observations?|duplicates?|repeated|times)\b'
                         r'|每(?:个|条|行)|逐条|重复|记录', question, re.I)):
        return sql, []
    try:
        statements = sqlglot.parse(sql, read='postgres')
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return sql, []
        tree = statements[0]
        if any(tree.args.get(key) for key in ('distinct', 'group', 'having', 'qualify', 'into')):
            return sql, []
        if any(tree.find_all((exp.Window, exp.AggFunc))):
            return sql, []
        scope = build_scope(tree)
        if scope is None:
            return sql, []
        catalog = {table['table_name'].casefold(): table for table in payload.get('candidate_tables') or []}
        sources = {}
        for alias, (_, source) in scope.selected_sources.items():
            if not isinstance(source, exp.Table) or source.catalog:
                return sql, []
            name = f'{source.db}.{source.name}' if source.db else source.name
            table = catalog.get(name.casefold())
            if table is None and not source.db:
                matches = [value for key, value in catalog.items() if key.rsplit('.', 1)[-1] == source.name.casefold()]
                table = matches[0] if len(matches) == 1 else None
            if table is None:
                return sql, []
            sources[alias.casefold()] = table
        bindings = []
        for projection in tree.selects:
            column = projection.this if isinstance(projection, exp.Alias) else projection
            if not isinstance(column, exp.Column) or column.is_star:
                return sql, []
            table = sources.get(column.table.casefold()) if column.table else None
            if table is None and not column.table:
                possible = [item for item in sources.values() if any(
                    c['column_name'].casefold() == column.name.casefold() for c in item.get('columns') or [])]
                table = possible[0] if len(possible) == 1 else None
            if table is None:
                return sql, []
            field = next((c for c in table.get('columns') or [] if c['column_name'].casefold() == column.name.casefold()), None)
            contract = (field.get('value_semantics') or {}).get('dimension_contract') if field else None
            if not isinstance(contract, dict) or contract.get('role') != 'categorical':
                return sql, []
            provenance = contract.get('provenance') or {}
            if (not provenance.get('url', '').startswith('https://')
                    or not re.fullmatch(r'[0-9a-f]{64}', provenance.get('artifact_sha256', ''))):
                return sql, []
            terms = [term for term in contract.get('request_terms') or [] if isinstance(term, str) and term.strip()]
            # Every projected dimension must be explicitly named. No projection
            # can silently inherit a category request made for another field.
            matched = [term for term in terms if re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', question, re.I)]
            if not matched:
                return sql, []
            bindings.append({'table': table['table_name'], 'column': field['column_name'],
                             'matched_terms': matched, 'provenance': provenance})
        if not bindings:
            return sql, []
        # DISTINCT plus an unrelated ORDER BY expression is invalid in PG and
        # can imply a different answer grain. Do not rewrite such a query.
        order = tree.args.get('order')
        expressions = {p.this.sql() if isinstance(p, exp.Alias) else p.sql() for p in tree.selects}
        aliases = {p.alias for p in tree.selects if p.alias}
        if order and any(o.this.sql() not in expressions and not (
            isinstance(o.this, exp.Column) and not o.this.table and o.this.name in aliases)
            for o in order.expressions):
            return sql, []
        tree.set('distinct', exp.Distinct())
        return tree.sql(dialect='postgres'), [{'kind': 'governed_category_value_grain', 'dimensions': bindings}]
    except sqlglot.errors.SqlglotError:
        return sql, []

"""Compile governed category dimensions into a single explicit SQL predicate.

All categories, synonyms and codes come from source-provenanced metadata. This
pass never adds a missing business filter or chooses an unmentioned measure.
"""
from __future__ import annotations

import re


def requested_category_sets(question: str, payload: dict) -> list[dict]:
    question = ' '.join((question or '').casefold().split())
    contracts = []
    for table in payload.get('candidate_tables') or []:
        for column in table.get('columns') or []:
            definition = (column.get('value_semantics') or {}).get('categorical_dimensions') or {}
            provenance = definition.get('provenance') or {}
            domain = definition.get('domain') or []
            if (not provenance.get('url', '').startswith('https://') or
                    not re.fullmatch(r'[a-f0-9]{64}', provenance.get('artifact_sha256', '')) or
                    not domain or not all(isinstance(x, str) for x in domain)):
                continue
            selected = set(domain)
            matched = []
            ambiguous = False
            for dimension in definition.get('dimensions') or []:
                states = []
                for state in dimension.get('states') or []:
                    values = state.get('values') or []
                    if not values or not set(values) <= set(domain):
                        ambiguous = True
                        break
                    hits = []
                    for alias in state.get('aliases') or []:
                        if not isinstance(alias, str) or not alias.strip():
                            continue
                        for match in re.finditer(r'(?<!\w)' + re.escape(alias.casefold()) + r'(?!\w)', question):
                            prefix = question[:match.start()].rstrip()
                            if re.search(r'\b(?:not|never|except|excluding|without)\s*(?:the\s+)?$',prefix):
                                ambiguous = True
                            hits.append(alias)
                    if hits:
                        states.append((set(values),sorted(set(hits))))
                distinct = {tuple(sorted(values)) for values,_ in states}
                if len(distinct)>1:
                    ambiguous = True
                if states:
                    selected &= states[0][0]
                    matched.append({'dimension':dimension.get('name'),'aliases':states[0][1]})
            if matched and selected and not ambiguous:
                contracts.append({'table':table['table_name'],'column':column['column_name'],
                    'domain':domain,'values':sorted(selected),'matched':matched,'provenance':provenance})
    return contracts


def apply_categorical_contract(question: str, sql: str, payload: dict) -> tuple[str,list[dict]]:
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import traverse_scope

    contracts=requested_category_sets(question,payload)
    if not contracts:
        return sql,[]
    try:
        statements=sqlglot.parse(sql,read='postgres')
        if len(statements)!=1 or not isinstance(statements[0],(exp.Select,exp.SetOperation)):
            return sql,[]
        tree=statements[0];scopes=list(traverse_scope(tree))
    except sqlglot.errors.SqlglotError:
        return sql,[]
    changes=[]
    for contract in contracts:
        quoted_codes = re.findall(r"['\"]([^'\"]+)['\"]", question or "")
        if any(code in contract['domain'] and code not in contract['values'] for code in quoted_codes):
            continue
        matches=[]
        for scope in scopes:
            if not isinstance(scope.expression,exp.Select):
                continue
            sources={key.casefold():source for key,(_,source) in scope.selected_sources.items()}
            for predicate in scope.expression.find_all((exp.EQ,exp.In)):
                if predicate.find_ancestor(exp.Select) is not scope.expression:
                    continue
                parent=predicate.parent
                valid=False
                while parent is not None and parent is not scope.expression:
                    if isinstance(parent,(exp.Not,exp.Or,exp.Join)):
                        break
                    if isinstance(parent,(exp.Where,exp.Having)):
                        valid=True;break
                    if isinstance(parent,exp.If) and parent.this is predicate:
                        valid=True;break
                    if not isinstance(parent,(exp.Paren,exp.And)):
                        break
                    parent=parent.parent
                if not valid:
                    continue
                column=predicate.this
                values=predicate.expressions if isinstance(predicate,exp.In) else [predicate.expression]
                if isinstance(predicate,exp.EQ) and isinstance(column,exp.Literal):
                    column,values=predicate.expression,[predicate.this]
                if (not isinstance(column,exp.Column) or column.name.casefold()!=contract['column'].casefold()
                        or not values or not all(isinstance(v,exp.Literal) and v.is_string for v in values)):
                    continue
                if not {v.this for v in values}<=set(contract['domain']):
                    continue
                source=sources.get(column.table.casefold()) if column.table else None
                if source is None and not column.table and len(sources)==1:
                    source=next(iter(sources.values()))
                if not isinstance(source,exp.Table) or source.catalog:
                    continue
                namespace,_,bare=contract['table'].rpartition('.')
                if (source.name.casefold()!=(bare or contract['table']).casefold()
                        or (source.db and source.db.casefold()!=namespace.casefold())):
                    continue
                if not source.db:
                    possible = [table for table in payload.get('candidate_tables') or []
                                if table['table_name'].rsplit('.',1)[-1].casefold()==source.name.casefold()]
                    if len(possible)!=1:
                        continue
                matches.append((predicate,column,values))
        # Multiple predicates may represent several separately compared populations.
        if len(matches)!=1:
            continue
        predicate,column,previous=matches[0]
        if {v.this for v in previous}==set(contract['values']):
            continue
        values=[exp.Literal.string(v) for v in contract['values']]
        replacement=(exp.EQ(this=column.copy(),expression=values[0]) if len(values)==1
                     else exp.In(this=column.copy(),expressions=values))
        changes.append({**contract,'previous_predicate':predicate.sql(dialect='postgres'),
                        'compiled_predicate':replacement.sql(dialect='postgres')})
        predicate.replace(replacement)
    return (tree.sql(dialect='postgres'),changes) if changes else (sql,[])

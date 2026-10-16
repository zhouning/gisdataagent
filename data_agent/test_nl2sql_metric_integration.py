"""Registered formulas must reach the real product execution path intact."""
import copy
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from data_agent import nl2sql_executor as executor
from data_agent.nl2sql_metric_grounding import MetricCatalogUnavailable


@pytest.fixture
def product(monkeypatch):
    for key, value in {
        'NL2SQL_AGENT_FAMILY': 'gemma', 'GDA_NL2SQL_METRIC_COMPILATION': '1',
        'GDA_NL2SQL_REFERENCE_RANGE_REPAIR': '0', 'GDA_NL2SQL_REFERENCE_RANGE_ENFORCE': '0',
        'GDA_NL2SQL_OUTPUT_CONTRACT': '0', 'GDA_NL2SQL_RELATIONAL_REVIEW': '0',
        'GDA_NL2SQL_ANSWER_PLAN': '0', 'GDA_NL2SQL_REGISTERED_IR': '0',
        'GDA_NL2SQL_EXECUTION_CONSENSUS': '0',
        'GDA_NL2SQL_CONDITION_ROLES': '0',
    }.items():
        monkeypatch.setenv(key, value)
    metric = {'name': 'selected_share', 'definition': '100.0 * SUM(facts.amount) / NULLIF(SUM(facts.total),0)',
              'source_scope': 'public.facts', 'unit': 'percent',
              'semantic_contract': {'row_grain': 'One observation', 'population': 'Selected observations'}}
    payload = {'candidate_tables': [{'table_name': 'public.facts', 'columns': [
        {'column_name': name, 'pg_type': kind} for name, kind in
        [('id', 'integer'), ('amount', 'numeric'), ('total', 'numeric'), ('category', 'text')]]}],
        'registered_metrics': [metric], 'grounding_prompt': 'Authorized public.facts', 'few_shots': []}
    with patch.object(executor, 'build_nl2sql_context', return_value=payload), \
         patch.object(executor, '_auto_curate'):
        yield payload


def execute(sql, *args, **kwargs):
    with sqlite3.connect(':memory:') as connection:
        connection.execute("ATTACH DATABASE ':memory:' AS public")
        connection.execute('CREATE TABLE public.facts(id INT, amount REAL, total REAL, category TEXT)')
        connection.executemany('INSERT INTO public.facts VALUES(?,?,?,?)',
                               [(1, 1, 2, 'a'), (2, 9, 18, 'a'), (3, 100, 100, 'b'), (4, 0, 0, 'z')])
        rows = connection.execute(sql).fetchall()
        return json.dumps({'status': 'ok', 'data': rows})


def test_real_entrypoint_executes_registered_formula_with_requested_population(product):
    original = copy.deepcopy(product['registered_metrics'])
    sql = "SELECT GDA_METRIC('selected_share') AS answer FROM public.facts f WHERE category='a'"
    with patch.object(executor, '_generate_gemma_sql', return_value=sql), \
         patch.object(executor, '_execute_for_engine', side_effect=execute):
        result = json.loads(executor.run_nl2semantic2sql('Percentage for selected category a'))
    assert result['status'] == 'ok'
    assert result['execution']['data'] == [[50.0]]
    assert 'GDA_METRIC' not in result['sql']
    assert result['metric_compilation']['bindings'][0]['semantic_contract']['row_grain'] == 'One observation'
    assert product['registered_metrics'] == original


@pytest.mark.parametrize('sql,reason', [
    ("SELECT GDA_METRIC('missing') FROM public.facts", 'metric_name_unavailable_or_ambiguous'),
    ("SELECT GDA_METRIC('selected_share') FROM public.facts a JOIN public.facts b ON a.id=b.id", 'metric_requires_one_local_source_binding'),
])
def test_bad_binding_is_rejected_before_database_call(product, sql, reason):
    with patch.object(executor, '_generate_gemma_sql', return_value=sql), \
         patch.object(executor, '_execute_for_engine') as db:
        result = json.loads(executor.run_nl2semantic2sql('Percentage'))
    assert result['status'] == 'rejected'
    assert result['error'] == 'semantic_contract:' + reason
    db.assert_not_called()


def test_disabled_compiler_does_not_send_a_macro_to_database(product, monkeypatch):
    monkeypatch.setenv('GDA_NL2SQL_METRIC_COMPILATION', '0')
    with patch.object(executor, '_generate_gemma_sql', return_value="SELECT GDA_METRIC('selected_share') FROM public.facts"), \
         patch.object(executor, '_execute_for_engine') as db:
        result = json.loads(executor.run_nl2semantic2sql('Percentage'))
    assert result['error'] == 'semantic_contract:metric_compilation_disabled'
    db.assert_not_called()


def test_execution_retry_compiles_new_slot_before_next_execution(product):
    def retrying_execute(sql, *a, **kw):
        if retrying_execute.first:
            retrying_execute.first = False
            return '{"status":"error","error":"temporary failure"}'
        return execute(sql)
    retrying_execute.first = True
    with patch.object(executor, '_generate_gemma_sql', return_value='SELECT amount FROM public.facts'), \
         patch.object(executor, '_retry_with_llm', return_value="SELECT GDA_METRIC('selected_share') FROM public.facts WHERE category='a'"), \
         patch.object(executor, '_execute_for_engine', side_effect=retrying_execute) as db:
        result = json.loads(executor.run_nl2semantic2sql('Percentage for selected category a'))
    assert result['status'] == 'ok'
    assert db.call_count == 2
    assert result['execution']['data'] == [[50.0]]
    assert result['metric_compilation']['status'] == 'compiled'


def test_removed_authorized_input_rejects_stale_metric_snapshot(product):
    product['candidate_tables'][0]['columns'] = [c for c in product['candidate_tables'][0]['columns'] if c['column_name'] != 'total']
    with patch.object(executor, '_generate_gemma_sql', return_value="SELECT GDA_METRIC('selected_share') FROM public.facts"), \
         patch.object(executor, '_execute_for_engine') as db:
        result = json.loads(executor.run_nl2semantic2sql('Percentage'))
    assert result['error'] == 'semantic_contract:metric_formula_outside_source_scope'
    db.assert_not_called()


def test_registry_outage_is_explicit_and_no_model_is_called(product):
    with patch.object(executor, 'build_nl2sql_context', side_effect=MetricCatalogUnavailable('metric_catalog_unavailable')), \
         patch.object(executor, '_generate_gemma_sql') as llm, \
         patch.object(executor, '_execute_for_engine') as db:
        result = json.loads(executor.run_nl2semantic2sql('Percentage'))
    assert result['error'] == 'semantic_contract:metric_catalog_unavailable'
    llm.assert_not_called()
    db.assert_not_called()


def test_postprocessor_cannot_reintroduce_an_uncompiled_slot(product):
    with patch.object(executor, '_generate_gemma_sql', return_value='SELECT amount FROM public.facts'), \
         patch.object(executor, 'postprocess_sql', return_value=SimpleNamespace(
             sql="SELECT GDA_METRIC('selected_share') FROM public.facts", rejected=False, corrections=[])), \
         patch.object(executor, '_execute_for_engine') as db:
        result = json.loads(executor.run_nl2semantic2sql('Percentage'))
    assert result['status'] == 'rejected'
    assert 'uncompiled_semantic_metric' in result['error']
    db.assert_not_called()


def test_optional_annotation_does_not_filter_product_result(product, monkeypatch):
    monkeypatch.setenv('GDA_NL2SQL_CONDITION_ROLES', '1')
    sql = "SELECT id, CASE WHEN category='Active' THEN 'yes' ELSE 'no' END FROM public.facts WHERE category='Active' ORDER BY id"
    with patch.object(executor, '_generate_gemma_sql', return_value=sql), \
         patch.object(executor, '_execute_for_engine', side_effect=execute):
        result = json.loads(executor.run_nl2semantic2sql('List all observation IDs and mark whether category is Active.'))
    assert result['status'] == 'ok'
    assert result['execution']['data'] == [[1, 'no'], [2, 'no'], [3, 'no'], [4, 'no']]
    assert len(result['condition_roles']) == 1


def test_execution_retry_cannot_reintroduce_optional_marker_filter(product, monkeypatch):
    monkeypatch.setenv('GDA_NL2SQL_CONDITION_ROLES', '1')
    sql = "SELECT id, CASE WHEN category='Active' THEN 'yes' ELSE 'no' END FROM public.facts WHERE category='Active' ORDER BY id"
    calls = []
    def first_fails(statement, *a, **kw):
        calls.append(statement)
        return '{"status":"error","error":"temporary failure"}' if len(calls) == 1 else execute(statement)
    with patch.object(executor, '_generate_gemma_sql', return_value=sql), \
         patch.object(executor, '_retry_with_llm', return_value=sql), \
         patch.object(executor, '_execute_for_engine', side_effect=first_fails):
        result = json.loads(executor.run_nl2semantic2sql('List all observation IDs and mark whether category is Active.'))
    assert result['status'] == 'ok'
    assert len(calls) == 2
    assert result['execution']['data'] == [[1, 'no'], [2, 'no'], [3, 'no'], [4, 'no']]
    assert len(result['condition_roles']) == 1

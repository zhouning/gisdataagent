"""No model/network calls: prove admission bounds at the actual transport."""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace as NS

import pytest

from data_agent.llm_call_budget import BudgetDenied, CallBudget, budget_question, use_budget
from data_agent.openai_compatible_llm import OpenAICompatibleLLMConfig, LLMServiceError, chat_completion


def policy(**changes):
    return dict({
        'run_id': 'offline-test', 'provider': 'gemini', 'model': 'fixture-model',
        'base_url': 'https://model.invalid/v1', 'max_calls': 3,
        'max_calls_per_question': 2, 'max_output_tokens_per_call': 100,
        'max_total_output_tokens': 300, 'max_request_bytes': 4096,
        'max_cost_usd': '0.03', 'cost_ceiling_per_call_usd': '0.01',
        'pricing_reference': 'https://pricing.invalid/fixture',
        'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }, **changes)


def config():
    return OpenAICompatibleLLMConfig(provider='gemini', model='fixture-model',
        base_url='https://model.invalid/v1', api_key='SECRET-NEVER-STORE', timeout_seconds=60)


def fake_factory(calls, error=None):
    def factory(**kwargs):
        assert kwargs['max_retries'] == 0
        def create(**request):
            calls.append(request)
            if error:
                raise error
            return NS(id='fixture', model='fixture-model',
                choices=[NS(message=NS(content='SELECT 1'), finish_reason='stop')],
                usage=NS(prompt_tokens=5, completion_tokens=3, total_tokens=8))
        return NS(chat=NS(completions=NS(create=create)))
    return factory


def invoke(budget, calls, question='q1', error=None):
    with use_budget(budget), budget_question(question):
        return chat_completion(system_prompt='system', user_prompt='PRIVATE-PROMPT',
            config=config(), max_tokens=100, client_factory=fake_factory(calls, error))


def process_reserve(args):
    ledger, p, identity = args
    budget = CallBudget(ledger, p)
    try:
        with budget_question(identity):
            budget.reserve(config(), {'max_tokens': 100})
        return True
    except BudgetDenied:
        return False


def test_question_and_batch_limits_block_before_transport_and_survive_restart(tmp_path):
    p = policy()
    budget = CallBudget(tmp_path/'ledger.sqlite', p)
    calls = []
    _, evidence = invoke(budget, calls)
    assert evidence['budget_reservation']['reserved_usd_micros'] == 10000
    invoke(budget, calls)
    with pytest.raises(BudgetDenied, match='question_call_limit'):
        invoke(budget, calls)
    restored = CallBudget(tmp_path/'ledger.sqlite', p)
    invoke(restored, calls, 'q2')
    with pytest.raises(BudgetDenied, match='budget_call_limit'):
        invoke(restored, calls, 'q3')
    assert len(calls) == 3
    assert restored.snapshot()['reserved_cost_usd'] == '0.03'
    content = (tmp_path/'ledger.sqlite').read_bytes()
    assert b'SECRET-NEVER-STORE' not in content and b'PRIVATE-PROMPT' not in content


@pytest.mark.parametrize('error,status', [(TimeoutError('offline timeout'), 'failed'),
                                         (KeyboardInterrupt(), 'interrupted')])
def test_timeout_and_cancellation_never_refund_reservations(tmp_path, error, status):
    budget = CallBudget(tmp_path/'ledger.sqlite', policy(max_calls=1))
    calls = []
    with pytest.raises((LLMServiceError, KeyboardInterrupt)):
        invoke(budget, calls, error=error)
    with pytest.raises(BudgetDenied):
        invoke(budget, calls)
    assert len(calls) == 1
    assert budget.snapshot()['statuses'] == {status: 1}


@pytest.mark.parametrize('changes,code,successful_calls', [
    ({'max_cost_usd': '0.015'}, 'budget_cost_limit', 1),
    ({'max_total_output_tokens': 150}, 'budget_total_output_limit', 1),
    ({'max_request_bytes': 10}, 'budget_request_size_limit', 0),
    ({'max_output_tokens_per_call': 10}, 'budget_output_limit', 0),
    ({'model': 'wrong-model'}, 'budget_model_or_endpoint_changed', 0),
    ({'expires_at': '2020-01-01T00:00:00+00:00'}, 'budget_expired', 0),
])
def test_each_cap_blocks_before_network(tmp_path, changes, code, successful_calls):
    budget = CallBudget(tmp_path/'ledger.sqlite', policy(**changes))
    calls = []
    for index in range(successful_calls):
        invoke(budget, calls, str(index))
    with pytest.raises(BudgetDenied, match=code):
        invoke(budget, calls, 'next')
    assert len(calls) == successful_calls


def test_requires_question_identity_and_immutable_policy(tmp_path):
    p = policy()
    budget = CallBudget(tmp_path/'ledger.sqlite', p)
    calls = []
    with use_budget(budget), pytest.raises(BudgetDenied, match='question_identity_required'):
        chat_completion(system_prompt='', user_prompt='', config=config(), max_tokens=1,
                        client_factory=fake_factory(calls))
    with pytest.raises(BudgetDenied, match='policy_changed'):
        CallBudget(tmp_path/'ledger.sqlite', dict(p, max_calls=100))
    assert not calls


def test_parallel_workers_cannot_overbook(tmp_path):
    p = policy(max_calls=4, max_total_output_tokens=400, max_cost_usd='0.04')
    ledger = tmp_path/'ledger.sqlite'
    CallBudget(ledger, p)
    def worker(n):
        budget = CallBudget(ledger, p)
        try:
            invoke(budget, [], str(n))
            return True
        except BudgetDenied:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(worker, range(16))) == 4
    assert CallBudget(ledger, p).snapshot()['reserved_calls'] == 4


def test_reserved_crashed_attempt_still_counts_on_reopen(tmp_path):
    p = policy(max_calls=1)
    budget = CallBudget(tmp_path/'ledger.sqlite', p)
    with budget_question('q1'):
        budget.reserve(config(), {'max_tokens':100})
    restored = CallBudget(tmp_path/'ledger.sqlite', p)
    with pytest.raises(BudgetDenied, match='call_limit'):
        invoke(restored, [])
    assert restored.snapshot()['statuses'] == {'reserved': 1}


def test_separate_processes_share_atomic_admission(tmp_path):
    p = policy(max_calls=2)
    ledger = tmp_path/'ledger.sqlite'
    CallBudget(ledger, p)
    with ProcessPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(process_reserve, [(ledger,p,str(n)) for n in range(6)])) == 2
    assert CallBudget(ledger,p).snapshot()['reserved_calls'] == 2


def test_generation_retries_and_followup_repairs_share_one_budget(monkeypatch, tmp_path):
    from data_agent import nl2sql_executor as executor
    from data_agent import openai_compatible_llm as transport
    from data_agent.user_context import current_nl2sql_llm_calls
    budget = CallBudget(tmp_path/'ledger.sqlite',policy())
    monkeypatch.setenv('GDA_LLM_PROVIDER','gemini')
    monkeypatch.setenv('GDA_NL2SQL_GENERATION_RETRIES','5')
    monkeypatch.setenv('GDA_NL2SQL_GENERATION_DEADLINE_SECONDS','0')
    monkeypatch.setattr(transport.OpenAICompatibleLLMConfig,'from_env',config)
    monkeypatch.setattr(executor,'generation_token_budget',lambda *a:100)
    monkeypatch.setattr(executor,'_generation_retry_delay',lambda *a:0)
    actual = transport.chat_completion
    calls=[]
    def fail(**kwargs):
        return actual(**kwargs,client_factory=fake_factory(calls,TimeoutError('synthetic')))
    monkeypatch.setattr(transport,'chat_completion',fail)
    token = current_nl2sql_llm_calls.set([])
    try:
        with use_budget(budget),budget_question('same-question'):
            with pytest.raises(BudgetDenied,match='question_call_limit'):
                executor._generate_gemma_sql('question')
            with pytest.raises(BudgetDenied,match='question_call_limit'):
                executor._generate_gemma_sql('repair')
        assert len(calls)==2
        assert len(current_nl2sql_llm_calls.get())==2
    finally:
        current_nl2sql_llm_calls.reset(token)


def test_direct_http_cannot_send_after_budget_exhausted(monkeypatch,tmp_path):
    import httpx
    budget=CallBudget(tmp_path/'ledger.sqlite',policy(max_calls=1))
    invoke(budget,[])
    monkeypatch.setattr(httpx,'Client',lambda **kw:pytest.fail('HTTP must not be constructed'))
    with use_budget(budget),budget_question('other'),pytest.raises(BudgetDenied):
        chat_completion(system_prompt='s',user_prompt='q',config=config(),max_tokens=100)


def test_legacy_transport_cannot_bypass_active_budget(tmp_path):
    from data_agent import nl2sql_executor as executor
    with use_budget(CallBudget(tmp_path/'ledger.sqlite',policy())),budget_question('q'):
        with pytest.raises(BudgetDenied,match='unsupported_legacy_transport'):
            executor._generate_gemma_sql('question',model_name='legacy-model')


def test_evaluation_resume_cannot_reset_budget_by_changing_ledger(tmp_path):
    from data_agent.llm_call_budget import evaluation_budget
    p=policy()
    out=tmp_path/'run'
    ledger=tmp_path/'ledger.sqlite'
    invoke(evaluation_budget(out,ledger,p),[])
    assert evaluation_budget(out,ledger,p).snapshot()['reserved_calls']==1
    with pytest.raises(BudgetDenied,match='resume_binding'):
        evaluation_budget(out,tmp_path/'other.sqlite',p)
    ledger.rename(tmp_path/'archived.sqlite')
    with pytest.raises(BudgetDenied,match='ledger_missing'):
        evaluation_budget(out,ledger,p)


def test_budget_cannot_relabel_historical_unbudgeted_run(tmp_path):
    from data_agent.llm_call_budget import evaluation_budget
    (tmp_path/'records.jsonl').write_text('{}\n')
    with pytest.raises(BudgetDenied,match='existing_unbudgeted_run'):
        evaluation_budget(tmp_path,tmp_path/'ledger.sqlite',policy())


def test_in_memory_policy_mutation_cannot_increase_limit(tmp_path):
    budget=CallBudget(tmp_path/'ledger.sqlite',policy(max_calls=1))
    invoke(budget,[])
    budget.policy['max_calls']=100
    with pytest.raises(BudgetDenied,match='policy_changed'):
        invoke(budget,[])


def test_stopped_batch_has_no_completion_or_accuracy_claim(monkeypatch,tmp_path):
    from scripts.nl2sql_bench_bird import eval_product_source as evaluator
    bench=tmp_path/'benchmark.json'
    bench.write_text(json.dumps([{'question_id':1,'question':'q','db_id':'fixture'}]))
    policy_file=tmp_path/'policy.json'
    policy_file.write_text(json.dumps(policy()))
    out=tmp_path/'run'
    monkeypatch.setattr(evaluator.OpenAICompatibleLLMConfig,'from_env',config)
    def stop(args,questions):
        error=BudgetDenied('budget_call_limit')
        error.evidence={'question_id':1,'llm_calls':[]}
        raise error
    monkeypatch.setattr(evaluator,'_run_evaluation',stop)
    monkeypatch.setattr('sys.argv',['eval_product_source.py','--benchmark',str(bench),
        '--out-dir',str(out),'--budget-policy',str(policy_file),'--budget-ledger',str(tmp_path/'ledger.sqlite')])
    with pytest.raises(BudgetDenied):
        evaluator.main()
    assert not (out/'completion.json').exists()
    assert not (out/'report.json').exists()
    result=json.loads((out/'stopped.json').read_text())
    assert result['planned_n']==1 and result['is_complete_accuracy_result'] is False
    assert result['interrupted_question']['question_id']==1


@pytest.mark.parametrize('changes', [{'max_calls':True}, {'max_cost_usd':'NaN'},
    {'cost_ceiling_per_call_usd':'0'}, {'pricing_reference':'https://user:secret@model.invalid'},
    {'expires_at':'2028-01-01'}, {'unrecognized':'field'}])
def test_invalid_policies_fail_closed(tmp_path, changes):
    with pytest.raises(BudgetDenied):
        CallBudget(tmp_path/'ledger.sqlite', policy(**changes))


def test_missing_policy_cli_stops_before_manifest_or_model(monkeypatch, capsys):
    from scripts.nl2sql_bench_bird import eval_product_source as evaluator
    monkeypatch.setattr(evaluator.OpenAICompatibleLLMConfig, 'from_env', config)
    monkeypatch.setattr(evaluator, 'run_manifest', lambda *a: pytest.fail('preflight should not run'))
    monkeypatch.setattr('sys.argv', ['eval_product_source.py'])
    with pytest.raises(SystemExit) as exc:
        evaluator.main()
    assert exc.value.code == 2
    assert 'requires --budget-policy' in capsys.readouterr().err


def test_budget_denial_caught_by_product_still_stops_evaluation(monkeypatch, tmp_path):
    from scripts.nl2sql_bench_bird import eval_product_source as evaluator
    monkeypatch.setattr(evaluator, 'registered_database', lambda *a: None)
    budget = CallBudget(tmp_path/'ledger.sqlite', policy(max_calls=1))
    invoke(budget, [], 'prior')
    def product(*a, **kw):
        try:
            invoke(budget, [], 'new')
        except BudgetDenied:
            return json.dumps({'status':'error'})
    monkeypatch.setattr(evaluator, 'run_nl2semantic2sql', product)
    with use_budget(budget), pytest.raises(BudgetDenied, match='call_limit'):
        evaluator.evaluate_one({'question_id':7,'question':'test','db_id':'fixture'}, None)


@pytest.mark.parametrize('fault,expected', [('schema','answer_plan_response_schema'),
                                          ('transport','model_transport_failure'),
                                          ('query_route','query_route_contract')])
def test_integration_fault_saves_first_result_and_stops_before_next_question(monkeypatch, tmp_path, fault, expected):
    from scripts.nl2sql_bench_bird import eval_product_source as evaluator
    benchmark=tmp_path/'benchmark.json'
    benchmark.write_text(json.dumps([{'question_id':1}, {'question_id':2}]))
    policy_file=tmp_path/'policy.json'
    policy_file.write_text(json.dumps(policy()))
    out=tmp_path/'run'
    monkeypatch.setattr(evaluator.OpenAICompatibleLLMConfig,'from_env',config)
    from data_agent.nl2sql_route_policy import resolve_bird_query_policy
    settings = {'GDA_NL2SQL_QUERY_PROFILE': 'registered_ir_strict'}
    manifest = {'deployed_model': {}, 'settings': settings,
                'query_policy': resolve_bird_query_policy(settings).evidence()}
    monkeypatch.setattr(evaluator,'run_manifest',lambda *a: manifest)
    monkeypatch.setattr(evaluator,'RemoteBirdRuntime',lambda *a: None)
    monkeypatch.setattr(evaluator,'model_call_errors',lambda *a: [])
    for name in ['BIRD_PG_HOST','BIRD_PG_USER','BIRD_PG_PASSWORD']:
        monkeypatch.setenv(name,'offline')
    questions=[]
    def evaluate(question,runtime):
        questions.append(question['question_id'])
        return {'question_id':question['question_id'],'db_id':'fixture','difficulty':'simple',
                'correct':0,'failure_category':'generation_or_execution_error','latency_ms':1,
                'prediction_status':'error','gold_status':'ok',
                'query_policy': {} if fault=='query_route' else manifest['query_policy'],
                'answer_plan': {'status':'rejected','rejections':[{'kind':'response_schema'}]} if fault=='schema' else {},
                'llm_calls':[{'status':'failed'}] if fault=='transport' else []}
    monkeypatch.setattr(evaluator,'evaluate_one',evaluate)
    monkeypatch.setattr('sys.argv',['eval_product_source.py','--benchmark',str(benchmark),
        '--out-dir',str(out),'--budget-policy',str(policy_file),'--budget-ledger',str(tmp_path/'ledger.sqlite')])
    with pytest.raises(evaluator.ProductIntegrationFault,match=expected):
        evaluator.main()
    assert questions == [1]
    assert len((out/'records.jsonl').read_text().splitlines()) == 1
    assert not (out/'completion.json').exists()
    stopped=json.loads((out/'stopped.json').read_text())
    assert stopped['reason']==expected and stopped['planned_n']==2
    assert stopped['is_complete_accuracy_result'] is False
    report=json.loads((out/'report.json').read_text())
    assert report['is_complete_accuracy_result'] is False and report['planned_n']==2
    # Resuming cannot hop over the saved fault and dispatch question two.
    with pytest.raises(evaluator.ProductIntegrationFault,match=expected):
        evaluator.main()
    assert questions == [1]


def test_semantic_mistakes_and_wrong_results_are_not_integration_faults():
    from scripts.nl2sql_bench_bird import eval_product_source as evaluator
    assert evaluator.integration_fault({'failure_category':'wrong_result'}) is None
    assert evaluator.integration_fault({'answer_plan':{'status':'rejected',
        'rejections':[{'kind':'semantic_contract'}]}}) is None

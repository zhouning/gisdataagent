"""Quick smoke test the hard-timeout wrapper."""
import sys, os
sys.path.insert(0, 'D:/adk')
sys.path.insert(0, 'D:/adk/scripts/nl2sql_bench_cq')
from dotenv import load_dotenv
load_dotenv('D:/adk/data_agent/.env', override=True)
sys.stdout.reconfigure(encoding='utf-8')

from run_cq_eval import _init_runtime, baseline_generate_family_aware
_init_runtime()

# (1) Gemini path
print('--- Gemini 2.5-flash ---')
r = baseline_generate_family_aware('how many buildings have 40+ floors', 'gemini-2.5-flash')
print('status:', r['status'], 'tokens:', r['tokens'])
print('sql:', r['sql'][:120])

# (2) Hard-timeout via small env override
os.environ['BASELINE_HARD_TIMEOUT'] = '2'
print('\n--- Hard timeout test (BASELINE_HARD_TIMEOUT=2s, expect hard_timeout) ---')
r = baseline_generate_family_aware('how many buildings', 'gemini-2.5-flash')
print('status:', r['status'])
print('error:', r.get('error', '')[:200])

# Reset
os.environ['BASELINE_HARD_TIMEOUT'] = '180'

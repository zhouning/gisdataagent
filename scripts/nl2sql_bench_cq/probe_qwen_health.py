"""Probe Qwen DashScope endpoint health in real time."""
import sys, time
sys.path.insert(0, 'D:/adk')
sys.path.insert(0, 'D:/adk/scripts/nl2sql_bench_cq')
from dotenv import load_dotenv
load_dotenv('D:/adk/data_agent/.env', override=True)
sys.stdout.reconfigure(encoding='utf-8')

from data_agent.model_gateway import create_model
import litellm

PROMPT = "Reply with just SELECT 1; no markdown."

for name in ('qwen3.6-flash', 'qwen3.6-plus'):
    print(f'\n=== {name} ===')
    t0 = time.time()
    try:
        adk_model = create_model(name)
        resp = litellm.completion(
            model=adk_model.model,
            messages=[{'role': 'user', 'content': PROMPT}],
            temperature=0.0,
            timeout=30,
            extra_body=(adk_model._additional_args or {}).get('extra_body'),
        )
        dur = time.time() - t0
        text = (resp.choices[0].message.content or '').strip()
        print(f'  OK in {dur:.1f}s')
        print(f'  text: {text[:200]!r}')
        usage = getattr(resp, 'usage', None)
        if usage:
            print(f'  prompt_tokens={getattr(usage, "prompt_tokens", "?")} '
                  f'completion_tokens={getattr(usage, "completion_tokens", "?")}')
    except Exception as e:
        dur = time.time() - t0
        print(f'  FAIL in {dur:.1f}s')
        print(f'  {type(e).__name__}: {str(e)[:500]}')

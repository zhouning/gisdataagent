import asyncio
import os
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from data_agent.agent import planner_agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig
from google.genai import types
from data_agent.app import _context_cache_config
from google.adk.apps import App
from data_agent.plugins import build_plugin_stack

async def test_query(use_cache):
    print(f"\n--- Testing with Context Cache = {use_cache} ---")
    try:
        from google.adk.sessions.database import DatabaseSessionService
        session_service = DatabaseSessionService()
        print("Using DatabaseSessionService")
    except Exception:
        session_service = InMemorySessionService()
        print("Using InMemorySessionService")
    plugins = build_plugin_stack()
    
    if use_cache and _context_cache_config:
        app = App(
            name="test_app",
            root_agent=planner_agent,
            context_cache_config=_context_cache_config,
            plugins=plugins
        )
        runner = Runner(app=app, session_service=session_service, auto_create_session=True)
    else:
        runner = Runner(
            agent=planner_agent, 
            app_name="test_app",
            session_service=session_service,
            plugins=plugins,
            auto_create_session=True
        )
        
    query = "请把重庆市璧山区福禄镇的行政区范围加载到地图上"
    content = types.Content(role='user', parts=[types.Part(text=query)])
    run_config = RunConfig(max_llm_calls=50)
    
    print("Sending query...")
    events = runner.run_async(user_id="test", session_id=f"test_{time.time()}", new_message=content, run_config=run_config)
    
    async for event in events:
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text, end="", flush=True)
                if part.function_call:
                    print(f"\n[Tool Call]: {part.function_call.name}")
                if part.function_response:
                    print(f"\n[Tool Result]: {part.function_response.name} completed.")
        if getattr(event, "is_final_response", lambda: False)():
            print("\nFinal response received.")
    print("Done.")

if __name__ == "__main__":
    from data_agent.cli import _load_env
    _load_env()
    # Test without cache
    asyncio.run(test_query(False))
    # Test with cache
    asyncio.run(test_query(True))

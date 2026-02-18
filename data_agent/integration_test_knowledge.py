import asyncio
import os
import sys
from dotenv import load_dotenv

# Load environment variables from the folder where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(script_dir, '.env'))

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Correct way to import from the same package when running as a module
try:
    from .agent import knowledge_agent
except ImportError:
    # Fallback for direct execution
    import agent
    knowledge_agent = agent.knowledge_agent

async def run_integration_test():
    print("--- Starting Vertex AI Search Integration Test ---")
    
    APP_NAME = "test_knowledge_integration"
    USER_ID = "tester"
    SESSION_ID = "session_001"
    
    session_service = InMemorySessionService()
    await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    
    runner = Runner(agent=knowledge_agent, app_name=APP_NAME, session_service=session_service)
    
    # Test Query
    test_query = "Please explain the theoretical basis for land use spatial swap between forest and farmland, focusing on how to balance ecological security and farmland protection redline based on the latest research in the knowledge store."
    
    print(f"Query: {test_query}\n")
    
    # Run Agent
    content = types.Content(role='user', parts=[types.Part(text=test_query)])
    
    print("Wait: Retrieving knowledge and generating response...")
    events = runner.run_async(user_id=USER_ID, session_id=SESSION_ID, new_message=content)
    
    final_text = ""
    async for event in events:
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text, end="", flush=True)
                    final_text += part.text
        
        if event.is_final_response():
            print("\n\nResponse complete.")

    # Validation
    print("\n--- Validating Output Quality ---")
    
    quality_checks = {
        "LaTeX formulas": "$" in final_text,
        "Markdown table": "|" in final_text and "---" in final_text,
        "Citations": "[" in final_text and "]" in final_text
    }

    for check, passed in quality_checks.items():
        status = "[PASS]" if passed else "[WARN]"
        print(f"{status} {check} detected.")

if __name__ == "__main__":
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        print("Error: GOOGLE_CLOUD_PROJECT not found in .env")
    else:
        try:
            asyncio.run(run_integration_test())
        except Exception as e:
            import traceback
            print(f"\nExecution failed: {str(e)}")
            traceback.print_exc()

import asyncio
import os
import sys
import geopandas as gpd
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Import the root agent
try:
    from data_agent.agent import root_agent
except ImportError:
    import agent
    root_agent = agent.root_agent

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Test Data Path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_SHP_PATH = os.path.abspath(os.path.join(BASE_DIR, "斑竹村10000.shp"))

async def run_end_to_end_pipeline():
    print("==================================================")
    print("   Starting End-to-End Data Pipeline Test")
    print("==================================================")
    print(f"Input Data: {TEST_SHP_PATH}")
    
    # 1. Setup Runner
    APP_NAME = "pipeline_test"
    USER_ID = "admin"
    SESSION_ID = "e2e_session_001"
    
    session_service = InMemorySessionService()
    await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)
    
    # 2. Construct User Query
    user_query = f"请对该区域的数据进行完整的空间布局优化分析：{TEST_SHP_PATH}。首先请检索相关的林耕置换理论。"
    
    content = types.Content(role='user', parts=[types.Part(text=user_query)])
    
    # 3. Execution Loop
    print("\nPipeline running... (This may take a minute)\n")
    
    full_response_log = []
    
    # Run async runner
    events = runner.run_async(user_id=USER_ID, session_id=SESSION_ID, new_message=content)
    
    async for event in events:
        # Capture and print output in real-time
        if event.content and event.content.parts:
            for part in event.content.parts:
                # Text output
                if part.text:
                    print(part.text, end="", flush=True)
                    full_response_log.append(part.text)
                
                # Tool calls
                if part.function_call:
                    print(f"\n[Tool Call]: {part.function_call.name}")
                
                # Tool responses
                if part.function_response:
                    print(f"\n[Tool Result]: {part.function_response.name} completed.")

        if event.is_final_response():
            print("\n\nPipeline execution finished.")

    # 4. Final Validation
    print("\n==================================================")
    print("   Verification Report")
    print("==================================================")
    
    full_text = "".join(full_response_log)
    
    checks = {
        "Theory (LaTeX)": "$" in full_text,
        "Data Health": "数据概览" in full_text or "Data Overview" in full_text,
        "FFI Calculation": "FFI" in full_text,
        "DRL Optimization": "Optimization Complete" in full_text or "布局优化" in full_text,
        "Visualization": ".png" in full_text,
        "Policy Advice": "建议" in full_text or "Policy" in full_text
    }
    
    all_passed = True
    for name, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"{status} - {name}")
        if not passed: all_passed = False
        
    if all_passed:
        print("\nSUCCESS: All pipeline stages executed correctly!")
    else:
        print("\nWARNING: Some stages may have failed or output unexpected content.")

if __name__ == "__main__":
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        print("Error: GOOGLE_CLOUD_PROJECT not found. Please check .env")
    else:
        try:
            asyncio.run(run_end_to_end_pipeline())
        except Exception as e:
            print(f"\nExecution Failed: {str(e)}")
            import traceback
            traceback.print_exc()

import chainlit as cl
import sys
import os
import re
import asyncio
from typing import List, Dict
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 🟢 CRITICAL FIX: Load environment variables explicitly
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"✅ Loaded environment from {env_path}")
else:
    print("⚠️ Warning: .env file not found in data_agent directory")

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Import the root agent
try:
    from data_agent.agent import root_agent
except ImportError:
    import agent
    root_agent = agent.root_agent

# Initialize Session Service (Global for this simple app)
session_service = InMemorySessionService()

def extract_file_paths(text: str) -> List[Dict[str, str]]:
    """Extract file paths from text and determine their type."""
    artifacts = []
    pattern = r'(?:[a-zA-Z]:\\|/)[^<>:"|?*]+\.(png|html|shp|zip|csv)'
    matches = re.finditer(pattern, text, re.IGNORECASE)
    for match in matches:
        path = match.group(0)
        ext = match.group(1).lower()
        if os.path.exists(path):
            artifacts.append({"path": path, "type": ext})
    return artifacts

@cl.on_chat_start
async def start():
    """Initialize the session."""
    user_id = "user"
    session_id = cl.user_session.get("id")
    await session_service.create_session(app_name="data_agent_ui", user_id=user_id, session_id=session_id)
    cl.user_session.set("user_id", user_id)
    cl.user_session.set("session_id", session_id)
    
    await cl.Message(
        content="👋 **欢迎使用 GIS 智能分析平台**\n\n请上传数据文件（SHP/CSV）或直接输入文件路径开始分析。\n*(系统已就绪，环境配置检测通过)*",
        author="System"
    ).send()

@cl.on_message
async def main(message: cl.Message):
    """Handle user message."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    
    # Check credentials before running
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        await cl.Message(content="❌ Error: `GOOGLE_CLOUD_PROJECT` environment variable not found. Please check .env file.").send()
        return

    runner = Runner(agent=root_agent, app_name="data_agent_ui", session_service=session_service)
    content = types.Content(role='user', parts=[types.Part(text=message.content)])
    
    final_msg = cl.Message(content="")
    await final_msg.send()
    
    shown_artifacts = set()
    current_step = None
    
    try:
        # Run ADK Stream
        events = runner.run_async(user_id=user_id, session_id=session_id, new_message=content)
        
        async for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    
                    # 1. Text Output
                    if part.text:
                        await final_msg.stream_token(part.text)
                        
                        found = extract_file_paths(part.text)
                        elements = []
                        for artifact in found:
                            path = artifact['path']
                            if path in shown_artifacts: continue
                            
                            name = os.path.basename(path)
                            if artifact['type'] == 'png':
                                elements.append(cl.Image(path=path, name=name, display="inline"))
                                shown_artifacts.add(path)
                            elif artifact['type'] == 'html':
                                elements.append(cl.File(path=path, name=name))
                                shown_artifacts.add(path)
                        
                        if elements:
                            await cl.Message(content=f"📂 生成了新的分析资源：", elements=elements).send()

                    # 2. Tool Calls
                    if part.function_call:
                        if current_step: await current_step.update()
                        current_step = cl.Step(name=part.function_call.name, type="tool")
                        current_step.input = str(part.function_call.args)
                        await current_step.send()
                    
                    # 3. Tool Responses
                    if part.function_response:
                        if current_step:
                            current_step.output = "✅ Completed"
                            await current_step.update()
                            current_step = None

        await final_msg.update()
        
    except Exception as e:
        error_msg = f"❌ 运行时错误: {str(e)}"
        print(error_msg)
        await cl.Message(content=error_msg).send()

import chainlit as cl
import sys
import os
import re
import asyncio
import time
import zipfile
import shutil
from typing import List, Dict, Optional
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Import agent and report generator
try:
    from data_agent.agent import root_agent
    from data_agent.report_generator import generate_word_report
except ImportError:
    import agent
    import report_generator
    root_agent = agent.root_agent
    generate_word_report = report_generator.generate_word_report

session_service = InMemorySessionService()

# Directory for uploads
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

def extract_file_paths(text: str) -> List[Dict[str, str]]:
    """Extract file paths from text."""
    artifacts = []
    pattern = r'(?:[a-zA-Z]:\\|/)[^<>:"|?*]+\.(png|html|shp|zip|csv)'
    matches = re.finditer(pattern, text, re.IGNORECASE)
    for match in matches:
        path = match.group(0)
        ext = match.group(1).lower()
        if os.path.exists(path):
            artifacts.append({"path": path, "type": ext})
    return artifacts

def handle_uploaded_file(element) -> Optional[str]:
    """
    Process uploaded file.
    - If Zip: Extract and find .shp
    - If other: Return path
    """
    if not element.path:
        return None
        
    # Copy to our upload dir to ensure persistence/access
    # Chainlit stores in temp, let's keep it clean
    dest_path = os.path.join(UPLOAD_DIR, element.name)
    shutil.copy(element.path, dest_path)
    
    ext = os.path.splitext(dest_path)[1].lower()
    
    if ext == '.zip':
        # Unzip
        extract_dir = os.path.join(UPLOAD_DIR, os.path.splitext(element.name)[0])
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(dest_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # Find shapefile
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    if file.lower().endswith('.shp'):
                        return os.path.abspath(os.path.join(root, file))
            
            return None # No shapefile found
        except Exception as e:
            print(f"Zip extraction failed: {e}")
            return None
            
    return os.path.abspath(dest_path)

@cl.on_chat_start
async def start():
    """Initialize session."""
    user_id = "user"
    session_id = cl.user_session.get("id")
    await session_service.create_session(app_name="data_agent_ui", user_id=user_id, session_id=session_id)
    cl.user_session.set("user_id", user_id)
    cl.user_session.set("session_id", session_id)

@cl.on_message
async def main(message: cl.Message):
    """Handle user message with File Upload Support."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        await cl.Message(content="❌ Error: `GOOGLE_CLOUD_PROJECT` not found.").send()
        return

    # --- 🟢 Handle File Uploads ---
    uploaded_files = []
    if message.elements:
        for element in message.elements:
            # Chainlit file uploads come as cl.File (which inherits Element)
            # Or checks mime type
            processed_path = handle_uploaded_file(element)
            if processed_path:
                uploaded_files.append(processed_path)
    
    # Construct User Prompt
    user_text = message.content
    
    if uploaded_files:
        # Append file info to the prompt transparently
        files_msg = "\n\n[System Context] 用户上传了以下文件，请优先分析这些数据："
        for f in uploaded_files:
            files_msg += f"\n- {f}"
        
        # If user didn't say anything, give a default instruction
        if not user_text.strip():
            user_text = "请对上传的数据进行完整的空间布局优化分析。"
        
        full_prompt = user_text + files_msg
        
        # Notify user in UI that file was received
        await cl.Message(content=f"✅ 已接收文件，正在解析：\n`{uploaded_files[0]}`").send()
    else:
        full_prompt = user_text

    runner = Runner(agent=root_agent, app_name="data_agent_ui", session_service=session_service)
    content = types.Content(role='user', parts=[types.Part(text=full_prompt)])
    
    # Timer & Steps
    thinking_start_time = time.time()
    thinking_step = cl.Step(name="Thinking Process", type="process")
    await thinking_step.send()
    
    final_msg = cl.Message(content="")
    shown_artifacts = set()
    current_tool_step = None
    tool_start_time = 0
    is_thinking = True
    full_response_text = ""
    
    try:
        events = runner.run_async(user_id=user_id, session_id=session_id, new_message=content)
        
        async for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    
                    # Tool Call
                    if part.function_call:
                        if current_tool_step: await current_tool_step.update()
                        tool_name = part.function_call.name
                        tool_start_time = time.time()
                        current_tool_step = cl.Step(name=tool_name, type="tool", parent_id=thinking_step.id)
                        args_str = str(part.function_call.args)
                        current_tool_step.input = args_str[:500] + "..." if len(args_str) > 500 else args_str
                        await current_tool_step.send()

                    # Tool Response
                    if part.function_response:
                        if current_tool_step:
                            duration = time.time() - tool_start_time
                            current_tool_step.name += f" ({duration:.2f}s)"
                            current_tool_step.output = "✅ Tool execution successful"
                            await current_tool_step.update()
                            current_tool_step = None

                    # Text Output
                    if part.text:
                        if is_thinking:
                            total_duration = time.time() - thinking_start_time
                            thinking_step.name = f"Thinking Process ({total_duration:.1f}s)"
                            await thinking_step.update() 
                            is_thinking = False
                            await final_msg.send() 
                        else:
                            # Update timer periodically during streaming (e.g. every token or every N tokens)
                            # This gives a 'live' feel to the total time
                            total_duration = time.time() - thinking_start_time
                            thinking_step.name = f"Thinking Process ({total_duration:.1f}s)"
                            await thinking_step.update()

                        await final_msg.stream_token(part.text)
                        full_response_text += part.text
                        
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
                            await cl.Message(content="", elements=elements).send()

        # Cleanup
        if is_thinking: 
            total_duration = time.time() - thinking_start_time
            thinking_step.name += f" ({total_duration:.2f}s)"
            await thinking_step.update()
            
        if current_tool_step: 
            duration = time.time() - tool_start_time
            current_tool_step.name += f" ({duration:.2f}s)"
            await current_tool_step.update()
            
        await final_msg.update()
        cl.user_session.set("last_response_text", full_response_text)
        
        actions = [
            cl.Action(
                name="export_report", 
                value="docx", 
                label="📄 导出 Word 报告", 
                description="将本次分析结果导出为文档",
                payload={"format": "docx"}
            )
        ]
        await cl.Message(content="分析完成。您可以下载相关文件或导出完整报告。", actions=actions).send()
        
    except Exception as e:
        err_msg = f"❌ Error: {str(e)}"
        print(err_msg)
        await cl.Message(content=err_msg).send()

@cl.action_callback("export_report")
async def on_export_report(action: cl.Action):
    text = cl.user_session.get("last_response_text")
    if not text:
        await cl.Message(content="❌ 无法获取报告内容").send()
        return
    msg = cl.Message(content="正在生成报告...")
    await msg.send()
    try:
        output_path = os.path.join(os.path.dirname(__file__), "Analysis_Report.docx")
        generate_word_report(text, output_path)
        await cl.Message(content="✅ 报告已生成：", elements=[
            cl.File(path=output_path, name="Analysis_Report.docx", display="inline")
        ]).send()
    except Exception as e:
        await cl.Message(content=f"❌ 生成失败: {str(e)}").send()

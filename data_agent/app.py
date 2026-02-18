import chainlit as cl
import sys
import os
import re
import asyncio
from typing import List, Dict
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

# Import agent
try:
    from data_agent.agent import root_agent
except ImportError:
    import agent
    root_agent = agent.root_agent

session_service = InMemorySessionService()

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

@cl.on_chat_start
async def start():
    """Initialize session."""
    user_id = "user"
    session_id = cl.user_session.get("id")
    await session_service.create_session(app_name="data_agent_ui", user_id=user_id, session_id=session_id)
    cl.user_session.set("user_id", user_id)
    cl.user_session.set("session_id", session_id)
    
    # We don't send a welcome message here because chainlit.md handles the welcome screen.
    # But we can send a "System Ready" toast if we wanted.

@cl.on_message
async def main(message: cl.Message):
    """Handle user message with Gemini-like UX."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        await cl.Message(content="❌ Error: `GOOGLE_CLOUD_PROJECT` not found.").send()
        return

    runner = Runner(agent=root_agent, app_name="data_agent_ui", session_service=session_service)
    content = types.Content(role='user', parts=[types.Part(text=message.content)])
    
    # 🌟 Gemini UX: Thinking Process Container
    # We create a parent step "Thinking Process" that will hold all tool calls.
    # It starts immediately and closes when the first text token arrives.
    thinking_step = cl.Step(name="Thinking Process", type="process")
    await thinking_step.send()
    
    # Prepare Final Message
    final_msg = cl.Message(content="")
    
    # State tracking
    shown_artifacts = set()
    current_tool_step = None
    is_thinking = True
    
    try:
        events = runner.run_async(user_id=user_id, session_id=session_id, new_message=content)
        
        async for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    
                    # --- 1. Tool Call (Sub-step inside Thinking) ---
                    if part.function_call:
                        # Create a child step nested under 'thinking_step'
                        if current_tool_step: await current_tool_step.update()
                        
                        tool_name = part.function_call.name
                        current_tool_step = cl.Step(
                            name=tool_name, 
                            type="tool", 
                            parent_id=thinking_step.id
                        )
                        # Truncate args if too long for cleaner UI
                        args_str = str(part.function_call.args)
                        current_tool_step.input = args_str[:500] + "..." if len(args_str) > 500 else args_str
                        await current_tool_step.send()

                    # --- 2. Tool Response ---
                    if part.function_response:
                        if current_tool_step:
                            # We don't show full output in UI to keep it clean, just a checkmark
                            current_tool_step.output = "✅ Tool execution successful"
                            await current_tool_step.update()
                            current_tool_step = None

                    # --- 3. Text Output (The Answer) ---
                    if part.text:
                        # Close thinking step on first text token
                        if is_thinking:
                            await thinking_step.update() # Close the step
                            is_thinking = False
                            await final_msg.send() # Start the final message stream

                        await final_msg.stream_token(part.text)
                        
                        # Real-time Artifact Rendering (The "Magic")
                        found = extract_file_paths(part.text)
                        elements = []
                        for artifact in found:
                            path = artifact['path']
                            if path in shown_artifacts: continue
                            
                            name = os.path.basename(path)
                            if artifact['type'] == 'png':
                                # Gemini-like: Inline images
                                elements.append(cl.Image(path=path, name=name, display="inline"))
                                shown_artifacts.add(path)
                            elif artifact['type'] == 'html':
                                # Provide download
                                elements.append(cl.File(path=path, name=name))
                                shown_artifacts.add(path)
                        
                        if elements:
                            # Attach elements to the final message dynamically? 
                            # Chainlit allows updating elements of an existing message?
                            # Yes, assuming we send them. Or we can send a small sub-message.
                            # For better UX, let's append to final_msg if possible, or send separate.
                            # Sending separate avoids re-rendering the whole text block.
                            await cl.Message(content="", elements=elements).send()

        # Final cleanup
        if is_thinking: await thinking_step.update()
        if current_tool_step: await current_tool_step.update()
        await final_msg.update()
        
    except Exception as e:
        err_msg = f"❌ Error: {str(e)}"
        print(err_msg)
        await cl.Message(content=err_msg).send()

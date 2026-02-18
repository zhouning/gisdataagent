# Requirements Specification: Data Agent Custom Web UI

## 1. Project Overview
The goal is to replace the generic `adk web` interface with a custom, specialized web application powered by **Chainlit**. This application will provide a rich, interactive experience for users interacting with the GIS Data Agent, featuring inline visualization of maps, charts, and data analysis reports.

## 2. User Personas
*   **Government Planner**: Needs to upload land use data and receive policy-aligned optimization reports. Prioritizes clarity and visual evidence.
*   **GIS Analyst**: Needs to inspect intermediate data products (SHP, FFI scores) and explore results interactively on a map.

## 3. User Stories
*   **US-001**: As a user, I want to chat with the agent using natural language to initiate analysis tasks.
*   **US-002**: As a user, I want to see the agent's "thinking process" (e.g., "Calculating FFI...", "Optimizing Layout...") in real-time.
*   **US-003**: As a user, I want generated static charts (PNG) to appear directly in the chat window, not just as file paths.
*   **US-004**: As a user, I want to explore optimization results on an interactive map (HTML) embedded within the chat interface.
*   **US-005**: As a user, I want to download the final result files (SHP, Reports) via clickable buttons.

## 4. Functional Requirements

### 4.1 Chat Interface
*   **Framework**: Chainlit (Python).
*   **Input**: Text input field.
*   **History**: Session-based chat history.

### 4.2 ADK Integration
*   **Runner**: Must use `google.adk.runners.Runner` to execute `data_agent.agent.root_agent`.
*   **Streaming**: Must support asynchronous streaming of text tokens from ADK to Chainlit UI.
*   **Tool Visualization**: Tool calls (e.g., `ffi`, `drl_model`) should be rendered as Chainlit "Steps" or "Nesting".

### 4.3 Artifact Rendering (The "Magic" Feature)
*   **Pattern Recognition**: The system must regex-scan the agent's textual response for file paths.
    *   `.png`: Render as `cl.Image`.
    *   `.html`: Render as `cl.Frame` (iframe) or `cl.File`.
    *   `.shp`: Render as `cl.File` (Download).
*   **Deduplication**: Ensure the same image isn't rendered multiple times if mentioned repeatedly.

## 5. Non-Functional Requirements
*   **Performance**: UI latency < 200ms. Agent response time depends on model inference but UI must remain responsive.
*   **Security**: Restrict file access to the `D:\adk` workspace. Do not expose system files.
*   **Compatibility**: Support modern browsers (Chrome, Edge).

## 6. Constraints
*   Must run in the existing Python `.venv` environment.
*   Must reuse existing `data_agent` logic without modifying core algorithms.

## 7. Gemini-like Experience (v2.0 Upgrade)
*   **Nested Thinking**: Intermediate tool calls (describe, ffi, drl) MUST be collapsed under a single parent step labeled "Thinking Process" or "Processing...", similar to Gemini's "Show work". They should not clutter the main chat unless expanded.
*   **Clean UI**: 
    -   Custom Avatar for the Agent (GIS Bot icon).
    -   Welcome Screen with "Starters" (Quick Action buttons).
    -   Removed verbose system prompts from the visible chat history.
*   **Step Logic**: 
    -   Start a "Thinking" step when the user sends a message.
    -   Update this step with sub-steps for each tool call.
    -   Close the step when the final text response begins streaming.

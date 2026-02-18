# Architecture Design: Chainlit-ADK Integration

## 1. High-Level Architecture

```mermaid
graph LR
    subgraph "Frontend (Browser)"
        UI[Chainlit UI]
    end

    subgraph "Backend (Python)"
        CL_Server[app.py (Chainlit Server)]
        ADK_Runner[ADK Runner]
        Agent[DataPipeline Agent]
    end

    subgraph "File System"
        Workspace[D:\adk]
    end

    UI -- WebSocket (User Input) --> CL_Server
    CL_Server -- run_async() --> ADK_Runner
    ADK_Runner -- Execute --> Agent
    Agent -- Read/Write --> Workspace
    ADK_Runner -- Stream Events --> CL_Server
    CL_Server -- Render Elements --> UI
```

## 2. Component Design

### 2.1 `app.py` (Main Entry)
*   **Role**: Orchestrates the chat session.
*   **Key Hooks**:
    *   `@cl.on_chat_start`: Initialize ADK Session, set up user ID.
    *   `@cl.on_message`: Receive user input, trigger ADK Runner.
*   **Event Handling**:
    *   Iterates over `runner.run_async()`.
    *   Handles `ModelResponse` (Text) -> `cl.Message.stream_token`.
    *   Handles `ToolCall` -> `cl.Step`.

### 2.2 `ArtifactHandler` (Utility Class)
*   **Role**: Parses text streams to identify and handle file paths.
*   **Logic**:
    *   Input: Streamed text chunk or accumulated message.
    *   Process: Regex match `(D:|[a-zA-Z]:)\[^<>:"/|?*]+\.(png|html|shp|zip)`.
    *   Output: `cl.Element` (Image, File, etc.).

### 2.3 `ADKAdapter` (Integration Layer)
*   **Role**: Wraps ADK `InMemorySessionService` and `Runner` to be async-friendly for Chainlit.

## 3. Data Flow

1.  **User** types: "Optimize land use for file X."
2.  **Chainlit** sends message to `app.py`.
3.  `app.py` passes message to `ADK Runner`.
4.  **Agent** thinks, calls tools (`ffi`, `drl`).
5.  `app.py` captures tool events, shows "Thinking..." step in UI.
6.  **Agent** generates chart `D:\adk\comp.png`.
7.  **Agent** responds text: "Optimization done. See [comp.png]."
8.  `app.py` detects `.png` path in text.
9.  `app.py` loads `D:\adk\comp.png`, creates `cl.Image`, sends to UI.
10. **User** sees text + rendered image.

## 4. Security Considerations
*   **Path Traversal**: Validate that all accessed files are within `BASE_DIR`.
*   **Env Vars**: Ensure `.env` is loaded safely.

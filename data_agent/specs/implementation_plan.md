# Implementation Plan

## Phase 1: Environment & Prototype (P0) - [DONE]
- [x] **Task 1.1**: Install `chainlit` dependency.
- [x] **Task 1.2**: Create `data_agent/app.py` skeleton.
- [x] **Task 1.3**: Implement basic ADK `run_async` loop within Chainlit.
- [x] **Verification**: "Hello World" chat works with ADK agent.

## Phase 2: Rich Media Integration (P1) - [DONE]
- [x] **Task 2.1**: Implement `path_extractor` regex logic.
- [x] **Task 2.2**: Implement `cl.Image` rendering for PNGs.
- [x] **Task 2.3**: Implement `cl.File` / `cl.Frame` for HTML maps.
- [x] **Verification**: Run end-to-end test, verify charts appear in chat.

## Phase 3: UI/UX Refinement (P2)
- [ ] **Task 3.1**: Implement `cl.Step` for Tool Call visualization (show "Thinking...").
- [ ] **Task 3.2**: Add `chainlit.md` welcome screen.
- [ ] **Task 3.3**: Customize Theme (optional).

## Phase 4: Final Polish
- [ ] **Task 4.1**: Code cleanup and comments.
- [ ] **Task 4.2**: Documentation update (README).

## Phase 5: Gemini-like Experience (v2.0) - [IN PROGRESS]
- [ ] **Task 5.1 (Nested Steps)**: Refactor `app.py` to wrap all tool calls inside a single parent `cl.Step("Thinking...")`.
- [ ] **Task 5.2 (Starters)**: Update `.chainlit/config.toml` to add "One-click Analysis" buttons for demo data.
- [ ] **Task 5.3 (Avatar)**: Add a custom avatar to `public/` directory and configure it.
- [ ] **Task 5.4 (Streaming Polish)**: Ensure text streaming doesn't start until "Thinking" is complete (or streams in parallel cleanly).

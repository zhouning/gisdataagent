# Implementation Plan

## Phase 1: Environment & Prototype (P0)
- [ ] **Task 1.1**: Install `chainlit` dependency.
- [ ] **Task 1.2**: Create `data_agent/app.py` skeleton.
- [ ] **Task 1.3**: Implement basic ADK `run_async` loop within Chainlit.
- [ ] **Verification**: "Hello World" chat works with ADK agent.

## Phase 2: Rich Media Integration (P1)
- [ ] **Task 2.1**: Implement `path_extractor` regex logic.
- [ ] **Task 2.2**: Implement `cl.Image` rendering for PNGs.
- [ ] **Task 2.3**: Implement `cl.File` / `cl.Frame` for HTML maps.
- [ ] **Verification**: Run end-to-end test, verify charts appear in chat.

## Phase 3: UI/UX Refinement (P2)
- [ ] **Task 3.1**: Implement `cl.Step` for Tool Call visualization (show "Thinking...").
- [ ] **Task 3.2**: Add `chainlit.md` welcome screen.
- [ ] **Task 3.3**: Customize Theme (optional).

## Phase 4: Final Polish
- [ ] **Task 4.1**: Code cleanup and comments.
- [ ] **Task 4.2**: Documentation update (README).

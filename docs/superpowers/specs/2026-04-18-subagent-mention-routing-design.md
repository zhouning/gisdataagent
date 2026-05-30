# @SubAgent Mention Routing Design

Date: 2026-04-18
Status: Approved in conversation
Scope: GIS Data Agent prototype branch (`feat/v12-extensible-platform`)

## 1. Goal

Add an explicit `@SubAgent` interaction mode to the chat box so advanced users can bypass semantic intent routing when they already know which pipeline, sub-agent, or skill they want to invoke.

Examples:
- `@General 把这个 shp 渲染成专题图`
- `@DataVisualization 把刚才处理后的数据做热力图`
- `@MyCustomSkill 生成这个数据集的元数据摘要`

This feature should coexist with the current natural-language routing flow:
- Normal messages continue to use Gemini-based semantic routing.
- Messages beginning with a valid `@...` mention take the explicit route.
- Unknown mentions fall back to the current semantic router.

## 2. Why This Is Worth Adding

The current architecture is optimized for intent inference by the main agent. That is the right default for ordinary users, but it adds avoidable latency and token usage for expert users who already know the target agent.

`@SubAgent` creates a second interaction path:
- **Implicit routing** for natural language and novice users
- **Explicit routing** for expert users who want control and predictability

This improves:
- user control
- routing determinism
- latency and token cost in explicit cases
- usability of the existing multi-agent architecture as the system grows

## 3. Non-Goals

This design does **not** introduce:
- automatic orchestration of missing upstream dependencies
- cross-session state recovery
- changes to Chainlit message protocol
- replacement of the current semantic router
- arbitrary invocation of internal code paths that are not already registered as pipeline/sub-agent/skill concepts

## 4. User Experience

### 4.1 Input behavior

The chat input supports `@`-triggered mention autocomplete.

When the user types `@`, the frontend shows a dropdown list of invocable targets. The user can:
- continue typing to filter
- use arrow keys to navigate
- use `Enter` or `Tab` to accept
- use `Esc` to close the dropdown

The sent message remains plain text. No Chainlit transport changes are required.

### 4.2 Examples

- `@Governance 检查这个地块数据的拓扑错误`
- `@Optimization 对这批耕地做空间布局优化`
- `@DataVisualization 对刚才结果生成分级设色图`
- `@soil-analysis-expert 分析这份土壤采样表`

### 4.3 Failure behavior

If the mention text cannot be resolved to a valid target, the backend falls back to the current semantic routing behavior.

This keeps the feature forgiving and avoids breaking existing user habits.

## 5. Invocable Target Types

The system supports four target classes.

### 5.1 Pipeline targets

Direct routing to the three top-level pipelines already used by the system:
- `@General`
- `@Governance`
- `@Optimization`

Behavior:
- skip semantic classification
- set the target pipeline directly
- keep the rest of the downstream execution flow unchanged

### 5.2 Pipeline sub-agent targets

Direct routing to individual internal pipeline agents such as:
- `@DataVisualization`
- `@DataProcessing`
- `@GovExploration`

Behavior:
- bypass top-level semantic classification
- invoke a dedicated sub-agent execution path
- use only current session state as context

### 5.3 Custom skill targets

User-defined custom skills stored in the database and already exposed through the product capability model.

Behavior:
- only return skills visible to the current user (`own + shared` under current rules)
- resolve by stable handle/slug
- execute through existing custom skill creation/invocation logic

### 5.4 Built-in ADK skill targets

Built-in skills under `data_agent/skills/` can also be exposed as mentionable targets.

Behavior:
- discover from the existing skills directory
- expose only stable skill identifiers
- execute through the existing built-in skill path rather than inventing a new runtime abstraction

## 6. Backend Architecture

## 6.1 Mention registry

Add a new module such as `data_agent/mention_registry.py`.

Responsibilities:
- aggregate all invocable targets into one normalized registry
- unify metadata across pipelines, sub-agents, custom skills, and built-in skills
- provide lookup by handle
- expose metadata for frontend autocomplete

Suggested normalized record shape:

```python
{
    "handle": "DataVisualization",
    "label": "DataVisualization",
    "type": "sub_agent",
    "description": "地图渲染、图表生成、3D可视化",
    "allowed_roles": ["admin", "analyst"],
    "required_state_keys": ["processed_data"],
    "pipeline": "GENERAL",
}
```

Required fields:
- `handle`
- `label`
- `type`
- `description`
- `allowed_roles`
- `required_state_keys`

Optional fields:
- `pipeline`
- `source`
- `skill_id`
- `user_owned`

## 6.2 Handle rules

Handles must be stable, unique, and autocomplete-friendly.

Recommended rules:
- top-level pipelines: PascalCase (`General`, `Governance`, `Optimization`)
- internal sub-agents: PascalCase based on internal agent name
- built-in ADK skills: keep stable kebab-case if that is the existing canonical name
- custom skills: slug generated from skill name with collision-safe suffix when needed

If collisions occur, registry uniqueness wins. The UI can still display richer labels such as:
- `DataVisualization (sub-agent)`
- `DataVisualization:optimization`

## 6.3 Mention parser

Add a new parser module such as `data_agent/mention_parser.py`.

Responsibilities:
- detect whether the message begins with a mention
- extract the first mention token
- preserve the remaining natural-language instruction
- resolve the mention against the registry

Parsing rule:
- only the **leading** mention is interpreted as routing syntax
- later `@...` occurrences in message body are treated as ordinary text

Examples:
- `@DataVisualization 把刚才结果做热力图` -> mention=`DataVisualization`, remaining=`把刚才结果做热力图`
- `请帮我 @DataVisualization 画图` -> no special parse, falls back to semantic router

This keeps the syntax predictable and avoids accidental routing.

## 6.4 Integration point in app.py

Current semantic routing happens in `data_agent/app.py` around the existing `classify_intent(...)` call.

The new flow becomes:

1. check pending template behavior as today
2. run `parse_agent_mention(user_text, user_id, role)`
3. if a valid mention target is found:
   - enforce RBAC
   - dispatch explicitly according to target type
4. else:
   - continue into current `classify_intent(...)`

This preserves the current router as the default path and keeps the new feature additive.

## 6.5 Dispatch behavior by target type

### Pipeline target dispatch

For `pipeline` targets:
- skip LLM classification
- set `intent` directly
- continue through current execution code path for that pipeline

This is the lowest-risk implementation and should be delivered first.

### Sub-agent target dispatch

For `sub_agent` targets:
- dispatch into a dedicated direct sub-agent executor
- do not auto-run upstream steps
- consume only current session state

This executor should be thin. It should not duplicate the whole pipeline framework. It should only:
- validate required state
- build the sub-agent input context
- run the selected agent
- normalize result delivery back into chat/map/data updates

### Custom skill target dispatch

For `custom_skill` targets:
- resolve target from DB-visible custom skills
- route through the existing custom skill invocation path
- preserve current user scoping and sharing logic

### Built-in ADK skill target dispatch

For `adk_skill` targets:
- resolve from skills directory discovery
- invoke through the existing built-in skill mechanism
- do not create a second skill runtime

## 7. State Dependency Policy

This is the most important design constraint.

For direct sub-agent execution, the system uses **only the most recent current-session state**. It does not attempt to reconstruct upstream outputs automatically.

Examples:
- `@DataVisualization` may require `processed_data`
- `@DataSummary` may require processed or analyzed results
- `@GovProcessing` may require loaded or profiled dataset context

If required state is missing, the system should fail fast with a specific message such as:

> `@DataVisualization` requires `processed_data`, but no such state exists in the current session. Please run a preceding processing step first.

Rationale:
- avoids hidden extra token spend
- avoids surprising multi-step side effects
- keeps direct invocation deterministic
- keeps the first implementation small and maintainable

## 8. RBAC and Safety

The frontend may hide or gray out unavailable targets, but authorization must remain backend-enforced.

Rules:
- `viewer` cannot use mention syntax to bypass existing governance/optimization restrictions
- custom skills must still respect current visibility and ownership rules
- built-in skills and sub-agents should expose allowed roles explicitly in the registry

If an unauthorized target is mentioned, the backend returns the same denial semantics already used by the current routing flow.

## 9. Frontend API

Add a dedicated endpoint, for example:
- `GET /api/chat/mention-targets`

Return shape:

```json
{
  "targets": [
    {
      "handle": "DataVisualization",
      "label": "DataVisualization",
      "type": "sub_agent",
      "description": "地图渲染、图表生成、3D可视化",
      "allowed": true,
      "allowed_roles": ["admin", "analyst"],
      "required_state_keys": ["processed_data"]
    }
  ]
}
```

Why a new endpoint instead of reusing `/api/capabilities`:
- capabilities currently exposes built-in skills, custom skills, and toolsets, but not pipelines or internal sub-agents
- capabilities lacks mention-specific metadata such as `required_state_keys`
- capabilities is capability-oriented, not chat-input-oriented
- mention autocomplete needs a smaller, normalized, RBAC-aware payload

## 10. Frontend Component Changes

Primary file:
- `frontend/src/components/ChatPanel.tsx`

Add a lightweight mention-autocomplete layer around the existing textarea.

New frontend concerns:
- local state for dropdown visibility and highlighted index
- fetch mention targets once per chat session start or first `@` use
- client-side filtering by typed token
- insertion of selected handle into textarea
- keyboard controls: Up/Down/Enter/Tab/Esc

The textarea remains the source of truth. No protocol changes are needed.

## 11. Error Handling

Required explicit cases:

1. **Unknown mention**
   - fall back to semantic routing

2. **Unauthorized mention**
   - backend denial consistent with current RBAC messaging

3. **Known sub-agent but missing required state**
   - fail fast with exact missing keys

4. **Registry conflict or invalid handle**
   - prevent at registry build time and log clearly

5. **Frontend autocomplete fetch failure**
   - degrade gracefully: free text still works, backend parsing still works

## 12. Observability

Add logs and metrics so this new interaction mode can be evaluated.

Recommended fields:
- `mention_detected`
- `mention_target_type`
- `mention_target_handle`
- `mention_resolution_status` (`matched`, `unknown`, `unauthorized`, `missing_state`)
- `mention_fallback_to_semantic_router`

This allows measurement of:
- explicit-routing adoption
- failure modes
- most-used direct targets
- whether exposing more sub-agents is worthwhile

## 13. Testing Strategy

### 13.1 Backend tests

Add unit tests for:
- leading mention parsing
- non-leading `@` ignored
- unknown mention fallback
- RBAC enforcement
- state dependency validation
- registry aggregation and collision handling

Add integration tests for:
- `@General` direct route
- `@Governance` denied for viewer
- `@DataVisualization` success when session state exists
- `@DataVisualization` failure when `processed_data` missing
- custom skill visibility filtering

### 13.2 Frontend tests

Add tests for:
- `@` opening dropdown
- filtering targets by typed text
- arrow-key selection
- Enter/Tab accept
- Esc close
- no regression in normal send behavior

## 14. Incremental Delivery Plan

Implement in this order:

### Phase 1: Pipeline direct route
- mention registry with pipeline entries only
- mention parser
- `app.py` pre-routing integration
- backend fallback behavior
- minimal tests

### Phase 2: Frontend autocomplete
- `GET /api/chat/mention-targets`
- ChatPanel dropdown and keyboard interaction
- role-aware target display

### Phase 3: Sub-agent direct route
- sub-agent registry entries
- required state metadata
- direct sub-agent executor
- dependency validation

### Phase 4: Skill targets
- custom skill mention support
- built-in ADK skill mention support
- collision hardening and observability improvements

This phased order reduces risk because the first shippable slice already provides user value.

## 15. Recommendation

This feature is both reasonable and feasible for the current GIS Data Agent architecture.

It should be implemented as an **explicit routing overlay**, not as a replacement for the existing semantic router.

That gives the system two complementary modes:
- implicit expert discovery through intent routing
- explicit expert control through mention routing

This fits the product direction well because the platform is already evolving toward user-extensible multi-agent orchestration. `@SubAgent` makes that architecture legible and controllable from the chat surface.

## 16. Final Decision Summary

Approved decisions from discussion:
- mentionable targets include all four groups: top-level pipelines, pipeline sub-agents, custom skills, and built-in ADK skills
- sub-agent direct execution uses current session state only
- missing state fails fast instead of auto-running prerequisites
- frontend uses `@`-triggered autocomplete in the chat box
- unresolved mentions fall back to the current semantic router

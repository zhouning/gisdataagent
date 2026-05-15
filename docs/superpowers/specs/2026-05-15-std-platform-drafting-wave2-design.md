# Standards Platform — Drafting Wave 2 Design

**Date:** 2026-05-15
**Branch:** `feat/v12-extensible-platform`
**Status:** design — ready for implementation plan
**Parent spec:** `docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`
**Predecessors:** Wave 1 (`2026-05-15-std-platform-drafting-wave1-design.md`) + Wave 1.5 (in-band, no separate spec — adds data_elements table CRUD round-trip)
**Scope:** P1 「起草」 sub-tab, citation assistant — second of three drafting waves

## 0. Why this spec

Wave 1 + 1.5 deliver a working clause editor (TipTap + lock + data_elements
CRUD). The next user-facing capability per the parent spec §6.2 is the
citation assistant: while drafting a clause, the user looks up references
from three sources, the system reranks them, the user inserts one as a
citation chip in the editor body, and the system persists a `std_reference`
row.

Wave 3 (AI drafting suggestions) follows after this.

## 1. Scope of Wave 2

**Delivered**

- **Three-source search** behind one endpoint:
  - **pgvector**: cosine search over `std_clause.embedding`,
    `std_data_element.embedding`, `std_term.embedding` (all VECTOR(768),
    populated by the existing `embedder.py`)
  - **KB GraphRAG**: wrap the existing `data_agent.knowledge_base.search()`
    (already used elsewhere in the project)
  - **web**: reuse the existing `data_agent.standards_platform.ingestion.web_fetcher`
    (white-listed domains only: std.samr.gov.cn / openstd.samr.gov.cn /
    iso.org / ogc.org / arxiv.org / scholar.google.com / cnki.net), with
    manual-paste fallback for blocked / 4xx URLs
- **LLM rerank** via `model_gateway` (default flash). Combines candidates
  from all three sources, returns ranked list with `confidence ∈ [0, 1]`.
- **Two new REST endpoints**:
  - `POST /api/std/citation/search` — orchestrate the 3 sources + rerank
  - `POST /api/std/citation/insert` — write `std_reference` row, return ref_id
- **Citation chip** in the editor as a custom TipTap mark. Renders
  `[[ref:<UUID>]]` as a styled chip with confidence color (green ≥0.8,
  amber 0.6-0.8, red <0.6). The text-form `[[ref:<UUID>]]` is the
  canonical Markdown representation, so the existing
  `extractTablesAsMarkdown` save path round-trips it cleanly.
- **CitationPanel** in the editor right column (replaces ClauseMeta when
  invoked, or appears as a slide-over).

**Explicitly NOT in this wave**

- AI drafting suggestions (Wave 3)
- Reverse lookup ("which clauses cite this reference?")
- Citation editing UX (mark click → menu to update or remove). Wave 2 is
  insert-only; user removes a chip by deleting the `[[ref:id]]` text.
- Cross-language search
- Image / table snapshot preview in candidate list

## 2. Architecture

### 2.1 Backend — new modules under `data_agent/standards_platform/drafting/`

```
drafting/
├── citation_sources.py       # 3 source implementations (parallel-safe)
├── citation_rerank.py        # model_gateway-based LLM rerank
└── citation_assistant.py     # orchestrator: fan out → rerank → return
```

Existing modules reused:

- `embedder.py` (Wave 1 ancestor) — already populates `embedding` columns
- `data_agent/knowledge_base.py` — top-level `search_kb(query, kb_id=None,
  kb_ids=None, top_k=10)` returns chunks. Wave 2 calls it with
  `kb_id=STANDARDS_KB_ID` from env (or `None` → search across all KBs)
- `data_agent/standards_platform/ingestion/web_fetcher.py` — `fetch(url)`,
  `save_manual(url, pasted_text, user_id)`
- `data_agent/model_gateway.py` — `ModelGateway.create_model(task_type=...)`
  returns LLM client; we use `task_type="rerank"`, model defaults to flash

### 2.2 Backend — new routes appended to `data_agent/api/standards_routes.py`

| Method | Path | Role | Calls |
|---|---|---|---|
| POST | `/api/std/citation/search` | editor | `citation_assistant.search_citations` |
| POST | `/api/std/citation/insert` | editor | direct INSERT into `std_reference` |

### 2.3 Frontend — new + modified

```
standards/draft/
├── ClauseEditor.tsx          # MODIFY: register Citation TipTap mark, open panel button
├── CitationPanel.tsx         # NEW: search box + candidate list + insert button
└── citationMark.ts           # NEW: TipTap mark definition for [[ref:id]]
```

```
standards/
└── standardsApi.ts           # MODIFY: +2 fetch functions (citationSearch, citationInsert)
```

### 2.4 No DB migration

- `std_reference` table already exists in migration 073 with the right
  columns: `source_clause_id`, `target_kind` (CHECK constraint allows
  `std_clause`/`std_document`/`external_url`/`web_snapshot`/`internet_search`),
  `target_clause_id`, `target_url`, `snapshot_id`, `citation_text`,
  `confidence NUMERIC(3,2)`, `verified_by`, `verified_at`
- `std_web_snapshot` table also already exists (migration 073)
- Embedding columns already exist on `std_clause` / `std_data_element` / `std_term`

### 2.5 No new npm dependencies

- TipTap custom mark uses the existing `@tiptap/core` (already a transitive
  dep of `@tiptap/react`)
- Search panel uses plain React + the existing `standardsApi.ts`

## 3. Key data flows

### 3.1 Search request

```
Editor: user clicks "查找引用" button or presses Ctrl+Shift+R
  → CitationPanel opens, focuses search input
  → user types or pastes selection → submits
  → POST /api/std/citation/search
       Body: {clause_id, query, sources?: ['pgvector','kb','web']}
              (sources omitted = all three)
       Server (in citation_assistant.search_citations):
         1. embed(query) via embedder
         2. parallel:
            a. pgvector search across 3 tables, top_k=10 each
            b. knowledge_base.search(query, k=10)
            c. web_fetcher: only triggered if user explicitly toggles
               (web is slow; default off in MVP), returns recent
               std_web_snapshot matches by full-text on snapshot.body
         3. assemble candidates: list of {kind, target_id|url, snippet,
                                          base_score}
         4. citation_rerank.rerank(query, candidates) → adds confidence
         5. sort by confidence desc, top_k=20 overall
       → 200 + {candidates: [
           {kind: 'std_clause', target_clause_id, snippet, confidence,
            doc_code, clause_no},
           {kind: 'std_data_element', target_data_element_id, code,
            name_zh, snippet, confidence},
           {kind: 'kb_chunk', kb_doc_id, snippet, confidence},
           {kind: 'web_snapshot', snapshot_id, url, snippet, confidence},
         ]}
```

### 3.2 Insert citation

```
User clicks "插入引用" on a candidate card
  → POST /api/std/citation/insert
       Body: {clause_id, candidate}
       Server: INSERT INTO std_reference (
                   source_clause_id, target_kind, target_clause_id|...,
                   citation_text, confidence, verified_by, verified_at)
               VALUES (...)  -- verified_by=user, verified_at=now()
       → 200 + {ref_id, citation_text}
  → Frontend: editor.commands.insertContent(`[[ref:${ref_id}]]`)
              (the citationMark transforms this to a chip on display)
```

### 3.3 Save round-trip

The TipTap mark `citation` defines:

- `parseHTML`: pattern `<span data-citation="<UUID>">[[ref:<UUID>]]</span>`
  → mark
- `renderHTML`: `<span data-citation="<UUID>" class="citation-chip">[[ref:<UUID>]]</span>`
- `toMarkdown`-equivalent: ensure the inner text `[[ref:<UUID>]]` is what
  `extractTablesAsMarkdown` (existing helper) sees in `cell.textContent`

Because the mark only **wraps** existing text content (the literal
`[[ref:<UUID>]]`), our existing serialization path emits it verbatim. On
load, `marked.parse(body_md)` produces plain text containing `[[ref:UUID]]`,
TipTap's `parseHTML` rule on the mark won't fire (no `<span>` wrapping the
text from marked output); the mark **only** survives within an editing
session.

To make `[[ref:UUID]]` chips persist across save/load, we add a small
post-processor on load:

```ts
// after marked.parse(body_md) → html
const enhanced = html.replace(
  /\[\[ref:([0-9a-f-]+)\]\]/g,
  (_, id) => `<span data-citation="${id}" class="citation-chip">[[ref:${id}]]</span>`
);
editor.commands.setContent(enhanced, false);
```

This way:
- `body_md` always stores the canonical `[[ref:UUID]]` text
- The TipTap mark renders chips during editing
- Round-trip is simple regex on each side

### 3.4 Chip styling and confidence

```css
.citation-chip {
  display: inline-block;
  padding: 0 4px;
  border-radius: 3px;
  font-size: 12px;
  font-family: ui-monospace, monospace;
  border: 1px solid #ccc;
  margin: 0 2px;
  cursor: default;
}
.citation-chip[data-confidence-high] { background: #e6f7ee; border-color: #0a7; }
.citation-chip[data-confidence-mid]  { background: #fff8e1; border-color: #f60; }
.citation-chip[data-confidence-low]  { background: #fde2e2; border-color: #d33; color: #a00; }
```

The confidence band is fetched once at chip render time via a small
`GET /api/std/references/{id}` endpoint (added if needed) — but for
simplicity in Wave 2, we **do not** fetch confidence on render: chips
display as neutral. The rerank confidence is shown in the CitationPanel
candidate list before insertion. This keeps load time fast.

### 3.5 Source toggling

The CitationPanel has 3 checkboxes (default: pgvector ✓, kb ✓, web ✗).
The user explicitly opts into web search because it's slower and may hit
the manual-paste fallback flow.

## 4. Module contracts

### 4.1 `citation_sources.py`

```python
class Candidate(TypedDict):
    kind: str           # 'std_clause' | 'std_data_element' | 'std_term'
                        # | 'kb_chunk' | 'web_snapshot' | 'internet_search'
    target_id: str | None       # UUID for in-DB targets
    target_url: str | None      # for web
    snippet: str                # ≤500 chars
    base_score: float           # raw similarity / rank score
    extra: dict                 # source-specific fields (doc_code,
                                # clause_no, snapshot_id, etc.)


def search_pgvector(query_embedding: list[float], *,
                    top_k_per_table: int = 10) -> list[Candidate]:
    """Cosine search over std_clause / std_data_element / std_term."""

def search_kb(query: str, *, top_k: int = 10) -> list[Candidate]:
    """Wrap data_agent.knowledge_base.search_kb(); return chunks as
    Candidates. Reads STANDARDS_KB_ID from env if set; otherwise
    searches across all kb_ids."""

def search_web(query: str, *, top_k: int = 5) -> list[Candidate]:
    """Search the existing std_web_snapshot table by FTS on body.
    Web fetcher is invoked only when the user supplies a URL (handled
    by an existing route), not during this generic search."""
```

### 4.2 `citation_rerank.py`

```python
def rerank(query: str, candidates: list[Candidate], *,
           top_k: int = 20) -> list[Candidate]:
    """LLM rerank via model_gateway. Adds 'confidence' float to each
    Candidate's extra dict and sorts by it. Returns up to top_k."""
```

The prompt (in Chinese, following project convention):

```
你是一个数据标准检索助手。给定一段查询和一组候选片段，为每个候选给出 0-1
之间的相关度分数。返回 JSON 数组 [{"index": <int>, "confidence": <float>,
"reason": <string>}]，按 confidence 降序。

查询: <query>

候选:
[0] kind=std_clause snippet="..."
[1] kind=kb_chunk snippet="..."
...
```

### 4.3 `citation_assistant.py`

```python
def search_citations(*, clause_id: str, query: str,
                     sources: set[str] | None = None,
                     top_k: int = 20) -> list[Candidate]:
    """Orchestrate. sources=None means all of pgvector / kb / web."""
```

### 4.4 Routes

```python
POST /api/std/citation/search
  Body: {clause_id: str, query: str, sources?: ['pgvector','kb','web']}
  → 200 {candidates: [Candidate, ...]}
  → 400 if query missing / clause_id invalid

POST /api/std/citation/insert
  Body: {clause_id: str, candidate: Candidate}
  → 200 {ref_id: str, citation_text: str}
  → 400 if candidate fields don't satisfy std_reference CHECK constraint
```

## 5. Frontend behaviour

### 5.1 CitationPanel

```
[ Search box ]                                 [×]
  [ pgvector ✓ ] [ KB ✓ ] [ web ☐ ]
  [ Search ]

  Results:
  ┌──────────────────────────────────────────┐
  │ 🟢 0.92  std_clause: GB/T 13923 §4.2     │
  │ 行政区代码字段定义...                       │
  │ [插入]                                     │
  ├──────────────────────────────────────────┤
  │ 🟡 0.71  kb_chunk: 国土调查规程            │
  │ ...                                        │
  │ [插入]                                     │
  └──────────────────────────────────────────┘
```

Mounted as a slide-over from the right edge, triggered by:
- Toolbar button "查找引用" in ClauseEditor
- Keyboard shortcut Ctrl+Shift+R when editing a clause

### 5.2 ClauseEditor changes

```tsx
// new state
const [citationOpen, setCitationOpen] = useState(false);

// new toolbar button (after − 行 button)
<button onClick={() => setCitationOpen(true)}
        disabled={state.kind !== "editing"}>
  查找引用
</button>

// new render block (overlay or absolute-positioned panel)
{citationOpen && (
  <CitationPanel
    clauseId={clause.id}
    onClose={() => setCitationOpen(false)}
    onInsert={(refId) => {
      editor?.chain().focus()
        .insertContent(`[[ref:${refId}]]`).run();
      setCitationOpen(false);
    }}
  />
)}
```

### 5.3 citationMark.ts (TipTap mark)

```ts
import { Mark, mergeAttributes } from "@tiptap/core";

export const Citation = Mark.create({
  name: "citation",
  addAttributes() {
    return {
      refId: {
        default: null,
        parseHTML: (el) => el.getAttribute("data-citation"),
        renderHTML: (attrs) =>
          attrs.refId ? { "data-citation": attrs.refId } : {},
      },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-citation]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes({ class: "citation-chip" }, HTMLAttributes),
      0,
    ];
  },
});
```

Registered in ClauseEditor's `useEditor.extensions` array alongside
StarterKit, Table, etc.

### 5.4 Save round-trip

In the existing `onSave` flow:

- `editor.getHTML()` returns `<span data-citation="UUID">[[ref:UUID]]</span>`
- `extractTablesAsMarkdown` skips spans (only handles tables)
- `turndown.turndown(htmlWithoutTables)` walks the span; turndown by
  default outputs the inner text `[[ref:UUID]]` (a span has no
  block-level meaning). Verified by smoke test — if turndown wraps the
  span text in unexpected ways, we add a custom turndown rule that
  emits the raw `[[ref:UUID]]` text.

In the existing load flow:

- After `marked.parse(combined)`, run the `replace(/\[\[ref:([0-9a-f-]+)\]\]/g, ...)`
  enhancer described in §3.3 before `setContent`.

## 6. Testing

### 6.1 Unit tests

`data_agent/standards_platform/tests/test_citation_assistant.py`:

1. `test_search_pgvector_returns_top_k` — seed 5 clauses with embeddings,
   query embedding → top 3 by cosine
2. `test_search_kb_wraps_chunks` — patch `knowledge_base.search` with a
   stub, assert candidates shape
3. `test_search_web_filters_by_fts` — seed std_web_snapshot, search
4. `test_assistant_orchestrates_three_sources` — patch all 3 sources,
   assert merged + reranked result
5. `test_rerank_assigns_confidence` — patch model_gateway with a stub
   that returns a fixed JSON ranking; assert candidates carry confidence

### 6.2 API tests

`data_agent/standards_platform/tests/test_api_citation.py`:

1. `test_search_citations_returns_200` — full path with stubbed sources
2. `test_search_citations_validates_query_required` — returns 400
3. `test_insert_citation_creates_std_reference_row` — assert row in DB
4. `test_insert_citation_rejects_invalid_target_kind` — 400 on CHECK
   violation

### 6.3 Frontend

No unit tests in this wave (consistent with Wave 1). Manual E2E only.

### 6.4 Manual E2E

1. Open clause FT.1 in 起草 editor
2. Click 查找引用 → panel opens
3. Search "行政区代码" → candidates appear, top one is std_data_element XZQDM
4. Click 插入 on that candidate
5. Editor shows `[[ref:UUID]]` chip styled inline
6. Save → DevTools Network shows PUT body_md contains `[[ref:UUID]]` literal
7. Switch to FT.2 then back → chip re-renders correctly
8. SQL: `SELECT * FROM std_reference WHERE source_clause_id = ...` → row exists

### 6.5 Regression

- `pytest data_agent/standards_platform/` stays green
- `npm run build` exit 0
- Existing Wave 1.5 table CRUD still works (the citation mark MUST NOT
  break the extractTablesAsMarkdown round-trip)

## 7. Done criteria

- [ ] 3 source modules + orchestrator + rerank, all unit-tested
- [ ] 2 routes mounted, 4 API tests pass
- [ ] CitationPanel + Citation mark integrated into ClauseEditor
- [ ] Manual E2E §6.4 all 8 steps pass
- [ ] `std_reference` row created on insert
- [ ] No regression in pytest or npm build

## 8. Risks and limits

| Risk | Mitigation |
|---|---|
| LLM rerank latency >2 s makes UI feel sluggish | Show loading spinner; allow user to skip rerank by Shift+Search (uses base_score directly) |
| KB GraphRAG is project-wide and may not be tuned for standards content | First version returns raw results; tuning deferred to a future "KB indexing for standards" task |
| Web search is rate-limited (5 sources × N queries) | Default-off; reuses existing manual-paste fallback when web_fetcher fails |
| Turndown converts `<span data-citation>` in unexpected ways on save | Test in `_test_turndown.cjs`-style smoke (already used for Wave 1.5 debug); fall back to custom turndown rule if needed |
| Marked re-parses `[[ref:UUID]]` in body_md → not enhanced to chip | The load-time `replace(...)` regex enhancer handles this — verified by E2E step 7 |
| Citation chip is not editable (only deletable as text) | Acceptable for Wave 2; click-to-update is Wave 3+ scope |
| Confidence on chip not shown post-insert | Acceptable for Wave 2; confidence visible in the search panel before insert |

## 9. Out of scope (deferred)

- Reverse-citation panel ("incoming references to this clause")
- Citation chip click → context menu (update target, change kind, remove)
- Confidence-aware chip color on render (requires N additional fetches)
- Global citation graph visualization (Wave 4+)
- Internet search via firecrawl/tavily (parent spec mentions; deferred)
- Multilingual rerank prompt
- Chip preview on hover

## 10. Implementation order

Suggested for the writing-plans step:

1. `citation_sources.py` skeleton + 3 source functions
2. Unit tests 1-3 (one per source) → green
3. `citation_rerank.py` + unit test 5 → green
4. `citation_assistant.py` orchestrator + unit test 4 → green
5. 2 REST routes + 4 API tests → green
6. `standardsApi.ts` +2 fetch functions
7. `citationMark.ts` (TipTap mark)
8. `CitationPanel.tsx` (search UI)
9. `ClauseEditor.tsx` integration (toolbar button, panel mount, mark
   registration, save/load enhancers)
10. `npm run build` clean + manual E2E + push

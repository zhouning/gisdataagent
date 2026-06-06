# Standards Platform Review Template Visualization First Slice Design

- **Status**: Approved for implementation planning
- **Date**: 2026-06-06
- **Scope**: P4 审定流模板可视化 first slice
- **Builds on**: `std_document_version`, `std_review_round`,
  `std_reference`, `std_review_comment`, `gating.check_close_gating()`,
  and `ReviewSubTab`

## 1. Goal

Add a read-only visualization of the default standards review workflow so an
operator can understand where a selected document version is in the review
stage, which role owns each step, and which gates currently block approval.

This is a template visualization, not a template builder. It documents and
renders the workflow already implemented by Wave 4:

1. draft version
2. start review round
3. audit references
4. resolve review comments
5. close review round
6. approved and ready for publish

## 2. In Scope

1. **Repository**:
   `data_agent/standards_platform/review/template_repo.py` with a deterministic
   `default_review_template(version_id)` read model.
2. **API**:
   `GET /api/std/reviews/template/{version_id}` for authenticated users.
3. **Frontend SDK**:
   typed `getReviewTemplate(versionId)` in `standardsApi.ts`.
4. **Review UI**:
   a compact `ReviewTemplatePanel` above the existing review columns.
5. **Roadmap update**:
   mark P4 review template visualization first slice complete.

## 3. Non-Goals

- No new database tables or migrations.
- No editable review template designer.
- No multi-stage serial approval workflow.
- No new review status semantics.
- No change to round close gating or drafting/publishing guards.
- No graph layout library, ReactFlow, or canvas in this slice.
- No workflow execution engine.

## 4. Response Shape

```json
{
  "template_id": "default_review_v1",
  "version_id": "...",
  "version_status": "review",
  "steps": [
    {
      "id": "draft",
      "label": "起草版本",
      "role": "standard_editor",
      "status": "done",
      "description": "版本处于 draft 后可启动审定。",
      "metrics": {}
    },
    {
      "id": "start_review",
      "label": "启动审定",
      "role": "admin",
      "status": "done",
      "description": "管理员指定 reviewer 并创建 open round。",
      "metrics": {"open_round_id": "..."}
    }
  ],
  "edges": [
    {"source": "draft", "target": "start_review", "label": "admin starts round"}
  ],
  "summary": {
    "open_round_id": "...",
    "latest_round_id": "...",
    "latest_round_status": "open",
    "latest_round_outcome": null,
    "pending_refs": 2,
    "open_comments": 1,
    "blocking": true
  }
}
```

Step status values are fixed:

- `done`: completed for this version
- `active`: the current working step
- `blocked`: current step cannot advance because a gate is failing
- `pending`: not reached yet

## 5. Backend Design

`default_review_template(version_id)` reads only existing tables:

- `std_document_version` for version existence and status
- `std_review_round` for open/latest review round
- `std_reference JOIN std_clause` for total/pending/approved/rejected refs
- `std_review_comment` for total/open/resolved comments

Status mapping:

| Version / round state | Template behavior |
|---|---|
| no version row | API returns `404 {"error": "version not found"}` |
| `draft` and no round | draft is active; later steps pending |
| `review` with open round and pending refs | audit references is blocked |
| `review` with open round, refs done, open comments | resolve comments is blocked |
| `review` with open round and gates clear | close round is active |
| `approved` | all review steps done; approved step active/done |
| `released` or `retired` | review template is complete; publish lifecycle is out of scope |
| latest round rejected and version back to `draft` | close round done with rejected outcome; draft active again |

The repository should return an empty-but-valid metrics set when a version has
no references or comments. This keeps newly drafted standards explainable.

## 6. API Design

`GET /api/std/reviews/template/{version_id}`:

- any authenticated user can read
- returns `401` when unauthenticated
- returns `404 {"error": "version not found"}` for an unknown version
- otherwise returns the response shape above
- no query parameters in the first slice

The route must be registered under `/api/std/reviews/*` without shadowing any
existing review round/comment/reference routes.

## 7. Frontend Design

`ReviewTemplatePanel` is mounted at the top of `ReviewSubTab`, above the
existing four-column review workspace.

The panel shows:

- horizontal step list with stable widths
- role label for each step
- step status badge (`done`, `active`, `blocked`, `pending`)
- summary chips for version status, latest/open round, pending references, and
  open comments
- short blocked message when `summary.blocking` is true

The existing review columns remain unchanged below the panel. The panel is
read-only and refreshes when:

- `versionId` changes
- selected round changes
- references are updated
- a round is closed

## 8. Testing Strategy

Use TDD for backend behavior.

Repository tests:

- draft version with no round marks draft active and later steps pending
- review version with an open round and pending refs marks audit blocked
- review version with refs approved and open comments marks comments blocked
- review version with all gates clear marks close round active
- approved version marks review flow complete

API tests:

- unauthenticated gets `401`
- missing version gets `404`
- happy path returns template metadata and steps
- route is available and not confused with round routes

Frontend:

- `npm run build` is required verification; this UI area does not currently
  have a React test harness.

Regression:

- focused review-template backend tests
- full `data_agent/standards_platform` suite
- frontend build

## 9. Acceptance Criteria

- A selected standard version exposes a deterministic default review template.
- The template reflects the existing review state machine and close gates.
- ReviewSubTab shows the template without changing existing review operations.
- No new persistence or workflow semantics are introduced.
- Focused backend tests, full Standards Platform tests, and frontend build pass.

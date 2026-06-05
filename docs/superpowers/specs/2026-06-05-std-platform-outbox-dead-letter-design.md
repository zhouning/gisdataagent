# Standards Platform Outbox Dead-Letter UI Design

- **Status**: Approved for implementation planning
- **Date**: 2026-06-05
- **Scope**: v25.4 P4 first slice, outbox failed-event visibility and retry
- **Related roadmap**: `docs/roadmap.md` P4, Standards Platform dead-letter UI
- **Builds on**: existing `std_outbox`, `data_agent.standards_platform.outbox`, and `DeriveSubTab`

## 1. Goal

Add an admin-only dead-letter operations slice for Standards Platform outbox events.
The current system has reliable outbox primitives and a worker, but the UI only
surfaces aggregate failure counts. When a standards ingestion, publishing, or
derivation event reaches `status='failed'`, an operator must use SQL to inspect
and retry it. This slice makes that workflow available inside the existing
Standards Platform experience.

The first slice should let an admin:

1. View failed, pending, and in-flight `std_outbox` events with enough context to
   understand what failed.
2. Inspect `payload` and `last_error` without leaving the UI.
3. Retry one failed or stuck event by resetting it to `pending`.
4. Retry a selected set of failed or stuck events in one request.
5. Refresh the panel after worker activity without reloading the whole app.

## 2. Non-Goals

- No deletion or hard purge of outbox rows.
- No editing event payloads.
- No automatic retry policy changes.
- No global task-center refactor.
- No batch rollback or cross-standard impact graph work.
- No changes to derivation strategy behavior.
- No new worker process or queue technology.

## 3. Existing Context

Backend:

- `std_outbox` stores `event_type`, `payload`, `attempts`, `last_error`,
  `next_attempt_at`, and `status`.
- `outbox.claim_batch()` only claims `pending` events whose `next_attempt_at`
  is due.
- `outbox.fail()` retries with exponential backoff and marks an event `failed`
  after max attempts.
- `/api/std/outbox/status` currently returns counts by status.

Frontend:

- `DeriveSubTab` already shows derivation strategies, links, status summary, a
  rerun action, and data-model preview.
- `DeriveStatusSummary` shows failed derived-link counts, but not failed
  `std_outbox` events.
- `StandardsTab` already passes `userRole`, so the new panel can be admin-only.

## 4. User Experience

Place a new `OutboxDeadLetterPanel` in `DeriveSubTab`, below the existing status
summary and rerun controls. It is visible only when `userRole === "admin"`.

Panel behavior:

- Header shows counts for `failed`, `pending`, and `in_flight`.
- Default filter is `failed`.
- A compact table lists:
  - checkbox
  - event type
  - status
  - attempts
  - next attempt time
  - created time
  - last error summary
  - action: retry
- Selecting a row opens an inline detail area with formatted `payload` and full
  `last_error`.
- Bulk retry button is enabled only when at least one retryable event is selected.
- Retryable statuses are `failed` and `in_flight`.
- `done` events are read-only.
- `pending` events are listed for visibility but are not retried unless they are
  selected through the bulk API and the backend decides they are retryable.

The panel should be quiet and operational, matching the existing Standards
Platform style. It should not introduce a separate full-screen admin dashboard.

## 5. Backend Design

Add a small repository module:

```text
data_agent/standards_platform/outbox_admin.py
```

Responsibilities:

- `list_events(status=None, event_type=None, limit=50, offset=0) -> list[dict]`
- `get_counts() -> dict[str, int]`
- `retry_event(event_id, by_user) -> dict`
- `retry_events(event_ids, by_user) -> dict`

Retry semantics:

- Only `failed` and `in_flight` events are reset to `pending`.
- `next_attempt_at` is set to `now()`.
- `processed_at` remains unchanged if already null; no successful history is
  overwritten.
- `attempts` and `last_error` are preserved for operator context.
- The response includes `retried`, `skipped`, and a reason per skipped id.
- Each retry writes an audit row through the existing audit mechanism where
  practical. If the local standards routes do not already have a consistent
  audit helper, the repo returns enough detail for route-level logging.

Routes in `data_agent/api/standards_routes.py`:

| Route | Method | Auth | Behavior |
|---|---|---|---|
| `/api/std/outbox/events` | GET | admin | List events, filters: `status`, `event_type`, `limit`, `offset` |
| `/api/std/outbox/events/{event_id}/retry` | POST | admin | Retry one event |
| `/api/std/outbox/events/retry` | POST | admin | Retry selected ids |

The existing `/api/std/outbox/status` remains, but it can call `outbox_admin`
for consistent count logic.

## 6. Frontend Design

Extend:

```text
frontend/src/components/datapanel/standards/standardsApi.ts
frontend/src/components/datapanel/standards/DeriveSubTab.tsx
```

Add:

```text
frontend/src/components/datapanel/standards/derive/OutboxDeadLetterPanel.tsx
```

API wrappers:

- `listOutboxEvents(params)`
- `retryOutboxEvent(eventId)`
- `retryOutboxEvents(eventIds)`
- `getOutboxStatus()`

Component state:

- `statusFilter`: default `failed`
- `events`
- `counts`
- `selectedIds`
- `expandedEventId`
- `busy`
- `error`
- `refreshTick`

The panel should call `onRefreshDerive` only after successful retry when the
parent provides it, so existing derive status can update without a full reload.

## 7. Error Handling

- Non-admin users receive `403`.
- Invalid `limit` or `offset` returns `400`.
- Unknown event id returns `404`.
- Retry of non-retryable status returns `200` with `skipped`, not `500`.
- Database failures return `500` with a short error message and server log
  details.
- Frontend shows API errors inline and keeps the previous table visible.

## 8. Testing Strategy

Use TDD. Write failing tests before production code.

Backend tests:

- `test_outbox_admin.py`
  - lists failed events in newest-first order
  - filters by status and event type
  - retry changes `failed` to `pending` and sets `next_attempt_at <= now()`
  - retry changes stuck `in_flight` to `pending`
  - retry skips `done`
  - bulk retry returns mixed retried/skipped results
- `test_api_standards.py` or a focused `test_api_outbox_admin.py`
  - unauthenticated request returns `401`
  - non-admin returns `403`
  - admin can list events
  - admin can retry one event
  - admin can bulk retry

Frontend verification:

- `npm run build` must pass.
- If the project has no React test harness for this area, TypeScript build is
  the required frontend verification for this slice.

Regression:

- Run `pytest data_agent/standards_platform -q`.
- Run focused API tests before the full package sweep.

## 9. Acceptance Criteria

- Admin can see failed outbox events without SQL.
- Admin can inspect full payload and error details.
- Admin can retry one failed or stuck event.
- Admin can bulk retry selected failed or stuck events.
- `done` events cannot be retried.
- Existing worker behavior remains unchanged.
- Existing Standards Platform tests pass.
- Frontend build passes.

## 10. Open Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Retrying `in_flight` could duplicate work if a worker is still processing it | Limit this to admin action and preserve at-least-once semantics; the existing handlers must remain idempotent |
| Payloads may be large | Render in a scrollable detail area and truncate table summaries |
| Operators may expect delete/purge | Exclude deletion in this slice to preserve auditability |
| Event failures may repeat immediately | Preserve `attempts` and `last_error`, so repeated failures stay visible |

## 11. Implementation Order

1. Backend repository tests and `outbox_admin.py`.
2. API tests and routes.
3. Frontend API wrappers.
4. `OutboxDeadLetterPanel`.
5. `DeriveSubTab` integration.
6. Focused tests, full Standards Platform tests, frontend build.
7. Roadmap update marking v25.4 first P4 slice complete.

# Standards Platform Outbox Admin Hardening Design

- **Status**: Approved for implementation planning
- **Date**: 2026-06-06
- **Scope**: hardening follow-up for v25.4 P4 outbox dead-letter first slice
- **Builds on**: `outbox_admin.py`, `/api/std/outbox/events/*`, and `OutboxDeadLetterPanel`

## 1. Goal

Close the non-blocking review findings from the outbox dead-letter slice before
moving to larger P4 work. The hardening should improve operator feedback,
protect the bulk retry endpoint from accidental large requests, and leave a
durable audit trail for successful admin retries.

## 2. In Scope

1. **Bulk retry cap**: `POST /api/std/outbox/events/retry` accepts at most 200
   event IDs. Larger requests return `400` with a clear validation error.
2. **Durable audit**: each successfully retried `std_outbox` event writes one
   `agent_audit_log` row with action `std_outbox.retry`, username `by_user`,
   and JSON details containing at least `event_id`, `event_type`, and
   `previous_status`.
3. **Frontend retry summary**: the dead-letter panel shows a compact result
   message after single or bulk retry, including skipped reasons when the API
   returns `skipped` with HTTP 200.

## 3. Out of Scope

- No retry policy changes.
- No payload editing, deletion, purge, or automatic replay.
- No worker changes.
- No new audit table or migration.
- No new frontend dependency or component test harness.
- No P4 batch rollback, review-template visualization, or cross-standard impact
  graph work in this slice.

## 4. Backend Design

### Bulk Cap

Add an API-level cap constant in `data_agent/api/standards_routes.py`:

```python
_MAX_OUTBOX_RETRY_IDS = 200
```

After confirming `event_ids` is a non-empty list of non-empty strings, reject
`len(event_ids) > _MAX_OUTBOX_RETRY_IDS` with:

```json
{"error": "event_ids must contain at most 200 ids"}
```

The repository does not need a separate cap because the API is the admin entry
point for UI-initiated bulk retry.

### Durable Audit

Update `data_agent/standards_platform/outbox_admin.py` so `retry_event()` selects
`event_type` and `status` under `FOR UPDATE`. When the event is retryable and the
state update succeeds, insert an audit row in the same transaction:

```sql
INSERT INTO agent_audit_log (username, action, details)
VALUES (:u, 'std_outbox.retry', CAST(:d AS jsonb))
```

Details:

```json
{
  "event_id": "...",
  "event_type": "...",
  "previous_status": "failed"
}
```

The audit row is written only for successful `retried` outcomes, not for missing,
malformed, duplicate, or non-retryable events.

## 5. Frontend Design

Add a `retryMessage` state to `OutboxDeadLetterPanel`.

Single retry:

- If API returns `retried`, show `已重试 1 条事件`.
- If API returns `skipped`, show `未重试: <reason>`.

Bulk retry:

- Show `重试完成: retried N, skipped M`.
- If skipped results exist, append a compact reason summary using the first
  one to three skipped reasons, truncated so it fits in the right rail.

The message should clear when the user changes filters or starts a new retry.
It can share the panel's existing compact inline message style; no toast system
is introduced.

## 6. Testing Strategy

Use TDD for backend behavior.

Repository tests:

- `retry_event()` writes `agent_audit_log` for a successful retry.
- `retry_event()` does not write audit rows for skipped `done` events.

API tests:

- bulk retry rejects 201 IDs with `400` and the exact cap error message.
- bulk retry still accepts 200 IDs and delegates to `_outbox_admin.retry_events`.

Frontend verification:

- `npm run build` is the required verification because this area has no React
  test harness.

Regression:

- Focused backend outbox tests.
- Full `data_agent/standards_platform` test suite.
- Frontend build.

## 7. Acceptance Criteria

- Large accidental bulk retry requests are rejected before repository work.
- Each successful admin retry is visible in durable audit logs.
- Operators can see whether retry calls retried or skipped events without
  opening developer tools.
- Existing worker at-least-once behavior remains unchanged.
- Focused backend tests, full Standards Platform tests, and frontend build pass.

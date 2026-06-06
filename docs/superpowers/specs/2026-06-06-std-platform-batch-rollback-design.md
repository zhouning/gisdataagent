# Standards Platform Batch Rollback First Slice Design

- **Status**: Approved for implementation planning
- **Date**: 2026-06-06
- **Scope**: P4 batch rollback first slice for Standards Platform derivations
- **Builds on**: `link_repo.rollback_version()`, `/api/std/derive/rollback/{version_id}`, and `DeriveSubTab`

## 1. Goal

Add an admin-only batch rollback workflow for derivations so operators can
rollback multiple standards document versions without issuing repeated API calls
or SQL. This first slice reuses the existing single-version rollback semantics:
active `std_derived_link` rows become `superseded`, downstream generated rows
that carry `derived_status` become `stale`, and manual rows remain untouched.

## 2. In Scope

1. **Repository batch helper**: add `link_repo.rollback_versions()` to process a
   list of version IDs in order, skip duplicates and missing/malformed IDs, and
   call existing `rollback_version()` for each valid existing version.
2. **Batch API**: add admin-only `POST /api/std/derive/rollback` with body
   `{version_ids: string[], reason?: string}`.
3. **Typed SDK**: add `rollbackDerivations()` and
   `rollbackDerivationsBatch()` wrappers in `standardsApi.ts`.
4. **Admin UI panel**: add a compact `BatchRollbackPanel` in `DeriveSubTab`.
   It can add the currently selected version ID and also accept pasted IDs.
5. **Roadmap update**: mark P4 batch rollback first slice complete.

## 3. Non-Goals

- No change to `rollback_version()` single-version behavior.
- No transaction spanning all versions; each version remains an independent
  rollback operation through existing repository semantics.
- No cross-document version picker in this slice.
- No automatic impact graph preview before rollback.
- No payload deletion, purge, or physical deletion of derived rows.
- No worker or outbox changes.

## 4. Backend Design

### Repository

Add to `data_agent/standards_platform/derivation/link_repo.py`:

```python
def rollback_versions(*, version_ids: Iterable[str], by_user: str = "system",
                      reason: Optional[str] = None) -> dict:
    ...
```

Response shape:

```json
{
  "rolled_back": [
    {
      "version_id": "...",
      "status": "rolled_back",
      "by_strategy": {"to_qc_rule": {"links_marked": 1, "...": "..."}}
    },
    {
      "version_id": "...",
      "status": "no_active_links",
      "by_strategy": {}
    }
  ],
  "skipped": [
    {"version_id": "...", "reason": "duplicate id"},
    {"version_id": "...", "reason": "not found"}
  ]
}
```

Malformed UUID strings are treated as `not found` to match the outbox admin
slice's operator-facing behavior.

### API

Add `POST /api/std/derive/rollback`:

- auth: admin only
- body: `version_ids` non-empty string list, max 50 IDs
- optional `reason`
- malformed JSON returns `400 {"error": "invalid JSON body"}`
- validation errors:
  - `version_ids must be a non-empty list`
  - `version_ids must contain non-empty strings`
  - `version_ids must contain at most 50 ids`
- default reason: `batch rollback by <username>`

The route delegates to `_link_repo.rollback_versions()` and returns its result.

## 5. Frontend Design

Add `frontend/src/components/datapanel/standards/derive/BatchRollbackPanel.tsx`
and mount it in `DeriveSubTab` for admins only.

Panel behavior:

- shows a compact textarea for version IDs, one per line or comma-separated
- has an optional reason input
- has an "加入当前版本" button when `versionId` is present
- deduplicates parsed IDs before sending
- rollback button disabled for non-admin, no IDs, or busy state
- result summary shows `rolled_back` count and `skipped` count
- details list each rolled-back/no-active/skipped version with reason/status
- calls `onRollbackComplete()` after successful API response so derive status and
  link table refresh

This is intentionally an operations panel, not a full version browser. The
version picker can be added later once P4 impact graph work exposes richer
cross-document context.

## 6. Testing Strategy

Use TDD for backend behavior.

Repository tests:

- successful batch returns one `rolled_back` item and marks links superseded
- duplicate IDs are skipped after the first occurrence
- missing or malformed IDs are skipped as `not found`
- existing version with no active links returns `status: no_active_links`

API tests:

- unauthenticated gets `401`
- non-admin gets `403`
- malformed JSON gets `400`
- empty/non-string/too-many IDs get `400`
- admin happy path delegates to `_link_repo.rollback_versions()` with default
  reason and returns the result

Frontend:

- `npm run build` is required verification; no React test harness exists in this
  area.

Regression:

- focused rollback/API tests
- full `data_agent/standards_platform` suite
- frontend build

## 7. Acceptance Criteria

- Admin can rollback multiple version IDs in one request.
- Duplicate/missing/malformed IDs do not abort the whole batch.
- Existing single-version rollback semantics are preserved.
- The UI can batch rollback pasted IDs and the currently selected version.
- Focused backend tests, full Standards Platform tests, and frontend build pass.

# Standards Platform Market Organization Access First Slice Design

- **Status**: Approved for implementation planning
- **Date**: 2026-06-06
- **Scope**: P5 标准市场多组织共享/权限模型 first slice
- **Builds on**: market catalog, market listing review, authenticated JWT
  metadata, and `MarketSubTab`

## 1. Goal

Add organization-scoped visibility for reviewed market listings. A listing can
be public, organization-scoped, or private. Catalog queries filter approved
listings according to the current user's organization metadata while preserving
legacy released standards that have no listing row.

This slice gives the market a practical first ACL layer without adding a full
tenant/member management subsystem.

## 2. In Scope

1. **Migration**: `088_std_market_listing_org_access.sql`.
2. **Repository**:
   extend `data_agent/standards_platform/market/listings.py` with visibility
   fields and update API.
3. **Catalog integration**:
   `list_market_standards()` filters explicit listing rows by visibility scope.
4. **API**:
   - `POST /api/std/market/listings` accepts visibility settings
   - `PATCH /api/std/market/listings/{listing_id}/visibility`
   - `GET /api/std/market/standards` applies viewer org context
5. **Frontend SDK/UI**:
   submit visibility settings and show listing visibility in the market tab.
6. **Roadmap update**:
   mark P5 organization access first slice complete.

## 3. Non-Goals

- No organization CRUD table.
- No user-to-organization membership management.
- No cross-tenant billing, approval delegation, or marketplace contracts.
- No row-level DB security policies.
- No data copy/install workflow for shared standards.

## 4. Auth Context

Organization id is read from decoded JWT metadata using the first available key:

1. `org_id`
2. `organization_id`
3. `org`
4. `tenant_id`

If no organization id is present, the user can still see public and legacy
catalog entries.

## 5. Data Model

Extend `std_market_listing`:

| Column | Meaning |
|---|---|
| `visibility_scope` | `public`, `organization`, or `private` |
| `owner_org_id` | primary organization for organization-scoped listings |
| `allowed_org_ids` | additional organization ids allowed to view |

Visibility rules:

- no listing row: visible as legacy released catalog item
- `public`: visible to all authenticated users
- `organization`: visible to admin, owner org, or any org in
  `allowed_org_ids`
- `private`: visible to admin, document owner, or listing submitter

Only approved listing rows enter the public catalog path. Submitted, rejected,
and withdrawn listings stay hidden except through admin listing APIs.

## 6. API Design

### `POST /api/std/market/listings`

Body:

```json
{
  "version_id": "...",
  "visibility_scope": "organization",
  "owner_org_id": "org-a",
  "allowed_org_ids": ["org-b"],
  "notes": "optional"
}
```

Defaults:

- `visibility_scope`: `public`
- `owner_org_id`: current user's org metadata when available
- `allowed_org_ids`: `[]`

Rules:

- organization visibility requires an `owner_org_id`
- invalid scope returns 409 from submit repository

### `PATCH /api/std/market/listings/{listing_id}/visibility`

Admin-only endpoint for changing visibility after listing creation.

Body:

```json
{
  "visibility_scope": "organization",
  "owner_org_id": "org-a",
  "allowed_org_ids": ["org-b"]
}
```

## 7. Frontend Design

`MarketSubTab` adds compact visibility controls around listing submission:

- scope selector: public / organization / private
- owner org input
- allowed org ids input
- catalog/review rows show visibility as a chip

The controls stay inside the existing market work surface.

## 8. Testing Strategy

Repository tests:

- public approved listings are visible to all
- organization listings are visible to owner org and admin only
- `allowed_org_ids` grants access to additional orgs
- private listings are visible to owner/submitter/admin
- visibility update changes catalog access

API tests:

- JWT metadata org id is honored by catalog filtering
- submit accepts visibility settings
- visibility patch is admin-only
- invalid visibility returns an error

Frontend:

- `npm run build` verification.

Regression:

- market focused tests
- full `data_agent/standards_platform` suite
- frontend build

## 9. Acceptance Criteria

- Approved market listings can be scoped by organization.
- Catalog filtering uses current user org metadata.
- Existing legacy released market entries remain visible.
- Admin can update listing visibility.
- Focused backend tests, full Standards Platform tests, and frontend build pass.

# Standards Platform Market Review First Slice Design

- **Status**: Approved for implementation planning
- **Date**: 2026-06-06
- **Scope**: P5 标准市场审核 first slice
- **Builds on**: market catalog + diff, market subscriptions,
  released `std_document_version`, authenticated roles, and `MarketSubTab`

## 1. Goal

Add a lightweight market listing review workflow. Editors can submit a released
standard version for market listing review, admins can approve or reject it,
and catalog visibility respects explicit listing decisions while preserving the
legacy behavior for released versions without listing rows.

This slice implements market review metadata and admin decisions only.
Organization sharing and ACLs remain later P5 work.

## 2. In Scope

1. **Migration**: `087_std_market_listing.sql`.
2. **Repository**:
   `data_agent/standards_platform/market/listings.py`.
3. **Catalog integration**:
   default market catalog includes released versions with no listing row
   (`legacy_approved`) or approved listing rows; submitted/rejected rows are
   hidden from the public catalog.
4. **API**:
   - `GET /api/std/market/listings`
   - `POST /api/std/market/listings`
   - `POST /api/std/market/listings/{listing_id}/review`
5. **Frontend SDK/UI**:
   submit listing action and a compact admin review queue in `MarketSubTab`.
6. **Roadmap update**:
   mark P5 market review first slice complete.

## 3. Non-Goals

- No organization/team marketplace ACL.
- No paid marketplace, rating, download/install flow, or sync workflow.
- No notification delivery.
- No multistep approval template; admin decision is a single approve/reject.
- No destructive removal of existing released catalog entries without an
  explicit listing decision.

## 4. Data Model

`std_market_listing`:

| Column | Meaning |
|---|---|
| `id` | listing id |
| `version_id` | submitted released version |
| `document_id` | denormalized parent document for filtering |
| `status` | `submitted`, `approved`, `rejected`, or `withdrawn` |
| `submitted_by`, `submitted_at` | submitter audit fields |
| `reviewed_by`, `reviewed_at` | admin review audit fields |
| `notes` | submitter notes |
| `review_notes` | admin review notes |
| `created_at`, `updated_at` | audit timestamps |

Uniqueness:

- one listing row per `version_id`
- rejected/withdrawn rows can be resubmitted by setting status back to
  `submitted`

Catalog visibility:

- no listing row: visible as `market_status='legacy_approved'`
- approved listing row: visible as `market_status='approved'`
- submitted/rejected/withdrawn listing row: hidden from default catalog

## 5. API Design

### `GET /api/std/market/listings`

Admin-only review queue. Supports `status`, `limit`, and `offset`.

### `POST /api/std/market/listings`

Editor/admin endpoint. Body:

```json
{"version_id": "...", "notes": "optional"}
```

Rules:

- version must exist
- version must be `released`
- duplicate submit reuses the same row and resets it to `submitted`

### `POST /api/std/market/listings/{listing_id}/review`

Admin-only endpoint. Body:

```json
{"decision": "approved", "review_notes": "optional"}
```

Rules:

- decision must be `approved` or `rejected`
- reviewed fields are updated atomically

## 6. Frontend Design

`MarketSubTab` adds:

- submit listing action on the selected market version
- compact "市场审核" queue
- approve/reject controls for submitted listings
- review status chip on catalog entries

The tab remains a work surface and does not add a separate landing page.

## 7. Testing Strategy

Repository tests:

- submit creates a submitted listing for a released version
- submit rejects non-released versions
- explicit submitted listing is hidden from default catalog
- approve makes the listing visible in catalog
- reject keeps the listing hidden and records review metadata
- list supports status filtering

API tests:

- auth and role gates
- submit happy path and validation
- admin list queue
- approve/reject happy path
- invalid decision and missing listing handling

Frontend:

- `npm run build` verification.

Regression:

- focused listing tests
- full `data_agent/standards_platform` suite
- frontend build

## 8. Acceptance Criteria

- Editors can submit released versions for market review.
- Admins can list, approve, and reject submitted listings.
- Catalog hides explicitly submitted/rejected listings until approval.
- Legacy released catalog entries remain visible when no listing row exists.
- Backend focused tests, full Standards Platform tests, and frontend build pass.

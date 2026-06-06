# Standards Platform Market Subscriptions First Slice Design

- **Status**: Approved for implementation planning
- **Date**: 2026-06-06
- **Scope**: P5 标准市场订阅持久化 first slice
- **Builds on**: market catalog + diff, released `std_document_version`,
  `std_document`, authenticated user context, and `MarketSubTab`

## 1. Goal

Add persistent user subscriptions for released standards in the market. A user
can subscribe to a market standard, see their active subscriptions, detect when
a newer released version is available, cancel a subscription, and mark the
latest version as seen.

This slice implements user-level subscriptions only. Organization-level sharing
and ACLs remain a later P5 slice.

## 2. In Scope

1. **Migration**: `086_std_market_subscription.sql`.
2. **Repository**:
   `data_agent/standards_platform/market/subscriptions.py`.
3. **API**:
   - `GET /api/std/market/subscriptions`
   - `POST /api/std/market/subscriptions`
   - `DELETE /api/std/market/subscriptions/{subscription_id}`
   - `POST /api/std/market/subscriptions/{subscription_id}/mark-seen`
4. **Frontend SDK/UI**:
   subscription actions and "我的订阅" panel in `MarketSubTab`.
5. **Roadmap update**:
   mark P5 subscription persistence first slice complete.

## 3. Non-Goals

- No organization/team subscription model.
- No ACL or tenant isolation beyond current authenticated user ownership.
- No notification delivery, email, webhook, or outbox event.
- No paid marketplace or approval workflow.
- No automatic sync/install of subscribed standards.

## 4. Data Model

`std_market_subscription`:

| Column | Meaning |
|---|---|
| `id` | subscription id |
| `subscriber_user_id` | authenticated user id |
| `document_id` | subscribed standard document |
| `source_version_id` | version used when subscription was created/reactivated |
| `last_seen_version_id` | latest released version acknowledged by user |
| `status` | `active` or `cancelled` |
| `notes` | optional user note |
| `created_at`, `updated_at` | audit timestamps |

Uniqueness:

- one row per `(subscriber_user_id, document_id)`
- re-subscribing a cancelled row reactivates it

Update detection:

- list subscriptions joins the latest released version for the subscribed
  document
- `has_update = latest_version_id != last_seen_version_id`

## 5. API Design

### `GET /api/std/market/subscriptions`

Returns active subscriptions for the current user:

```json
{
  "subscriptions": [
    {
      "id": "...",
      "document_id": "...",
      "doc_code": "TD/T-001",
      "title": "标准名称",
      "source_version_id": "...",
      "source_version_label": "v1.0",
      "last_seen_version_id": "...",
      "latest_version_id": "...",
      "latest_version_label": "v1.1",
      "has_update": true,
      "status": "active",
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

### `POST /api/std/market/subscriptions`

Body:

```json
{"version_id": "...", "notes": "optional"}
```

Rules:

- version must exist
- version must be `released`
- subscription is owned by current user
- duplicate subscription reactivates/updates the existing row

### `DELETE /api/std/market/subscriptions/{subscription_id}`

Cancels the current user's subscription. Admin may cancel any subscription.

### `POST /api/std/market/subscriptions/{subscription_id}/mark-seen`

Sets `last_seen_version_id` to the current latest released version of the
subscribed document.

## 6. Frontend Design

`MarketSubTab` adds:

- Subscribe button on selected market item
- "我的订阅" section under the catalog list
- update badge when `has_update=true`
- "标记已读" and "取消订阅" actions

The tab remains operational and compact. It does not introduce a landing page
or marketing-style layout.

## 7. Testing Strategy

Repository tests:

- subscribe creates an active subscription
- subscribe rejects non-released versions
- list returns only active subscriptions for the user
- list marks `has_update=true` when a newer released version exists
- mark seen clears `has_update`
- unsubscribe cancels ownership-scoped subscription

API tests:

- auth required
- subscribe happy path
- subscribe missing/non-released errors
- list current user
- mark seen
- delete subscription

Frontend:

- `npm run build` verification.

Regression:

- focused subscription tests
- full `data_agent/standards_platform` suite
- frontend build

## 8. Acceptance Criteria

- Users can persistently subscribe to released market standards.
- Users can see active subscriptions and update availability.
- Users can cancel and mark latest version as seen.
- Existing market catalog/diff flows remain compatible.
- Focused backend tests, full Standards Platform tests, and frontend build pass.

# Standards Platform Market Catalog + Diff First Slice Design

- **Status**: Approved for implementation planning
- **Date**: 2026-06-06
- **Scope**: P5 标准市场 first slice
- **Builds on**: released `std_document_version`, `std_document`,
  `std_clause`, `std_data_element`, `std_term`, `std_value_domain`,
  `PublishSubTab`, and `standardsApi.ts`

## 1. Goal

Start P5 with a low-risk standards market entry point: users can browse
released standards as shareable market items and compare two released/draft
versions before reuse or fork.

This first slice makes "standard as reusable product" visible without adding a
new cross-organization permission model. It answers:

1. Which standards are available for reuse?
2. What assets does each released version contain?
3. How different is a candidate version from another version?

## 2. In Scope

1. **Market repository**:
   `data_agent/standards_platform/market/catalog.py`.
2. **API**:
   - `GET /api/std/market/standards`
   - `GET /api/std/market/diff?source_version_id=&target_version_id=`
3. **Frontend SDK**:
   typed market catalog and diff functions in `standardsApi.ts`.
4. **Market UI**:
   new `MarketSubTab` in StandardsTab with catalog list and diff panel.
5. **Roadmap update**:
   mark P5 market catalog + diff first slice complete.

## 3. Non-Goals

- No new database tables or migrations.
- No subscription persistence in this slice.
- No organization/tenant ACL model.
- No marketplace approval workflow.
- No billing, ratings, comments, or usage analytics.
- No automatic import/install workflow beyond existing publish/fork APIs.
- No LLM-generated diff explanation.

## 4. API Design

### `GET /api/std/market/standards`

Any authenticated user can read.

Query params:

- `query`: optional text search over `doc_code`, `title`, `version_label`
- `limit`: optional integer, default `50`, maximum `100`
- `offset`: optional integer, default `0`

Response:

```json
{
  "items": [
    {
      "version_id": "...",
      "document_id": "...",
      "doc_code": "TD/T-001",
      "title": "国土空间用途管制标准",
      "source_type": "industry",
      "owner_user_id": "admin",
      "tags": ["自然资源"],
      "version_label": "v1.0",
      "released_at": "2026-06-06T...",
      "released_by": "admin",
      "supersedes_version_id": null,
      "asset_counts": {
        "clauses": 12,
        "data_elements": 31,
        "terms": 8,
        "value_domains": 4
      }
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### `GET /api/std/market/diff`

Any authenticated user can read.

Required query params:

- `source_version_id`
- `target_version_id`

Response:

```json
{
  "source_version_id": "...",
  "target_version_id": "...",
  "source": {"doc_code": "A", "version_label": "v1.0"},
  "target": {"doc_code": "A", "version_label": "v1.1"},
  "summary": {
    "added": 2,
    "removed": 1,
    "changed": 3,
    "unchanged": 20,
    "by_asset_type": {
      "clauses": {"added": 1, "removed": 0, "changed": 1, "unchanged": 8},
      "data_elements": {"added": 1, "removed": 1, "changed": 2, "unchanged": 12}
    }
  },
  "changes": [
    {
      "asset_type": "clauses",
      "key": "1.1",
      "change_type": "changed",
      "source_label": "1.1 术语",
      "target_label": "1.1 术语与定义"
    }
  ]
}
```

Diff identity keys:

| Asset type | Identity |
|---|---|
| clauses | `clause_no` if present, otherwise `ordinal_path` |
| data_elements | `code` |
| terms | `term_code` |
| value_domains | `code` |

Changed detection compares stable content fields only, not IDs/timestamps.

## 5. Frontend Design

`StandardsTab` gains a new sub-tab:

```text
采集 | 分析 | 起草 | 审定 | 发布 | 派生 | 市场
```

`MarketSubTab` layout:

- left catalog list of released market items
- right detail/diff panel
- source version defaults to the globally selected version when present
- target version defaults to the selected market item
- user can run diff between the selected source and target
- user can pick a market item as the active version for other tabs

The UI stays compact and operational, matching the existing Standards Platform
style. No marketing landing page is introduced.

## 6. Testing Strategy

Use TDD for backend behavior.

Repository tests:

- catalog lists only released versions
- catalog supports query filter and pagination
- catalog includes asset counts
- diff reports added/removed/changed/unchanged across clauses and data elements
- missing source/target version raises `LookupError`

API tests:

- unauthenticated requests get `401`
- invalid limit/offset returns `400`
- catalog happy path returns items
- diff requires both version IDs
- missing version returns `404`
- diff happy path returns summary and changes

Frontend:

- `npm run build` is required verification.

Regression:

- focused market backend tests
- full `data_agent/standards_platform` suite
- frontend build

## 7. Acceptance Criteria

- Released standards can be browsed from a new Market sub-tab.
- Market items expose useful metadata and asset counts.
- Two standard versions can be compared through a deterministic diff API.
- Existing publish/fork/review/derive flows remain unchanged.
- Focused backend tests, full Standards Platform tests, and frontend build pass.

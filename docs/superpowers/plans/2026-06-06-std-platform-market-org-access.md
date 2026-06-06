# Standards Platform Market Organization Access Implementation Plan

> **For agentic workers:** Keep this first slice scoped to market listing
> visibility. Do not introduce full tenant/member management.

**Goal:** Add organization-scoped visibility for reviewed market listings.

**Architecture:** Extend `std_market_listing`, pass viewer org metadata from
market routes into catalog queries, and add compact visibility controls in
`MarketSubTab`.

---

## Scope Check

This plan implements only the first organization access slice from
`docs/superpowers/specs/2026-06-06-std-platform-market-org-access-design.md`.
It does not add organization CRUD, memberships, billing, or data installation.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `data_agent/migrations/088_std_market_listing_org_access.sql` | Create | Add visibility columns |
| `data_agent/standards_platform/market/listings.py` | Modify | Submit/update visibility |
| `data_agent/standards_platform/market/catalog.py` | Modify | Catalog ACL filtering |
| `data_agent/standards_platform/tests/test_market_org_access.py` | Create | Repository tests |
| `data_agent/api/standards_routes.py` | Modify | Market org context + visibility endpoint |
| `data_agent/standards_platform/tests/test_api_market_org_access.py` | Create | API tests |
| `frontend/src/components/datapanel/standards/standardsApi.ts` | Modify | Visibility SDK fields/functions |
| `frontend/src/components/datapanel/standards/MarketSubTab.tsx` | Modify | Visibility controls |
| `docs/roadmap.md` | Modify | Mark slice complete |

---

## Task 1: Design Documents

- [ ] Add spec and implementation plan
- [ ] Commit

```powershell
git add docs\superpowers\specs\2026-06-06-std-platform-market-org-access-design.md docs\superpowers\plans\2026-06-06-std-platform-market-org-access.md
git commit -m "docs(std-platform): add market org access design"
```

---

## Task 2: Repository + Migration

- [ ] Add repository tests
- [ ] Add migration and repository/catalog changes
- [ ] Run focused tests
- [ ] Commit

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_market_org_access.py -q --basetemp .pytest_market_org_access_repo_tmp
git add data_agent\migrations\088_std_market_listing_org_access.sql data_agent\standards_platform\market\listings.py data_agent\standards_platform\market\catalog.py data_agent\standards_platform\tests\test_market_org_access.py
git commit -m "feat(std-platform): add market organization access repository"
```

---

## Task 3: API

- [ ] Add API tests
- [ ] Add market org context and visibility endpoint
- [ ] Run API focused tests
- [ ] Commit

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_market_org_access.py -q --basetemp .pytest_market_org_access_api_tmp
git add data_agent\api\standards_routes.py data_agent\standards_platform\tests\test_api_market_org_access.py
git commit -m "feat(std-platform): expose market organization access API"
```

---

## Task 4: Frontend

- [ ] Add SDK fields/functions
- [ ] Add compact visibility controls
- [ ] Run frontend build
- [ ] Commit

```powershell
cd frontend
npm run build
cd ..
git add frontend\src\components\datapanel\standards\standardsApi.ts frontend\src\components\datapanel\standards\MarketSubTab.tsx
git commit -m "feat(std-platform-fe): add market organization access controls"
```

---

## Task 5: Regression + Roadmap

- [ ] Market focused tests
- [ ] Full standards platform tests
- [ ] Frontend build
- [ ] Update roadmap to `v25.11`
- [ ] Commit roadmap
- [ ] Push `feat/v12-extensible-platform`

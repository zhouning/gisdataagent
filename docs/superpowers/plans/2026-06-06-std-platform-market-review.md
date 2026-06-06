# Standards Platform Market Review Implementation Plan

> **For agentic workers:** Implement task-by-task. Use focused tests for each
> backend step before running full regression.

**Goal:** Add a lightweight market listing review workflow for released
standards.

**Architecture:** Add `std_market_listing`, a listing repository, admin/editor
REST endpoints, catalog visibility integration, and compact UI controls inside
`MarketSubTab`. Keep organization ACLs for a later P5 slice.

---

## Scope Check

This plan implements only the first market review slice from
`docs/superpowers/specs/2026-06-06-std-platform-market-review-design.md`.
It does not add organization sharing, tenant ACLs, notifications, or paid
marketplace workflows.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `data_agent/migrations/087_std_market_listing.sql` | Create | Listing review table |
| `data_agent/standards_platform/market/listings.py` | Create | Listing repository |
| `data_agent/standards_platform/market/catalog.py` | Modify | Catalog review status and visibility |
| `data_agent/standards_platform/tests/test_market_listings.py` | Create | Repository tests |
| `data_agent/api/standards_routes.py` | Modify | Listing REST endpoints |
| `data_agent/standards_platform/tests/test_api_market_listings.py` | Create | API tests |
| `frontend/src/components/datapanel/standards/standardsApi.ts` | Modify | Typed SDK |
| `frontend/src/components/datapanel/standards/MarketSubTab.tsx` | Modify | Review UI |
| `docs/roadmap.md` | Modify | Mark slice complete |

---

## Task 1: Design Documents

- [ ] Add spec and implementation plan
- [ ] Commit

```powershell
git add docs\superpowers\specs\2026-06-06-std-platform-market-review-design.md docs\superpowers\plans\2026-06-06-std-platform-market-review.md
git commit -m "docs(std-platform): add market review design"
```

---

## Task 2: Repository + Migration

- [ ] Add repository tests
- [ ] Run focused test
- [ ] Add migration, listing repository, and catalog visibility integration
- [ ] Run focused test
- [ ] Commit

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_market_listings.py -q --basetemp .pytest_market_listings_repo_tmp
git add data_agent\migrations\087_std_market_listing.sql data_agent\standards_platform\market\listings.py data_agent\standards_platform\market\catalog.py data_agent\standards_platform\tests\test_market_listings.py
git commit -m "feat(std-platform): add market listing review repository"
```

---

## Task 3: API

- [ ] Add API tests
- [ ] Add endpoints in `standards_routes.py`
- [ ] Run API focused tests
- [ ] Commit

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_market_listings.py -q --basetemp .pytest_market_listings_api_tmp
git add data_agent\api\standards_routes.py data_agent\standards_platform\tests\test_api_market_listings.py
git commit -m "feat(std-platform): expose market listing review API"
```

---

## Task 4: Frontend

- [ ] Add listing SDK types/functions
- [ ] Add submit/review controls in `MarketSubTab`
- [ ] Run frontend build
- [ ] Commit

```powershell
cd frontend
npm run build
cd ..
git add frontend\src\components\datapanel\standards\standardsApi.ts frontend\src\components\datapanel\standards\MarketSubTab.tsx
git commit -m "feat(std-platform-fe): add market review controls"
```

---

## Task 5: Regression + Roadmap

- [ ] Focused tests
- [ ] Full standards platform tests
- [ ] Frontend build
- [ ] Update roadmap to `v25.10`
- [ ] Commit roadmap
- [ ] Final status check

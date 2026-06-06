# Standards Platform Market Subscriptions Implementation Plan

> **For agentic workers:** Implement task-by-task. Use TDD for backend tasks.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent user-level subscriptions for released standards in the
market.

**Architecture:** Add `std_market_subscription`, repository methods,
authenticated REST endpoints, and UI controls inside `MarketSubTab`. Keep
organization-level sharing for a later P5 slice.

---

## Scope Check

This plan implements only the first subscription persistence slice from
`docs/superpowers/specs/2026-06-06-std-platform-market-subscriptions-design.md`.
It does not add organization ACLs, notification delivery, or automatic sync.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `data_agent/migrations/086_std_market_subscription.sql` | Create | Subscription table |
| `data_agent/standards_platform/market/subscriptions.py` | Create | Subscription repository |
| `data_agent/standards_platform/tests/test_market_subscriptions.py` | Create | Repository tests |
| `data_agent/api/standards_routes.py` | Modify | Subscription REST endpoints |
| `data_agent/standards_platform/tests/test_api_market_subscriptions.py` | Create | API tests |
| `frontend/src/components/datapanel/standards/standardsApi.ts` | Modify | Typed SDK |
| `frontend/src/components/datapanel/standards/MarketSubTab.tsx` | Modify | Subscription UI |
| `docs/roadmap.md` | Modify | Mark slice complete |

---

## Task 1: Design Documents

- [ ] Add spec and implementation plan
- [ ] Commit

```powershell
git add docs\superpowers\specs\2026-06-06-std-platform-market-subscriptions-design.md docs\superpowers\plans\2026-06-06-std-platform-market-subscriptions.md
git commit -m "docs(std-platform): add market subscriptions design"
```

---

## Task 2: Repository + Migration

- [ ] Write failing repository tests
- [ ] Run RED:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_market_subscriptions.py -v --basetemp .pytest_market_subs_task1_tmp
```

- [ ] Add migration and `subscriptions.py`
- [ ] Run GREEN
- [ ] Commit:

```powershell
git add data_agent\migrations\086_std_market_subscription.sql data_agent\standards_platform\market\subscriptions.py data_agent\standards_platform\tests\test_market_subscriptions.py
git commit -m "feat(std-platform): add market subscription repository"
```

---

## Task 3: API

- [ ] Write failing API tests
- [ ] Run RED:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_api_market_subscriptions.py -v --basetemp .pytest_market_subs_task2_tmp
```

- [ ] Add endpoints in `standards_routes.py`
- [ ] Run GREEN
- [ ] Commit:

```powershell
git add data_agent\api\standards_routes.py data_agent\standards_platform\tests\test_api_market_subscriptions.py
git commit -m "feat(std-platform): expose market subscription API"
```

---

## Task 4: Frontend

- [ ] Add subscription SDK types/functions
- [ ] Add subscription panel/actions in `MarketSubTab`
- [ ] Run build:

```powershell
cd frontend
npm run build
```

- [ ] Commit:

```powershell
cd ..
git add frontend\src\components\datapanel\standards\standardsApi.ts frontend\src\components\datapanel\standards\MarketSubTab.tsx
git commit -m "feat(std-platform-fe): add market subscriptions"
```

---

## Task 5: Regression + Roadmap

- [ ] Focused tests:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform\tests\test_market_subscriptions.py data_agent\standards_platform\tests\test_api_market_subscriptions.py -q --basetemp .pytest_market_subs_focus_tmp
```

- [ ] Full standards platform:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\standards_platform -q --basetemp .pytest_market_subs_full_tmp
```

- [ ] Frontend build:

```powershell
cd frontend
npm run build
```

- [ ] Update roadmap to `v25.9`
- [ ] Commit roadmap
- [ ] Final status check

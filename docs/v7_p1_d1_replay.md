# D1 Replay — Evaluator with limit-unstable fallback

Records replayed: **312**
Rescued (old=fail, new=pass): **44**
Newly failed (old=pass, new=fail): **0**
Net rescue: **44**

## Per-qid pass count (old → new)

| qid | old pass | new pass | total | Δ |
|---|---|---|---|---|
| `CQ_GEO_EASY_02` | 0 | 0 | 22 | +0 |
| `CQ_GEO_EASY_10` | 0 | 24 | 24 | +24 |
| `CQ_GEO_EASY_20` | 0 | 0 | 24 | +0 |
| `CQ_GEO_EASY_24` | 0 | 0 | 24 | +0 |
| `CQ_GEO_MEDIUM_05` | 0 | 0 | 24 | +0 |
| `CQ_GEO_MEDIUM_08` | 0 | 20 | 24 | +20 |
| `CQ_GEO_MEDIUM_10` | 0 | 0 | 24 | +0 |
| `CQ_GEO_MEDIUM_20` | 0 | 0 | 24 | +0 |
| `CQ_GEO_MEDIUM_26` | 0 | 0 | 23 | +0 |
| `CQ_GEO_HARD_10` | 0 | 0 | 10 | +0 |
| `CQ_GEO_HARD_12` | 0 | 0 | 23 | +0 |
| `CQ_GEO_HARD_15` | 0 | 0 | 20 | +0 |
| `CQ_GEO_HARD_22` | 0 | 0 | 22 | +0 |
| `CQ_GEO_HARD_23` | 0 | 0 | 24 | +0 |

## Sample rescues (first 30)

| qid | family | sample | old_reason | new_reason |
|---|---|---|---|---|
| `CQ_GEO_EASY_10` | deepseek-v4-flash | sample_1 | `rowset mismatch` | `match` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-flash | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | deepseek-v4-flash | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-flash | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | deepseek-v4-flash | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-flash | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | deepseek-v4-pro | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-pro | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | deepseek-v4-pro | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-pro | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | deepseek-v4-pro | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-pro | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | gemini-2.5-flash | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | gemini-2.5-flash | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | gemini-2.5-flash | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | gemini-2.5-flash | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | gemini-2.5-flash | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | gemini-2.5-flash | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | gemini-2.5-pro | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | gemini-2.5-pro | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | gemini-2.5-pro | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_EASY_10` | gemini-2.5-pro | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | gemini-2.5-pro | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | gemini-3.1-flash-lite-preview | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | gemini-3.1-flash-lite-preview | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | gemini-3.1-flash-lite-preview | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | gemini-3.1-flash-lite-preview | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | gemini-3.1-flash-lite-preview | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | gemini-3.1-flash-lite-preview | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_10` | gemini-3.1-pro-preview | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |

# D1 Replay — Evaluator with limit-unstable fallback

Records replayed: **312**
Rescued (old=fail, new=pass): **125**
Newly failed (old=pass, new=fail): **0**
Net rescue: **125**

## Per-qid pass count (old → new)

| qid | old pass | new pass | total | Δ |
|---|---|---|---|---|
| `CQ_GEO_EASY_02` | 0 | 0 | 22 | +0 |
| `CQ_GEO_EASY_10` | 0 | 24 | 24 | +24 |
| `CQ_GEO_EASY_20` | 0 | 17 | 24 | +17 |
| `CQ_GEO_EASY_24` | 0 | 23 | 24 | +23 |
| `CQ_GEO_MEDIUM_05` | 0 | 14 | 24 | +14 |
| `CQ_GEO_MEDIUM_08` | 0 | 20 | 24 | +20 |
| `CQ_GEO_MEDIUM_10` | 0 | 10 | 24 | +10 |
| `CQ_GEO_MEDIUM_20` | 0 | 16 | 24 | +16 |
| `CQ_GEO_MEDIUM_26` | 0 | 0 | 23 | +0 |
| `CQ_GEO_HARD_10` | 0 | 0 | 10 | +0 |
| `CQ_GEO_HARD_12` | 0 | 0 | 23 | +0 |
| `CQ_GEO_HARD_15` | 0 | 0 | 20 | +0 |
| `CQ_GEO_HARD_22` | 0 | 1 | 22 | +1 |
| `CQ_GEO_HARD_23` | 0 | 0 | 24 | +0 |

## Sample rescues (first 30)

| qid | family | sample | old_reason | new_reason |
|---|---|---|---|---|
| `CQ_GEO_MEDIUM_05` | deepseek-v4-flash | sample_1 | `col count: gold=2 pred=3` | `match` |
| `CQ_GEO_EASY_10` | deepseek-v4-flash | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-flash | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_24` | deepseek-v4-flash | sample_1 | `rowset mismatch` | `match` |
| `CQ_GEO_MEDIUM_05` | deepseek-v4-flash | sample_2 | `col count: gold=2 pred=3` | `match` |
| `CQ_GEO_EASY_10` | deepseek-v4-flash | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-flash | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_MEDIUM_20` | deepseek-v4-flash | sample_2 | `rowset mismatch` | `match` |
| `CQ_GEO_MEDIUM_05` | deepseek-v4-flash | sample_3 | `col count: gold=2 pred=3` | `match` |
| `CQ_GEO_EASY_10` | deepseek-v4-flash | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-flash | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_MEDIUM_20` | deepseek-v4-flash | sample_3 | `rowset mismatch` | `match` |
| `CQ_GEO_EASY_24` | deepseek-v4-flash | sample_3 | `rowset mismatch` | `match` |
| `CQ_GEO_MEDIUM_05` | deepseek-v4-pro | sample_1 | `col count: gold=2 pred=3` | `match` |
| `CQ_GEO_EASY_10` | deepseek-v4-pro | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-pro | sample_1 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_EASY_20` | deepseek-v4-pro | sample_1 | `rowset mismatch` | `match` |
| `CQ_GEO_MEDIUM_20` | deepseek-v4-pro | sample_1 | `rowset mismatch` | `match` |
| `CQ_GEO_EASY_24` | deepseek-v4-pro | sample_1 | `rowset mismatch` | `match` |
| `CQ_GEO_HARD_22` | deepseek-v4-pro | sample_1 | `row count: gold=12 pred=11` | `match` |
| `CQ_GEO_MEDIUM_05` | deepseek-v4-pro | sample_2 | `col count: gold=2 pred=3` | `match` |
| `CQ_GEO_EASY_10` | deepseek-v4-pro | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-pro | sample_2 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_MEDIUM_10` | deepseek-v4-pro | sample_2 | `col count: gold=1 pred=4` | `match` |
| `CQ_GEO_MEDIUM_20` | deepseek-v4-pro | sample_2 | `rowset mismatch` | `match` |
| `CQ_GEO_EASY_24` | deepseek-v4-pro | sample_2 | `rowset mismatch` | `match` |
| `CQ_GEO_MEDIUM_05` | deepseek-v4-pro | sample_3 | `col count: gold=2 pred=3` | `match` |
| `CQ_GEO_EASY_10` | deepseek-v4-pro | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (50/50 match))` |
| `CQ_GEO_MEDIUM_08` | deepseek-v4-pro | sample_3 | `rowset mismatch` | `match (limit-unstable: pred is subset of gold-unbounded (20/20 match))` |
| `CQ_GEO_MEDIUM_10` | deepseek-v4-pro | sample_3 | `col count: gold=1 pred=4` | `match` |

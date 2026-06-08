# Model Family Baseline vs Full Comparison

Selection rule: latest complete 125/125 summary for each model and mode; smoke/partial runs excluded.

| Series  | Model | Baseline EX / Acc | Full EX / Acc   | Acc Delta | Baseline Valid  | Full Valid      | Baseline min | Full min |
| ------- | ----- | ----------------- | --------------- | --------- | --------------- | --------------- | ------------ | -------- |
| Gemma4  | e2b   | 37/125 (29.6%)    | 82/125 (65.6%)  | +36.0 pp  | 82/125 (65.6%)  | 108/125 (86.4%) | 7.39         | 21.22    |
| Gemma4  | e4b   | 42/125 (33.6%)    | 80/125 (64.0%)  | +30.4 pp  | 95/125 (76.0%)  | 110/125 (88.0%) | 6.75         | 13.49    |
| Gemma4  | 12b   | 62/125 (49.6%)    | 99/125 (79.2%)  | +29.6 pp  | 98/125 (78.4%)  | 110/125 (88.0%) | 7.21         | 16.68    |
| Gemma4  | 26b   | 68/125 (54.4%)    | 113/125 (90.4%) | +36.0 pp  | 110/125 (88.0%) | 117/125 (93.6%) | 7.47         | 13.05    |
| Gemma4  | 31b   | 69/125 (55.2%)    | 114/125 (91.2%) | +36.0 pp  | 119/125 (95.2%) | 117/125 (93.6%) | 13.92        | 20.04    |
| Qwen3.6 | 27b   | 71/125 (56.8%)    | 82/125 (65.6%)  | +8.8 pp   | 107/125 (85.6%) | 95/125 (76.0%)  | 14.38        | 62.44    |
| Qwen3.6 | 35b   | 69/125 (55.2%)    | 98/125 (78.4%)  | +23.2 pp  | 103/125 (82.4%) | 113/125 (90.4%) | 3.83         | 31.65    |

## Source Summaries

- Gemma4 e2b baseline: `data_agent\nl2sql_eval_results\family12_gemma4_e2b_host228_productized_both_2026-06-06_132040\baseline_summary.json`
- Gemma4 e2b full: `data_agent\nl2sql_eval_results\family12_gemma4_e2b_host228_productized_both_2026-06-06_132040\full_summary.json`
- Gemma4 e4b baseline: `data_agent\nl2sql_eval_results\family12_gemma4_e4b_host228_productized_both_2026-06-06_125415\baseline_summary.json`
- Gemma4 e4b full: `data_agent\nl2sql_eval_results\family12_gemma4_e4b_host228_productized_both_2026-06-06_125415\full_summary.json`
- Gemma4 12b baseline: `data_agent\nl2sql_eval_results\family12_gemma4_12b_host228_productized_both_2026-06-05_204210\baseline_summary.json`
- Gemma4 12b full: `data_agent\nl2sql_eval_results\family12_gemma4_12b_host228_productized_full_2026-06-05_233828\full_summary.json`
- Gemma4 26b baseline: `data_agent\nl2sql_eval_results\family12_gemma4_26b_host228_productized_baseline_2026-06-03_135931\baseline_summary.json`
- Gemma4 26b full: `data_agent\nl2sql_eval_results\family12_gemma4_26b_host228_productized_full_2026-06-03_183313\full_summary.json`
- Gemma4 31b baseline: `data_agent\nl2sql_eval_results\family12_gemma4_31b_host228_productized_baseline_2026-06-06_135836\baseline_summary.json`
- Gemma4 31b full: `data_agent\nl2sql_eval_results\family12_gemma4_31b_host228_productized_full_2026-06-05_201126\full_summary.json`
- Qwen3.6 27b baseline: `data_agent\nl2sql_eval_results\family13_qwen36_27b_host228_productized_both_2026-06-07_155521\baseline_summary.json`
- Qwen3.6 27b full: `data_agent\nl2sql_eval_results\family13_qwen36_27b_host228_productized_both_2026-06-07_155521\full_summary.json`
- Qwen3.6 35b baseline: `data_agent\nl2sql_eval_results\family13_qwen36_35b_host228_productized_both_2026-06-06_202034\baseline_summary.json`
- Qwen3.6 35b full: `data_agent\nl2sql_eval_results\family13_qwen36_35b_host228_productized_full_2026-06-07_131510\full_summary.json`

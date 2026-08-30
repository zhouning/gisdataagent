# ADR-241: JQDLTB 质量修复采用只读诊断和审批门

## Status

Accepted

## Date

2026-08-22

## Context

AR-0 首条切片的全量 JQDLTB source-quality gate 仍失败：配置的 `BSM` 不是唯一键，`TBMJ`/`TBDLMJ` 各有 6 条非正值，7 条记录的声明面积超过 1% 偏差，标准要求的 `SJNF` 和 `MSSM` 没有已批准的推导语义。

诊断发现 `TBBH` 在当前冻结 bundle 中 1,555/1,555 完整且唯一，但它只是技术候选，不能由平台自动提升为业务主键。源文件是客户/业务数据，工程侧也不能擅自用几何面积覆盖声明面积，或用固定年份/默认说明填入标准字段。

## Options Considered

| 方案 | 优点 | 风险 | 结论 |
|---|---|---|---|
| 原地改写 Shapefile 并继续发布 | 快速得到可用字段 | 丢失原始事实、无法证明业务语义和修复责任 | 不选 |
| 根据唯一性和字段名称自动推断所有修复 | 自动化程度高 | 把技术相关性误当业务权威，可能产生错误 ProductVersion | 不选 |
| 生成带 checksum 的聚合诊断，等待批准后编译 transformation contract | 保留 Raw 真值，修复可审计、可回放、可回滚 | 需要业务/数据责任人及时给出决定 | **选择** |

## Decision

1. `scripts/diagnose_chongqing_jqdltb_quality_repairs.py` 只读加载已封存 bundle，输出聚合字段画像、候选键、数值/面积计数、标准推导候选和待审批动作。
2. 诊断报告明确 `source_values_persisted=false`、`source_bytes_modified=false`、`auto_repair=false`、`promotion_ready=false`，并以 `diagnostic_sha256` 绑定到 AR-0 machine Manifest。
3. `TBBH` 只登记为 `technical_unique_candidate_requires_business_approval`；未取得批准前不替换 `BSM`，不生成 canonical ID。
4. 非正面积记录进入“更正或隔离”的审批选项；几何面积只作为 evidence，不覆盖 `TBMJ` 或 `TBDLMJ`。
5. `SJNF`、`MSSM` 保持 `pending_approval`，不从空字段、文件目录年份或默认常量自动推导。
6. 批准后必须创建新的版本化 transformation contract，保留 Raw 输入、修复前后字段映射、quarantine/reconciliation 结果、QualityResult、Lineage 和 rollback pointer，然后重跑 source-quality protocol。

## Rationale

- 现有 source-onboarding 已能稳定发现问题；缺口是把问题变成可决策的修复边界，而不是再添加旁路数据 authority。
- 诊断结果只暴露聚合数字和字段画像，避免把客户源值、绝对路径和临时身份写入证据。
- 机器 Manifest 校验 checksum 和预期计数，防止人工修改报告后仍被当作冻结事实。

## Trade-offs

- 在业务批准到达前，AR-0 不能 promotion，工程不能用默认值“先跑起来”。
- 诊断不会直接降低 blocker 数量；它把下一步变成可指派的业务/治理决策。
- 如果批准策略改变输入身份、标准版本或质量阈值，必须创建新的 Manifest 版本，不能覆盖当前失败证据。

## Evidence

- [JQDLTB quality repair diagnostic](../../benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json)
- [AR-0 machine Manifest](../../config/freezes/ar0-first-vertical-slice-2026-08-22.json)
- [AR-0 Freeze Manifest](../freezes/2026-08-22-ar0-first-vertical-slice-freeze.md)
- Diagnostic + source-onboarding tests: `8 passed`
- Diagnostic SHA-256: `da192c3f443f41cb189c3253473918000acbc8f9c087868e9eb702a4a4520b11`

## Revisit Triggers

- 业务责任人批准 `TBBH` 的 canonical key 语义；
- 数据责任人批准面积更正/隔离和 `SJNF`/`MSSM` 推导；
- source bundle、标准版本或质量阈值变化；
- 需要将诊断动作升级为 DataOps command、quarantine worker 或 DataProductVersion 发布流程。

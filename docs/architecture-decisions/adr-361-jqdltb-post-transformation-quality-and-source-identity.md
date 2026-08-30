# ADR-361: JQDLTB Post-Transformation Quality and Source Identity Recheck

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-30

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

AR-0 已经有真实源 onboarding 诊断，但批准后的 JQDLTB transformation executor 原先只在
合同层比较 source bundle SHA，物化后只输出 4 个简化检查。这样无法证明运行时读取的 sidecar
字节仍是批准对象，也无法阻止“全部记录被隔离后空集合通过”或几何/面积/标准字段漏检。

## 决策

在任何输出目录创建前，executor 对真实 `.shp` 输入执行 source bundle identity 两次：读取前一次，
读取 features 后再一次。两次 bundle identity 必须相同，且与 approved contract 的 `bundle_sha256`
一致；不一致直接 fail closed。JSON/CSV 只作为明确的合成测试 fixture，不声称 Shapefile bundle 证明。

物化后的 candidate quality 使用 `gda.jqdltb_transformation:v1` 规则，至少包含 10 项检查：

- records reconciliation；
- materialized records 非空；
- canonical key 完整且唯一；
- `TBMJ/TBDLMJ` 为正；
- approved derivations 完整；
- business corrections 完整；
- geometry 有效且非空；
- standardization fields 完整；
- quarantine reason code 合法；
- area policy 确实执行。

area policy 不从最终输出字段或单一 quarantine reason 反推。物化阶段分别记录偏差总数、保留源值、
几何替换和隔离的实际处理数，再按 approved policy 做精确对账。这样同一记录即使先处理面积偏差、
随后因非正面积等更高优先级原因进入隔离，也不会漏掉前一项策略执行；任一偏差没有对应处理计数，
质量门直接失败。

结果声明范围为 `post_transformation_candidate_full_dataset`。空 materialized 集合即失败，不能因为
每条记录都被隔离而得到 passed。QualityResult 仍独立于 scheduler/provider 状态，且不会自动创建
DataProductVersion。

## 证据

- [executor](../../data_agent/jqdltb_transformation_executor.py)
- [executor tests](../../data_agent/test_jqdltb_transformation_executor.py)
- [AR-0 Freeze Manifest](../freezes/2026-08-22-ar0-first-vertical-slice-freeze.md)

验证：JQDLTB transformation、DataOps、release、approval workflow、scheduler plan 聚焦回归
`43 passed`；新源 identity 漂移、全隔离空集合、偏差处理计数不完整、三种面积策略和既有审批门
均有测试。Ruff、compileall 和 diff check 通过。

## 边界

这项改动只完善批准后的运行时证据，不制造业务批准、语义 rule、真实生产环境或 DataProductVersion。
当前冻结源仍未有 approved strategy，AR-0 仍保持 `awaiting_business_approval`，source-quality 仍为
`failed`。

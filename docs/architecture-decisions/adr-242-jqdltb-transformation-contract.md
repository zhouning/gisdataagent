# ADR-242: JQDLTB Transformation Contract 采用审批绑定的 fail-closed 执行门

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-23

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

JQDLTB 的只读诊断已经把首条纵切片的事实固定下来：`BSM` 不是唯一键，`TBBH` 是完整且唯一的技术候选；`TBMJ/TBDLMJ` 各有 6 条非正值；7 条记录的声明面积超出 1% 偏差；`SJNF/MSSM` 没有已批准的语义推导。此前只有诊断结果，工程仍缺一份能承接业务决定、又不会提前执行的 transformation contract。

## 决策

新增 `JqdltbTransformationContract`，纳入 `platform_contracts` 的统一不可变 contract 注册表。Contract 固定：

- archive SHA-256、bundle SHA-256、标准版本/标准指纹、源 `ResourceVersion`；
- 质量诊断 SHA-256 和候选 canonical key（当前只能提交 `TBBH`）；
- 非正面积处理、面积偏差处理、`SJNF/MSSM` 推导规则三个策略组；选择业务更正时必须绑定更正数据的 `ResourceVersion` 与内容指纹，选择几何面积时必须绑定面积计算规则与指纹，每个批准的字段推导也必须绑定语义合同指纹；
- `plan_sha256` 与完整 `contract_sha256`；
- 执行态必须带独立人工 `ApprovalCase` 引用，并且批准人批准的正是同一 `plan_sha256`。

Contract 有三个有意分开的状态：

1. `approval_required`：冻结输入和未决项，策略值保持为空，不能提交 ApprovalCase。
2. `dry_run`：保存一份完整策略提案，可以生成 pending ApprovalCase，但不能执行。ApprovalCase 的 target fingerprint 和 request context 都绑定该提案。
3. `execute`：只能从原 `dry_run` proposal 和 authority 返回的 approved ApprovalCase 编译，不接受策略覆盖；真正执行前必须从 PostgreSQL authority 重读相同 ApprovalCase，并重新校验所有输入 checksum、诊断指纹和 source `ResourceVersion`。

执行校验对任何漂移 fail closed；几何面积仍是证据，不会被当作业务权威值自动覆盖源字段。

## 取舍

- **把策略写进普通配置**：实现快，但审批边界不可审计，容易出现“配置改了就执行”。拒绝。
- **直接修改诊断或源数据**：破坏只读证据与回放能力。拒绝。
- **使用独立 contract 并绑定审批**：多一个版本化对象，但能让业务决定、输入身份和执行结果一一对应，适合后续 Raw→ADS 重放。

## 证据

- [AR-0 transformation contract](../../config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json)
- [AR-0 machine Manifest](../../config/freezes/ar0-first-vertical-slice-2026-08-22.json)
- [JQDLTB quality repair diagnostic](../../benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json)
- [Contract implementation](../../data_agent/platform_contracts.py)
- [Contract tests](../../data_agent/test_jqdltb_transformation_contract.py)
- [Approval workflow](../../scripts/manage_chongqing_jqdltb_transformation_approval.py)
- [Approval authority service](../../data_agent/jqdltb_transformation_approval.py)
- [Approval packet](../freezes/2026-08-23-jqdltb-transformation-approval-packet.md)

## 重评触发条件

- 业务批准的 canonical key 不是 `TBBH`；
- 标准版本、源 bundle、源 ResourceVersion 或诊断指纹变化；
- 需要新增面积策略、派生字段或修复动作；
- 执行器需要从“仅生成 contract”扩展到真实 Raw→ADS 物化。

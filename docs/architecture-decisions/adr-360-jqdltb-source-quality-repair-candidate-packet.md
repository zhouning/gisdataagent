# ADR-360: JQDLTB Source-Quality Repair Candidate Packet

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-30

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

AR-0 的冻结源质量诊断和 transformation impact preview 已经给出事实，但业务输入仍分散在
diagnostic、semantic audit、readiness 和 draft decision packet 中。继续让工程人员从多份报告中
口头解释选择，会造成重复确认，也容易把“技术候选”误写成“业务批准”。

## 决策

新增只读 `gda.jqdltb_source_quality_repair_candidate_packet.v1`。它把 10 项待决事项集中成一份
可交给业务/数据责任人的 packet：

- 5 项 transformation：`canonical_key`、非正面积、面积偏差、`SJNF`、`MSSM`；
- 5 项 promotion governance：business steward、license、SLO/on-call、staging owner、production owner；
- 每个选项带聚合影响、所需证据、可关闭的 blocker 和接受后仍保留的 blocker；
- 只引用冻结证据的 SHA-256/规范化指纹，不包含源字段值、图斑 ID 或逐行敏感内容；
- `SJNF/MSSM` 的“继续隔离”选项明确不能关闭必填派生字段和晋级 blocker；
- 所有决定固定为 `pending_business_evidence`，不产生 Strategy、ApprovalCase、correction artifact、层文件或 `DataProductVersion`。

生成器会重新读取并校验 manifest、baseline、diagnostic、semantic audit、impact preview、readiness
和 draft decision packet 的身份。`--validate` 入口在交付后再次读取 packet 引用的全部文件，任何
内容、规范化指纹、source ResourceVersion 或 bundle 身份漂移都会 fail closed。

## 真实结果

packet：[`jqdltb_source_quality_repair_candidate_packet_2026-08-30.json`](../reports/jqdltb_source_quality_repair_candidate_packet_2026-08-30.json)

- packet SHA-256：`d953267afb5636b0f5c4071674283daf9162c33ee80671fbdc0528d618718523`；
- 10 项决定均为 `pending_business_evidence`；
- `quarantine` 非正面积：6 条隔离、1,549 条面积策略候选；
- `quarantine` 面积偏差：13 条隔离、1,542 条候选；
- `business_correction` 没有 correction identity 时保持数量未知；
- `promotion_ready=false`、AR-0 仍为 `awaiting_business_approval`。

验证：repair packet、impact preview、decision packet 聚焦回归 `18 passed`；新 packet 的 Ruff、
compileall 通过。该 packet 是业务输入交付物，不等于审批记录或源质量通过。

## 取舍

- 继续维护多份独立报告：已有事实可追溯，但业务无法快速比较选择和后果，保留风险；
- 自动选择技术上最简单的策略：会越过业务权威边界，拒绝；
- 生成带策略候选但不选值的只读 packet：减少往返，同时保持 fail-closed，采用。

## 后续门

业务方提交 signed/submitted decision packet 后，平台重新运行 readiness；只有五项 transformation
决定和语义证据完整时才在内存中生成 Strategy，随后才允许创建独立 ApprovalCase。批准后必须重跑
source-quality，并用同一 ProductVersion 提供 Raw→ADS 证据；本 ADR 不改变这些门。

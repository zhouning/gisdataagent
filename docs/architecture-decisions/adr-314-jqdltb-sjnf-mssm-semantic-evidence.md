# ADR-314: JQDLTB `SJNF/MSSM` 语义只接受来源证据

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-26

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

冻结的璧山 JQDLTB 源没有 `SJNF`、`MSSM` 字段。此前诊断把 `PZWH`、`SM`、`DLBZ`、`JQDLMC`
列为待审候选，但只统计了覆盖率，没有逐项对照标准正文和源 XML，业务审批仍要从头判断。

## 证据

- 《自然资源“一张图”数据库体系结构（2）统一调查监测1126》表 5-13 定义
  `SJNF=数据年份`、`Int(4)`、必填；注 13 明确“数据年份为数据生产的年份”。
- 同一表定义 `MSSM=描述说明`、`Char(2)`、必填，但当前材料没有给出 DLTB 的值域、填写说明或
  逐行映射规则。
- 1,555 条真实源中，`SM`、`DLBZ` 全空；`PZWH` 仅 10 条非空；`JQDLMC` 全量有值但语义是
  地类名称。
- `JQDLTB.shp.xml` 的 ArcGIS 处理记录跨 2018、2019 年，元数据创建日期为 2019-11-07；这些
  日期只证明文件处理历史，不能证明标准要求的数据生产年份。XML 也没有给出 `MSSM` 值域。

## 决策

AR-0 不从上述字段或处理日期自动生成 `SJNF/MSSM`：

- `SJNF` 只接受与本产品版本绑定的生产年份字段或业务材料，以及内容 SHA-256 和确定性提取方法。
- `MSSM` 只接受 DLTB `Char(2)` 的正式值域/填写规则和确定性映射；材料不足时继续隔离，不能写
  空串、通用说明或截断后的地类名称。
- 本次审计只形成候选否决证据，不创建 derivation rule、strategy、ApprovalCase 或
  DataProductVersion。

## 结果

原来的“请确认 `SJNF/MSSM` 语义”被压缩为两项可交付输入：生产年份依据；`MSSM Char(2)`
值域/逐行规则。收到材料后仍需生成版本化 rule artifact，走现有 transformation ApprovalCase，
不能绕过 ADR-313 的运行绑定。

## 证据产物

- [只读审计脚本](../../scripts/audit_chongqing_jqdltb_semantic_candidates.py)
- [机器报告](../reports/jqdltb_semantic_candidate_audit_2026-08-26.json)
- [聚焦测试](../../data_agent/test_chongqing_jqdltb_semantic_candidate_audit.py)
- 报告 canonical SHA-256：`90bead274d1dc7238cfb1b7f0400e8dc539f0f8aa9af932a6209a80a9acff4f8`

## 重评触发条件

- 业务方提交生产年份权威材料；
- 提交 DLTB `MSSM` 正式值域或填写规则；
- 冻结源 bundle、标准版本或标准文档字节发生变化。

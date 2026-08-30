# ADR-365：JQDLTB 语义字段隔离候选链

**状态**：Accepted for candidate-only use  
**日期**：2026-08-30

## 背景

AR-0 的冻结源可以继续做数据链路检查，但 `SJNF` 和 `MSSM` 仍没有获得可采纳的
权威语义规则。原有 transformation executor 需要完整审批策略才能写候选层；如果把
这两个字段填成空字符串、年份猜测或代码猜测，就会把“候选”伪装成标准化数据。

## 决策

增加一条与批准执行器隔离的 candidate-only 构建路径：

- Raw 层保留源记录；ODS、DIM、DWD、ADS 只生成候选投影，并删除未获准的 `SJNF/MSSM`
  字段，不写默认值；
- 每条源记录分别为 `SJNF`、`MSSM` 写入一个
  `gda.jqdltb_semantic_field_quarantine.v1` 字段级隔离条目；条目只保存
  `TBBH`、source feature id、目标字段、候选来源字段和隔离原因，不保存猜测值；
- 候选证据明确标注 `quality_verdict=failed`、`promotable=false`、
  `authority_state_created=false`、`data_product_version_created=false`；
- 候选输出采用内容寻址并支持幂等重放。它不调用 PlatformGateway，不创建
  ResourceVersion、Artifact、ApprovalCase、QualityResult 或 DataProductVersion；
- 如果语义审计已经显示某个目标获得 `accepted/approved`，候选路径拒绝执行并要求转入
  已批准 transformation executor，防止绕过审批。

## 取舍

这样可以在业务证据到位前检查 Raw→ADS 的物理排布、字段缺口和隔离规模，也能让下游
工程提前联调；代价是候选层不是标准化产品，不能进入服务、AI 或 GWM，也不能替代
更正 artifact、语义规则和业务批准。

## 验证

脚本 `scripts/build_chongqing_jqdltb_semantic_candidate.py` 已对冻结重庆 JQDLTB 源
实际运行：1,555 条源记录生成 1,555 条候选记录，`SJNF/MSSM` 共 3,110 个字段隔离；
源质量仍为 failed，未创建控制面状态或 `DataProductVersion`。实现和回归见
`data_agent/jqdltb_semantic_candidate.py` 与
`data_agent/test_jqdltb_semantic_candidate.py`。

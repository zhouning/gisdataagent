# ADR-312: 在业务批准前增加真实 JQDLTB Transformation Impact Preview

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-26

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

AR-0 已经把重庆璧山 JQDLTB 的 archive、Shapefile bundle、source `ResourceVersion`、标准版本和质量诊断冻结下来，但业务尚未决定 canonical key、非正面积处理、面积偏差处理以及 `SJNF/MSSM` 的语义推导。只保留诊断会让审批人看不到不同策略对真实产物规模的影响；直接执行又会越过审批边界。

## 决策

新增只读 `gda.jqdltb_transformation_impact_preview.v1` 预览命令，针对冻结的 1,555 条真实 `JQDLTB.shp` 逐策略计算聚合影响，不写 Raw、ODS、DIM、DWD、ADS，不创建 `ApprovalCase`，不生成 `DataProductVersion`。

预览固定绑定并校验：

- `archive_sha256`、Shapefile sidecar `bundle_sha256`（读取前后各计算一次）;
- source `ResourceVersion`、冻结 `approval_required` transformation contract、标准版本/指纹和诊断指纹;
- 1,555 features、EPSG:4523、`TBBH` 完整唯一候选键、`TBMJ/TBDLMJ` 双字段非正值事实和面积偏差事实。

预览覆盖 2×3 策略矩阵：

- 非正面积：`quarantine`、`business_correction`；
- 面积偏差：`preserve_source`、`use_geometry`、`quarantine`。

`business_correction` 没有 correction `ResourceVersion`/内容指纹时不猜测结果；`use_geometry` 没有面积规则指纹时不宣称可执行。六种组合都保留 `SJNF/MSSM` 待批准和 transformation ApprovalCase 缺失等执行阻塞。

同时修正 transformation executor：冻结质量规则要求的 `TBMJ`、`TBDLMJ` 两个面积字段都必须为正；业务更正必须同时提供有效更正值，否则记录进入 fail-closed 路径。面积偏差比较仍只使用冻结协议指定的 `TBMJ`，几何面积不会自动成为业务权威值。

## 真实结果

报告：[jqdltb_transformation_impact_preview_2026-08-26.json](../reports/jqdltb_transformation_impact_preview_2026-08-26.json)

报告 canonical 内容指纹为 `30ebf144218725372ef85a863c16facb24414c4cb676e6cdd6658f9e24c72ef5`；文件字节 SHA-256 为 `a00a10b79d05c7b4eed7693bd0ac506f07620b43644e472f697e3dd81b8a9161`。

- `quarantine + preserve_source`：6 条隔离，1,549 条进入面积策略后的候选集合；
- `quarantine + quarantine`：13 条隔离，1,542 条进入面积策略后的候选集合；
- 三种 `business_correction` 组合：因 correction 身份未提供，投影数量保持 `null`，不是估算值；
- 所有组合仍因 `SJNF/MSSM`、业务策略和 ApprovalCase 未完成而不能 promotion。

## 取舍

- **直接编译并执行默认策略**：能更快产出层文件，但会把技术假设冒充业务授权，拒绝。
- **只保留聚合诊断**：不会越权，但无法比较隔离规模和面积策略，延长业务决策往返，拒绝。
- **真实源只读 impact preview**：增加一个版本化报告和一次源读取，但能在不写数据的前提下给出可核验的候选规模，采用。

## 证据

- [Impact preview implementation](../../scripts/preview_chongqing_jqdltb_transformation_impact.py)
- [Impact preview test](../../data_agent/test_jqdltb_transformation_impact_preview.py)
- [Executor implementation](../../data_agent/jqdltb_transformation_executor.py)
- [Freeze Manifest](../freezes/2026-08-22-ar0-first-vertical-slice-freeze.md)
- [Transformation approval packet](../freezes/2026-08-23-jqdltb-transformation-approval-packet.md)

验证：JQDLTB 聚焦回归 35 项通过；PostgreSQL 发布门用例因 `JQDLTB_RELEASE_DATABASE_URL` 未配置跳过 1 项。Ruff 和 Python compileall 通过。

## 重评触发条件

- 业务提交新的 transformation strategy、correction resource 或几何面积规则；
- archive、bundle、source `ResourceVersion`、标准版本或诊断指纹变化；
- 冻结质量规则新增面积字段或新的派生目标。

# ADR-243: JQDLTB Transformation Runtime Admission

状态：已采纳（AR-0 首条 vertical slice）  
日期：2026-08-23

## 决策

JQDLTB 的物化入口使用独立的 `JqdltbTransformationExecutor`，由现有 DataOps HTTP 服务暴露：

`POST /v1/execute/chongqing-jqdltb-transformation`

入口接收完整的 executable contract，但执行前必须从 ApprovalCase authority 重新读取同一审批记录，并校验：

- contract、source `ResourceVersion`、诊断指纹、归档/包指纹和标准指纹一致；
- ApprovalCase 仍为 approved、未过期，且没有字段漂移；
- 失败发生在任何输出目录、层文件或平台 artifact 创建之前。

通过准入后，执行器原子生成 `raw`、`ods`、`dim`、`dwd`、`ads` 和 `quarantine` JSON 层，同时写入逐层 lineage、transformation artifact 和质量证据。源属性和源值保留；面积修正会先写入 `TBMJ_source` 等来源字段。平台 artifact、lineage、quality 记录使用最终路径登记。

本阶段不创建 `DataProductVersion`。即使 transformation quality 通过，也只得到一个可审计的 canonical candidate；产品发布仍由后续质量、服务和业务发布 gate 负责。

## 原因

- 审批是执行前的准入条件，不是执行后的说明文字。
- authority 复读可以阻止本地 JSON、过期审批或审批字段漂移绕过控制面。
- 原子层输出避免 Raw/ODS/DWD/ADS 只完成一部分时留下看似可用的数据产品。
- `DataProductVersion` 与 transformation candidate 分开，避免把“已按批准规则计算”误报成“已发布产品”。

## 当前范围

支持 GeoJSON/JSON/CSV，以及运行环境可读取的 GeoPandas 矢量文件。派生字段不再只依赖 contract 中的文字：每个批准的 `SJNF/MSSM` derivation 必须由运行时提供同 SHA-256 的 `gda.jqdltb_derivation_rule.v1` JSON artifact，并校验 target、source fields、semantic ref 和 method；当前唯一支持的 method 是 `first non-blank approved source value`。选择 `use_geometry` 时，运行时还必须提供同 SHA-256 的 `gda.jqdltb_geometry_area_rule.v1` artifact，并校验 source CRS、`TBMJ`、平方米单位、1% 比较容差和 `planar_geometry_area_in_source_crs` method。规则文件缺失、字节漂移、字段漂移或 method 不支持时，在输出目录创建前 fail closed。业务语义合同、面积权威和许可责任仍由 ApprovalCase 表达，不由执行器猜测。

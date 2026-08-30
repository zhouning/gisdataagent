# ADR-245：DuckDB 轻量存算一体架构采集与对账

## 状态

Accepted（仅适用于 lightweight integrated profile；2026-08-23）

## 背景

AR-1 已有 PostGIS 的 `ResourceVersion -> provider observation -> architecture
reconciliation` 切片，但轻量 profile 中的 DuckDB 仍只能作为执行器使用，无法在同一套
架构版本合同里表达“表存在、结构发生变化、物理对象被删除”。如果继续让各个调用方自行
读取 `information_schema`，会出现不同的对象身份、revision 和 tombstone 语义，最终又形成
一套旁路 metadata。

本决策只解决 DuckDB 文件中的单表技术架构事实。它不把 DuckDB catalog 复制到 GDA，也不
把行内容扫描当作 schema 事实；产品注册、治理合同、质量结果和发布仍由现有控制面负责。

## 决策

新增 `data_agent.duckdb_architecture_harvester`，复用现有
`ArchitectureProviderObservation`、`SchemaVersion` 和 `PhysicalLocation`：

- 通过 DuckDB 的只读连接读取指定 schema/table 的 `table_oid`、columns、constraints 和
  indexes；只保存规范化字段与 SHA-256，不保存原始 SQL、默认表达式或凭据。
- `provider_namespace` 使用受控的 `provider_ref/database_ref`，`provider_object_id` 使用
  `schema.table`；`PhysicalLocation` 的 revision 记录 provider 返回的
  `duckdb-table-oid:<table_oid>`。它能在 provider 暴露不同 OID 时区分物理位置变化，但
  DuckDB 1.5.5 的只读重开会按逻辑表名复用 OID，因此同名表删除后重建不能被这条只读
  adapter 保证识别为 location drift，必须由新的 provider revision 或新的 ResourceVersion
  承接。
- schema snapshot 指纹包含有序列定义、约束和索引；table OID 只进入 source revision 与
  physical-location revision，不混入 schema 指纹。默认表达式与索引/约束定义只保留指纹，
  避免把可能含有敏感信息的 provider 文本写入 evidence ledger。
- 表不存在时只生成不带任何当前 fingerprint 的 `tombstoned` observation；连接失败、查询
  失败和 provider 响应不符合预期直接报错，不生成 tombstone。
- 观察结果返回 `SchemaVersion`、`PhysicalLocation` 候选，但不会自动注册架构、创建
  `DataProductVersion` 或替换已绑定版本。调用方必须通过 `PlatformGateway` 记录 observation，
  再按既有 reconciliation/approval 门处理 drift。
- 相同输入、相同 `observed_at` 和相同 provider 事实产生相同 observation ID/fingerprint；
  ledger 的 append-only/tenant RLS/幂等约束继续生效。

## 取舍

| 方案 | 优点 | 代价 | 结论 |
| --- | --- | --- | --- |
| 在每个 DuckDB 调用点自行读取 catalog | 初始代码少 | 身份、指纹、删除语义无法统一；难以审计和重放 | 不选 |
| 把 DuckDB catalog 全量复制进 GDA | 查询方便 | GDA 变成第二技术 metadata authority，复制敏感 SQL 和 provider 状态 | 不选 |
| 复用 provider observation，只保存有界事实和候选 | 与 PostGIS、Gravitino bridge 共用账本；可重放、可发现 drift；实现面小 | 需要后续 provider adapter 补充实际数据/快照 conformance | 采用 |

## 验证

`data_agent/test_duckdb_architecture_harvester.py` 使用真实 DuckDB 1.5.5 文件完成：

- 固定时间的重复采集产生相同 observation 与 schema snapshot；采集连接为 read-only；
- `ALTER TABLE ... ADD COLUMN` 改变 schema 指纹，但保留同一 physical location 指纹；
- `DROP TABLE` 产生 tombstone，且不附带 schema/location 候选；同名重建的稳定物理身份
  识别能力按上面的 DuckDB provider 限制处理。

本 ADR 不证明 Iceberg/Gravitino catalog、对象存储字节校验、Spark/Sedona/Flink、云
DuckDB provider、跨租户外部系统或生产 RPO/RTO。上述能力仍需各自的 provider conformance
和恢复证据，不能由这条 lightweight slice 代替。

## 重评触发

- DuckDB 文件需要跨进程写入、快照/回滚或云对象存储 URI；
- 需要以行数、数据 checksum 或统计信息作为产品质量/发布门；
- DuckDB 版本升级导致 `table_oid` 或 catalog 字段稳定性变化；
- DuckDB provider 开始暴露跨只读连接稳定的对象 UUID/revision，可用于识别同名重建；
- lightweight profile 要求多租户共享同一文件或进入生产 HA/DR。

# ADR-248：Gravitino Iceberg 表架构观察

## 状态

Accepted（Gravitino table contract slice；2026-08-23）

## 背景

AR-1 已有 PostGIS、DuckDB 和 S3-compatible 对象的架构观察合同。Iceberg 表同时拥有稳定的
Gravitino 技术身份、Iceberg snapshot、schema 和 warehouse location；如果只记录一个 table
fingerprint，就无法区分“内容提交变化”和“schema 变化”，也无法把 snapshot 绑定到物理位置。

## 决策

新增 `data_agent.iceberg_architecture_harvester`，输入是已由 Gravitino read bridge 返回的单个 table
payload 和已准入的 `IcebergArchitectureTarget`：

- 只接受精确 `metalake/catalog/namespace/table` 身份；`provider=iceberg`、format version、数字
  `current-snapshot-id`、非空 schema columns 和无凭据的绝对 location 都必须存在；
- `current-snapshot-id` 生成 `source_revision=iceberg-snapshot:<id>`，写入 `PhysicalLocation` 的
  revision ref；同 schema 的新 snapshot 只改变 location/observation revision；
- schema snapshot 只保存字段顺序、字段 id（如 provider 提供）、类型、nullable、schema id 和
  format version，生成独立 schema content fingerprint；
- Gravitino transport/authorization/protocol error 必须由调用方抛出。只有 provider 已确认 not-found
  时才传入 `table=None` 生成 tombstone；
- 返回 `SchemaVersion`、`PhysicalLocation`、`ArchitectureProviderObservation` 候选，仍由
  `PlatformGateway` 负责账本写入、RLS、幂等和 reconciliation。

## 验证

`data_agent/test_iceberg_architecture_harvester.py` 的 5 项回归覆盖：

- 相同 table payload replay 指纹稳定；
- snapshot 变化与 schema 指纹分离；
- 字段新增同时触发 schema/location candidate 变化；
- 仅明确 not-found 生成 tombstone；
- 缺 snapshot、非法 snapshot、凭据 URI 和非 Iceberg provider fail closed。

契约回归本身不是 Gravitino/Iceberg 生产能力认证。真实 Spark/Iceberg snapshot 到 PostgreSQL ledger
的受限联合证据已按 [ADR-249](adr-249-real-iceberg-snapshot-ledger-acceptance.md) 完成；该证据仍不
覆盖真实 Gravitino REST table read、schema evolution、snapshot lineage、Spark/Sedona/Flink 互操作、
对象字节恢复、HA、backup/restore、双租户或跨系统恢复。

## 重评触发

- Iceberg schema 需要解析 nested/list/map/identifier fields，而当前受限列合同不足；
- provider 不再通过 table properties 暴露 snapshot/location，需读取 metadata JSON；
- 需要验证 snapshot ancestry、manifest/data-file checksums、branch/tag 或 WAP；
- 需要把 Iceberg observation 作为 successor release 或 DataProductVersion 的自动准入证据。

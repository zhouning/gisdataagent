# ADR-250：Iceberg snapshot lineage observation contract

## Status

Accepted（bounded provider evidence；2026-08-23）

## Context

Iceberg architecture observation 已能把当前 snapshot、schema 和 physical location 写入控制账本，
但仅凭 `source_revision=iceberg-snapshot:<id>` 无法在观察层表达当前 snapshot 的 parent chain。真实
Spark/Flink acceptance 已经获得该链；如果只把它留在脚本内部，后续 provider reconciliation、审计和
故障调查无法复用同一验证规则。

## Decision

`data_agent.iceberg_architecture_harvester` 接受可选的有界 `snapshots` payload，并将其投影为
`IcebergSnapshotLineageEntry`：

- 每个 entry 只包含数字 `snapshot_id`、可空数字 `parent_id` 和有界 `operation`；
- 输入顺序固定为 oldest -> newest，snapshot ID 必须唯一；root 不得有 parent，child 的 parent
  必须出现在前序 entry；
- 链尾必须等于 `properties.current-snapshot-id`；超过 256 个 entry、缺 entry、断链、重复或当前
  snapshot 不一致时 fail closed；
- 没有 provider lineage 字段时保持 `None`，不根据当前 ID 猜造 parent chain；tombstone 不得携带 lineage；
- lineage 仍是 provider observation evidence，不复制 metadata JSON、manifest 或数据文件，也不改变
  `ArchitectureProviderObservation` 的 source revision/ledger schema。当前账本 reconciliation 仍依据
  schema/location 指纹；lineage 作为报告和后续 successor/recovery gate 的输入。

## Evidence

`data_agent/test_iceberg_architecture_harvester.py` 覆盖 root/child 合法链和断链拒绝。真实联合验收
`.tmp/iceberg-architecture/acceptance-report.json` 在固定 Spark/Flink/MinIO/JDBC Catalog 矩阵上通过
17/17 checks：baseline root `3379225455652360291`、evolved child
`3726182389816928569`，报告 canonical `report_sha256`
`b53ef5d3fdab781ea99b5701879c84167dcb57654365d8f6999f604cebfdd1a8`，文件 SHA-256
`693409258b97ab1545850b67f23f69c31b17964aa2dab286aa25e19dc1d5af59`。

## Not claimed

本合同不证明 Gravitino REST catalog、Iceberg metadata JSON 的完整一致性、manifest/data-file lineage、
checkpoint recovery、branch/tag/WAP、生产 HA/DR、PITR/RPO/RTO 或跨区域复制。provider 未返回 lineage
时必须保留未知，不得把单个 current snapshot ID 当作完整 ancestry。

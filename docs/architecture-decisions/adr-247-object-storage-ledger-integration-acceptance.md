# ADR-247：对象存储观察接入控制账本的联合验收

## 状态

Accepted（disposable provider + disposable PostgreSQL ledger；2026-08-23）

## 背景

ADR-246 已经把 S3-compatible JSON/GeoJSON 对象转换为
`ArchitectureProviderObservation`、`SchemaVersion` 和 `PhysicalLocation` 候选，但只验证了
provider 读取。若不把这条路径接入 `PlatformGateway`，对象 revision、schema drift 和删除标记
仍然停留在采集进程内，不能成为可对账的 AR-1 证据。

## 决策

在同一 disposable acceptance 中同时启动固定版本 MinIO 和 PostgreSQL：

1. MinIO 开启 bucket versioning，写入同 schema 内容、字段增加内容，并创建 delete marker。
2. 用真实 harvester 产出的 observation 通过 `PlatformGateway` 写入控制账本。
3. 先验证 `unbound`，再登记 `ResourceVersion` 的 schema、contract、physical location 和
   binding，确认基线 `in_sync`。
4. 追加同 schema 新 object revision，要求对账为 `location_drift`；追加字段变化，要求为
   `schema_and_location_drift`；追加 delete marker，要求为 `tombstoned`。
5. 重放同一 observation 必须幂等，账本只允许 append-only；跨租户读取必须被拒绝，观察表必须
   开启并强制 RLS。

联合脚本为 `scripts/certify_object_storage_architecture_observation.py`。它只保存受限摘要和
指纹，不把对象字节、凭据或 PostgreSQL 连接串写入报告；所有 disposable provider/container/
volume/network 在退出时清理。

## 验证

固定镜像：

- `minio/minio:RELEASE.2025-04-22T22-12-26Z`
- `postgres:16.4`

报告：`.tmp/object-storage-architecture/object-storage-report.json`

- schema：`gda.object_storage_architecture.acceptance.v2`
- status：`passed`
- canonical `report_sha256`：`1973cd79969e91b3d1643ecf288803cc0aada6aa5ad6ba6954ebca34efe66063`
- 文件 SHA-256：`ad98d10ccbe70b3ceb9bc346984c9604c36f66c819d41cc8789ed0a4f8013fb0`
- observations：`present=3`、`tombstoned=1`
- 对账状态：`unbound`、`in_sync`、`location_drift`、`schema_and_location_drift`、`tombstoned`
- RLS：`enabled=true`、`forced=true`
- 清理：bucket、container、volume、network、PostgreSQL container 全部不存在

该证据证明的是开发/验收环境中的 provider-to-ledger 合同，不是生产对象存储 HA、跨区域复制、
Object Lock、RPO/RTO、Parquet/COG/二进制对象、sidecar manifest、双租户恢复或 Iceberg snapshot
能力。生产发布仍需独立的 provider foundation、恢复和故障注入验收。

## 重评触发

- 对象类型超出 JSON/GeoJSON，或完整 GET 超出 bounded exact-read 上限；
- provider revision 语义从 VersionId/ETag 变化为 multipart/checksum/replication 组合；
- 控制账本需要跨区域复制、PITR、备份恢复或生产 workload identity；
- 需要把观察结果直接驱动架构 successor、DataProductVersion 或发布 active pointer。

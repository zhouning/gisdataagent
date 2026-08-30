# ADR-246：S3-compatible JSON/GeoJSON 对象架构观察

## 状态

Accepted（受限 JSON/GeoJSON slice；2026-08-23）

## 背景

平台已有 S3/MinIO 对象读取、STAC 查询和 source schema drift 逻辑，但这些路径各自拥有
对象身份和 schema 指纹，尚未把对象存储纳入 AR-1 的
`ResourceVersion -> ArchitectureProviderObservation -> reconciliation` 合同。若直接把
对象列举结果写进 GDA catalog，会重新形成第二个技术 metadata authority；若只取前 N 条记录，
又无法把结果当作完整 schema 证据。

## 决策

新增 `data_agent.object_storage_architecture_harvester`，只处理 JSON/GeoJSON 单对象：

- 先执行 provider `HEAD`，使用 `VersionId`；未开启版本控制时使用 `ETag + ContentLength`
  作为 provider revision。没有 revision 的响应直接失败。
- 再执行有界、完整的 `GET`。`ContentLength` 超过 `max_schema_bytes`、实际读取长度不一致、
  JSON 解析失败或记录数超过 `max_schema_records` 都 fail closed；不会使用不完整 sample 生成
  schema candidate。GeoJSON 目标必须是 `FeatureCollection`。
- schema snapshot 只记录排序后的字段路径、类型和 nullable，不记录源值、原始 JSON、ETag、
  endpoint 或凭据。对象大小和记录数作为 bounded evidence，不进入 schema 指纹。
- schema 指纹与 object revision 分离：同一对象 revision 下增加字段产生 schema drift；内容改变但
  字段形状不变时 schema 指纹保持不变，而 `PhysicalLocation` revision 改变。
- `HEAD` 返回明确 not-found 才产生空 tombstone；`403`、超时、协议错误、GET 失败均抛出错误，
  不得把访问失败写成删除事实。
- 结果只返回现有 `SchemaVersion`、`PhysicalLocation` 和 `ArchitectureProviderObservation`
  候选。调用方仍须通过 `PlatformGateway` 记录 observation，不能自动注册架构、创建
  `DataProductVersion` 或改变产品 active pointer。

## 取舍

| 方案 | 优点 | 代价 | 结论 |
| --- | --- | --- | --- |
| 复用 source connector 的任意采样 discovery | 兼容对象种类多、成本低 | sample 可能漏字段；无法作为架构发布门 | 不选作 AR-1 authority |
| 把完整对象内容复制到控制账本 | schema 读取简单 | 大对象、敏感值和第二份数据真值进入 GDA | 不选 |
| HEAD revision + bounded exact GET + shape-only fingerprint | 能分离 schema/content revision；不复制数据真值；可重放 | 首期只支持 JSON/GeoJSON，超限对象需登记 governed manifest | 采用 |

## 验证

`data_agent/test_object_storage_architecture_harvester.py` 使用 fake S3 protocol client 覆盖：

- 固定 revision 的完整 GeoJSON 采集与 replay 指纹一致；
- 增加字段触发 schema 与 location 变化，保持字段形状但换 revision 只触发 location 变化；
- 明确 not-found 生成 tombstone，AccessDenied 不生成 tombstone；
- 超过 exact byte limit 直接失败，不采样。

`scripts/certify_object_storage_architecture_observation.py` 已使用固定镜像
`minio/minio:RELEASE.2025-04-22T22-12-26Z` 完成 disposable provider acceptance：真实开启
bucket versioning，连续写入三个 VersionId，验证同 schema revision、字段新增 drift、旧
VersionId 精确回读、delete-marker tombstone，并确认 bucket/container/volume/network 全部清理。
随后同一脚本启动 `postgres:16.4`，将真实 observation 通过 `PlatformGateway` 写入控制账本，
验证幂等、`unbound -> in_sync` 登记、`location_drift`、`schema_and_location_drift`、
`tombstoned`、RLS 和跨租户拒绝；PostgreSQL container 也已清理。联合证据详见
[ADR-247](adr-247-object-storage-ledger-integration-acceptance.md)。当前报告
`.tmp/object-storage-architecture/object-storage-report.json` 的 canonical `report_sha256`
为 `1973cd79969e91b3d1643ecf288803cc0aada6aa5ad6ba6954ebca34efe66063`，文件 SHA-256 为
`ad98d10ccbe70b3ceb9bc346984c9604c36f66c819d41cc8789ed0a4f8013fb0`。

这仍不是 PostgreSQL production foundation 或 MinIO/S3 生产 HA、复制、Object Lock、RPO/RTO
认证，也不证明 Parquet/COG/二进制对象、multipart checksum、STAC/pgSTAC catalog。后续 acceptance
必须继续使用同一 observation 合同，并单独验证权限、恢复和双租户隔离。

## 重评触发

- 需要支持 Parquet/COG/视频/点云等非 JSON 对象；
- 对象大于 exact GET 上限，且需要由 sidecar manifest 提供 schema；
- 生产对象存储启用 multipart checksum、Object Lock 或跨区域 version replication；
- provider 的 ETag 不再能作为未版本化对象的稳定 revision，或需要把 checksum 纳入 release gate。

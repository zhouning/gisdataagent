# ADR-253：DriveTransfer 轻量 file-lake profile 验收

## 状态

Accepted（bounded lightweight local file-lake；2026-08-23）

## 背景

总体架构把 `DriveTransfer` 定义为客户端/边缘侧的大文件传输和入湖能力，要求服务端
session、checkpoint、manifest、integrity 和 audit 成为事实来源。仓库已有
`OfflineIngestStore`，能够在轻量 file-lake profile 中完成分片 session、Raw immutable
asset、ZIP 安全解包、profiling 和幂等 ingest，但此前只有单元/API 回归，没有一条真实空间
bundle 的端到端证据，因此不能把它计入 AR-2 的可验证交付。

## 决策

将现有 `OfflineIngestStore` 的 bounded 能力作为 `DriveTransfer` 的 lightweight local
profile，新增 `scripts/certify_drive_transfer_lightweight.py` 作为可重复 acceptance：

1. 使用仓库内真实重庆 OSM GeoParquet，封装成 ZIP bundle，创建带 expected size、full
   SHA-256、chunk size、asset kind 和 source system 的服务端 upload session。
2. 以 1 MiB chunk 乱序提交 11 个分片；故意提交错误 checksum，要求 session 进入
   `interrupted`，随后从缺失/失败位置恢复并 replay 已验证分片。
3. finalize 时重新组装并计算完整文件 hash，原子写入 Raw 区和 raw manifest；ingest 时对 ZIP
   路径做有界 entry/size/path/symlink 校验，原子解包到 expanded Raw，写入 expansion manifest，
   再 profile GeoParquet 并记录 upload/expansion lineage。
4. 重复调用 ingest 必须复用原 ingest run，不得产生第二份 Raw/expanded asset 或新的事实
   manifest。报告只在所有这些门和临时目录清理同时通过时标记 `passed`。

该 profile 复用现有离线 ingest 的本地 session/manifest/audit 事实，不新增第二套文件真值，
也不把本地 JSON 事实冒充 PostgreSQL 控制面或云 provider authority。

## 验证

报告：`.tmp/drive-transfer/lightweight-acceptance-report.json`

- schema：`gda.drive_transfer.lightweight_acceptance.v1`；status：`passed`
- source：真实 `chongqing-osm-roads-standardized.geoparquet`，11,104,995 bytes，SHA-256
  `8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`
- bundle：11,023,659 bytes，11 chunks，SHA-256
  `fde7a14a2aca826ca915c28d97d3c0286a6346a58210d7019db89a4c2d2a77f8`
- 12/12 checks 通过：checksum rejection/interrupted、乱序恢复、all chunks、session commit、
  Raw size/hash、raw manifest、safe expansion、source-bound expansion manifest、GeoParquet
  profiling、upload/expansion lineage 和 ingest replay idempotency。
- 临时工作目录清理：`work_directory_absent=true`
- canonical `report_sha256`：`de8eda36b9f3bf67bc3da834515791504e7e66d39ea04e899ce51d1727b86f96`
- 文件 SHA-256：`e166098deda2fef91becd13007a0d581c363e1c97014159d4ab6dbc87c22e161`

## 未覆盖范围

本 ADR 只放行 lightweight local file-lake 的 bounded transfer/ingest。未放行 PostgreSQL
durable session authority、S3 multipart pre-signed URL、云盘/NAS/SMB/FTP/SFTP provider、
多租户生产 identity/quota/malware scanning、pause/resume 的跨进程客户端协议、TB 级吞吐、
HA、RPO/RTO 或跨区域恢复；这些仍是后续 `DriveTransfer` 生产 profile 的退出门。

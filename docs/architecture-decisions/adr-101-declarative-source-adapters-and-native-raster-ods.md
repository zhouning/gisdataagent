# ADR-101: Declarative Source Adapters and Native-Raster ODS

**Status**: Accepted  
**Date**: 2026-08-01  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

OSM 道路和中心城区建筑已证明 Shapefile 到 GeoJSON/GeoParquet/Iceberg 的真实链路，但 source
bundle、driver、profile、transform、质量证据和 promotion 边界仍部分隐藏在产品脚本中。对重庆
DEM 继续复制专用脚本会让同一文件在不同链路得到不同身份；沿用原有 `bundle_identity()` 又只会
计算非 Shapefile 主文件，遗漏 `.tfw/.aux.xml/.ovr/.vat.* /.xml` sidecar。

DEM 已经 tiled、LZW 压缩并包含 overview，但这些事实不等于通过 COG conformance。把它直接宣称
为 COG，或为了统一而覆盖转换原文件，都会混淆 raw integrity、ODS admission、标准化和发布资格。

## Decision

### Declarative, Fail-Closed Adapter Registry

每种受治理 source shape 必须使用不可变的 `SourceAdapterDefinition`，声明 adapter ID/version/
fingerprint、source kind、extension/driver allowlist、bundle member policy、profiler/transform adapter、
目标逻辑层、classification、required evidence/checks 和 promotion policy。

- registry 未登记的 adapter、extension 或 driver 拒绝执行；
- 必需 bundle member 缺失时拒绝执行；同 stem 出现未声明 sidecar 时拒绝执行；
- restricted source 不能直接声明 promotion eligible；
- adapter fingerprint 进入 source manifest 和 Platform Definition，执行证据可追溯到确切规则版本；
- 产品特定 schema transform 可以保留，但 source identity、治理边界和必需证据不能只存在于脚本。

Shapefile member 顺序保持与既有身份算法兼容，因此建筑迁移不改变既有 bundle SHA-256。

### Native-Raster Object ODS

重庆 DEM 的七个原始成员分别按 physical SHA-256、整体按 canonical bundle SHA-256 寻址，写入
MinIO 后逐成员回读校验。ODS 使用 `native_raster_bundle` 对象合同，不把 raster 强制展开为 Iceberg
行表，也不覆盖源 TIFF。

raw Resource 指向 bundle 前缀；ODS Resource 指向已验收的主 TIFF，并通过 manifest 绑定全部成员。
二者具有不同逻辑身份和 authority locator，以 `COPY` lineage 记录 byte-preserving admission。
同一 bundle 跨 Run 复用同一内容寻址 ODS ResourceVersion；每个 Run 仍产生独立 output/evidence
Artifact、QualityResult 和 lineage。ResourceVersion 的首次创建时间不是内容身份的一部分。

质量状态分开记录：

- raw source integrity 和 full pixel scan 可以为 `passed`；
- 未运行专用 validator 时 COG conformance 必须为 `not_evaluated`；
- ODS admission 只证明完整性、画像、回读和可回放；
- 标准映射、DWD/ADS 和 DataProductVersion promotion 继续阻断。

## Alternatives Rejected

- **只使用主 TIFF SHA-256**：遗漏会改变读取语义或性能的 sidecar，不能代表完整数据集。
- **接入时自动覆盖为 COG**：破坏 raw preservation，且当前没有独立 COG conformance 证据。
- **所有栅格强制写入 Iceberg 行表**：增加转换成本并弱化原生 raster consumer，不是 ODS 完整性所需。
- **继续复制产品专用控制代码**：无法证明跨格式治理语义一致，也不能稳定绑定 adapter 版本。

## Evidence

- 建筑真实全量回放仍为 107,452 条，bundle SHA-256 `e2697e...`、46,229,820-byte GeoJSON
  SHA-256 `6fd8c8...` 不变，本地快照和 MinIO 对象均复用。
- 重庆 DEM 七成员 bundle SHA-256 为 `7e2cd...`；全分辨率扫描记录 2,567,764 个像元，其中
  998,698 有效、1,569,066 NoData，高程 24–2802。首次上传和完整重放均完成逐成员 readback。
- Definition `cf9e56cf-8d94-5ded-b8d9-62d3295a4e81`、PlatformRun
  `dfc75abf-4779-50d3-8cfb-4b660f379950`、DolphinScheduler instance `15` 和 ODS
  ResourceVersion `25c9396e-2880-5a04-beb6-c407d8f2cc43` 形成完整控制/证据链。
- 两个前置 Run 分别暴露 authority locator 冲突和跨 Run content-version timestamp 冲突，均按
  provider STOP 终结为 `failed/state_version=4`；修复后新 Run 成功且完整重放零新增。
- 扩大控制面回归 191 项通过；Ruff 通过；migration ledger `103/103 in_sync`。

## Consequences

- 新 source format 必须先定义 bundle、profile、transform 和 promotion 合同，接入成本略有增加，
  但身份与质量语义不再依赖调用者约定。
- vector 和 raster 共用控制面证据模型，同时允许 Iceberg table 与 immutable object bundle 使用各自
  合适的物理形式。
- 当前结论不代表 DEM 已是 COG、已完成智能落标或可发布为数据产品。
- 数据库、对象存储、HTTP/STAC connector，Flink 增量、SLO/Incident、双租户和恢复仍是 AR-2
  后续退出门。

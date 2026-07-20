# ADR-017：GIS 服务发布控制面与 Provider Runtime

**Status**: Proposed

**Date**: 2026-07-20

**Decision owners**: Platform Architecture, GIS Engineering, DataOps, Security, SRE

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md)

**Related decisions**: [ADR-001 可插拔地理空间存储、计算与服务边界](adr-001-geospatial-lakehouse-and-postgis-boundary.md) · [ADR-004 传统平台能力下限与 Human/Agent 双入口](adr-004-capability-floor-and-dual-entry-agentic-platform.md) · [ADR-005 DataOps 与 AgentOps 双运营闭环](adr-005-dataops-and-agentops-operating-loops.md) · [ADR-006 OpenMetadata + Gravitino Metadata Fabric](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-007 DolphinScheduler + Temporal 编排平台](adr-007-dolphinscheduler-temporal-orchestration-platform.md)

## Context

项目已有 REST/MVT/STAC/MCP 接口、PostGIS serving schema、Martin 部署、COG/STAC 设计以及 SuperMap 等商业 GIS 的技术评估，也已经提出从 `DataProductVersion` 派生 `ServiceDefinitionVersion`。这些事实只证明局部 endpoint 和发布合同存在，不能证明已经具备生产级 GIS 服务发布平台。

完整 GIS 发布至少同时涉及：数据产品与服务版本关系、图层/样式/比例尺/坐标参考、二维/三维 provider、传统和现代 OGC 协议、认证授权、缓存一致性、流量切换、消费者兼容、SLO、事故、回滚和退役。若让某个 GIS server、API gateway 或 UI 配置直接成为平台权威，会再次形成多套定义、权限、调度和发布状态机；若全部自研，又会重复成熟协议、渲染和切片引擎。

约束：

- 私有化、离线、云托管和轻量部署都必须支持；云 provider 可替换默认开源组件。
- LLM 可能不可用；完整发布与运维必须有 Web/API/SDK/CLI/TUI/Notebook 确定性路径。
- 服务只能消费经过治理的 `DataProductVersion`，serving projection 可重建且不是分析真值。
- 当前团队不适合自研通用 OGC/STAC/MVT/raster/3D server，也不适合让每个 provider 建立独立调度和发布生命周期。
- 既有 PostGIS/Martin、React/MapLibre/deck.gl、MinIO/COG/STAC 和商业 GIS 资产应通过 adapter 增量演进。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. GDA 自研统一 GIS server | 单一代码栈，表面一致 | 重复 OGC、过滤、CRS、渲染、切片、3D、缓存和安全生态；长期维护不可控 | 拒绝 |
| B. GeoServer 作为平台控制面和全部 data plane | 传统 OGC/SLD 成熟，生态广 | 定义和部署生命周期被单一 server 绑定；轻量 MVT/COG/STAC、云和商业 provider 适配受限 | 仅作为兼容 provider |
| C. SuperMap/ArcGIS/云 GIS 作为平台权威 | 企业 GIS 能力和工具链完整 | 许可、云厂商和部署锁定；跨 provider 产品版本、审计和离线能力不统一 | 作为认证 provider，不作为权威 |
| D. API gateway 配置即服务目录 | 路由、认证和限流上线快 | 不理解 DataProduct、Layer/Style、构建、消费者兼容、回滚和退役 | 拒绝 |
| E. GDA Service Control Plane + 可认证 Provider Runtime + Gateway/Operations | 保持治理和生命周期统一，同时复用专业 GIS 引擎并支持替换 | 需要 provider SPI、能力矩阵、conformance、跨 revision 缓存和更多运维集成 | **选择为候选基线** |

## Decision

### 1. 三层所有权

1. **GIS Service Control Plane** 由 GDA 持有，负责定义、版本、策略、审批、provider placement、部署 revision、验证、active/rollback pointer、消费者、SLO、废弃和退役。这是领域控制能力，需要实现，但不能扩张为 GIS 协议引擎。
2. **Provider Runtime** 负责实际 Feature、Map、Tile、Raster、STAC、3D 和 Process 协议、查询、渲染与切片。provider 不拥有 DataProductVersion、策略批准、active pointer、消费者生命周期和平台 Run 真值。
3. **Gateway & Operations** 负责 OIDC/workload identity、路由、WAF、quota/rate limit、cache/ETag、request telemetry 和 usage。Gateway 不拥有 ServiceDefinition；provider endpoint 不直接公开。

三层共享 `ResourceURN`、`SubjectContext`、`PolicyDecision`、`PlatformRun`、Artifact、ApprovalCase、SLO/Incident、AuditEvent 和 correlation id，不创建第二套 metadata authority、scheduler 或 permission engine。

### 2. 发布对象与状态机

首期控制对象：

- `GISServiceDefinitionVersion`：通用 `ServiceDefinitionVersion` 的 GIS typed profile，声明服务类型、协议、request/response contract、source product、provider requirement、策略、兼容和 lifecycle；两者共用一个 service registry 和状态机，不能形成平行权威。
- `LayerDefinitionVersion`：source snapshot/projection、schema、geometry、CRS/axis order、extent、filter、scale/generalization、temporal dimension 和 field exposure。
- `StyleDefinitionVersion`：MapLibre Style、SLD 或 provider-native style artifact 及 portability class；样式不可原地覆盖。
- `TileMatrixSetDefinitionVersion`：CRS、origin、resolution/scale、zoom、tile size、bounds 和 axis order。
- `CachePolicyVersion`：namespace、key dimensions、TTL、stale policy、warmup、purge/rollover 和 authorization variance。
- `ServicePolicyBinding`：resource/column/row/spatial/temporal/action/purpose obligation 与 enforcement point。
- `ServiceDeploymentRevision`：provider/version/config fingerprint、artifact、route、health、validation verdict、created_at 和 active/rollback pointer。
- `EndpointRevision`、`ConsumerBinding`、`ServiceSLO` 和通用 `RollbackPointer`。

```text
draft -> validating -> approved -> deploying -> active
  |          |             |           |
  +-> fix-required          +-> failed  +-> deprecated -> retired
                                      incident -> suspended -> rollback
```

发布必须创建新 projection/deployment revision，验证后原子切换 active pointer。失败不改变 active revision；禁止原表就地变更、可变对象 key、共享可变 style 或直接修改 provider 配置绕过控制面。

### 3. Provider 候选基线

| Capability | 默认候选 | 使用边界 |
|---|---|---|
| SQL/attribute API | GDA typed API projection + PostGIS/DuckDB adapter | OpenAPI/JSON Schema 和 query/policy contract 由控制面固化；RocketAPI 只能作为 adapter |
| OGC API Features | pg_featureserv + pygeoapi 分工 | pg_featureserv 用于 PostGIS 轻量直出；pygeoapi 用于多源 OGC API facade。最终路由由过滤、CRS、事务、扩展、吞吐和运维 benchmark 决定 |
| OGC API Tiles/MVT | PostGIS + Martin + 标准 facade | Martin 只读版本化 serving schema；TileJSON/style/URL/ETag/cache key 都携带 revision，OGC API Tiles facade 不复制 tile 真值 |
| Raster/imagery | COG + TiTiler | COG 内容留在 object storage；TiTiler 承担窗口、重采样和 render projection，不成为 raster 真值 |
| STAC | pgSTAC + stac-fastapi 或同等 conformance 实现 | Collection/Item/Asset 与 ProductVersion、对象 version/checksum、policy 和 extent 一致 |
| WMS/WFS/WMTS/WCS、SLD | GeoServer | 条件兼容 provider，用于旧客户端、复杂制图和需要 CITE 认证的传统 OGC 场景；不成为默认平台控制面 |
| Commercial/cloud GIS | SuperMap iServer/iObjects、ArcGIS Enterprise、Azure/其他云 adapter | 只有通过 capability、许可、identity、SLO、恢复、升级和成本认证的功能才可声明支持 |
| 3D/point cloud/mesh | OGC 3D Tiles + object storage/Gateway | S3M/I3S 作为独立 provider capability；PDAL、Entwine、Py3DTilers 类构建器仅作为 DataOps executor 候选，逐数据家族认证 |
| Spatiotemporal observation/subscription | OGC API EDR/SensorThings profile | pygeoapi、FROST-Server 类 provider 或云 IoT adapter 逐项认证；Flink/checkpoint 后的产品投影是历史消费依据 |
| OGC API Processes | pygeoapi/兼容 facade | 返回统一 `RunRef`；DolphinScheduler 执行和保存 DataOps 状态，GIS provider 不自建隐藏 scheduler |
| File/export/offline package | Versioned Artifact + signed distribution | GeoPackage、FlatGeobuf、GeoParquet、COG、PMTiles、MBTiles 和商业离线包按 capability 认证；复用 `DriveTransfer`/multipart |
| API gateway | Apache APISIX 私有化候选；云 GatewayProvider 可替换 | APISIX 与现有 ingress、OIDC、策略、WAF、长连接、流式下载、观测和运维成本 benchmark 后才可 Accepted |

这里的“默认候选”不是 production-supported 声明。组件版本、镜像 digest、插件、CVE 基线和升级路径在 AR-0 benchmark 后冻结；不能在 ADR 中用未经运行验证的版本号制造确定性。

### 4. Provider SPI 与 placement

`GISServingProvider` 至少实现或显式拒绝：

```text
discover_capabilities
validate_definition
plan_projection
deploy_revision
health_and_readiness
activate_revision
invalidate_or_rollover_cache
rollback_revision
reconcile_external_state
collect_metrics_and_usage
deprecate_and_retire
```

`ProviderManifest` 声明 protocol/version、read/transaction、filter/paging/sort、CRS/axis order、style/label、tile/TMS、raster、time、3D/LOD、auth/policy pushdown、HA、backup/restore、license、resource/cost 和 conformance status。placement resolver 只能选择满足 ServiceDefinition requirement 且当前认证有效的 provider/version/profile；运行时选择固化到 DeploymentRevision，不能静默漂移。

### 5. 发布执行与调度

- publish、projection build、tile/3D build、validation、warmup、rollback 和 retirement 都创建 `PlatformRun` 和 Artifact/Evidence。
- DolphinScheduler 是数据构建、批量切片、projection rebuild、STAC materialization 和 OGC Process 的唯一 DataOps runtime。
- provider 自身的异步 job 可以保留外部 job ID，但必须支持幂等 submit、cancel、reconcile、timeout 和结果登记，不能成为唯一运行真值。
- API/Web/CLI/TUI/Agent 只提交同一 `CapabilitySpec` command；同步接口返回结果，长任务返回统一 `RunRef`。

### 6. 安全、缓存与多租户

- 所有公开流量经过 Gateway；provider 使用 workload identity、private network 和最小权限。运维诊断 endpoint 也不得默认公开。
- resource、column、row、spatial、temporal、action 和 purpose policy 优先安全下推；provider 无法表达时，通过独立 projection、security-barrier view 或请求后置过滤实现。无法证明无泄漏则拒绝发布。
- capabilities、schema、tile metadata、preview、legend、error、download、STAC link/asset 和 signed URL 都属于受控响应，不能只保护 feature query。
- cache key 至少隔离 tenant/policy class、service/layer/style/TMS/revision、format、extent/tile、filter/time 和 content negotiation。授权结果不得被公共 cache 复用。
- active pointer 切换采用 immutable URL/namespace + route switch；优先 namespace rollover，精确 purge 作为补充。任何 cache 均可丢、可重建且不保存权限或发布真值。

### 7. Conformance 与生产准入

每个 provider/profile 组合必须在固定代表数据和流量下通过：

- contract：schema、geometry、CRS/axis order、extent、null/empty/invalid、filter/paging/sort、time、format/content negotiation 和 error model；
- protocol：适用的 OGC CITE/ATS、STAC validator、TileJSON/MapLibre Style、COG validator、3D Tiles validator；
- visual：style、label、scale/generalization、nodata/colormap、LOD 和跨 revision golden screenshot/descriptor；
- security：允许/拒绝矩阵覆盖 feature/tile/raster/STAC/3D/download/preview/capabilities/error，provider direct-access negative test；
- lifecycle：idempotent deploy、持续流量下 atomic activation、failed deploy、rollback、deprecate/retire、cache warmup/invalidation 和 consumer notification；
- resilience：provider/Gateway restart、partial failure、stale external state、cancel/reconcile、projection rebuild、backup/restore、upgrade/rollback 和 degraded mode；
- SLO/cost：build/warmup/activation/rollback time、availability、p50/p95/p99、error/timeout、cache hit/staleness、throughput、saturation、bytes/egress 和 per-consumer cost。

只有代码、真实 provider、自动化测试、运行产物、SLO 证据、owner/on-call、backup/restore 和升级回滚全部存在时，状态才可从 `experimental`/`certified` 进入 `production-supported`。HTTP 200、地图显示、配置文件或 mock publisher 均不是生产准入证据。

## Rationale

1. 服务生命周期跨越多个 GIS server 和部署 profile，必须由独立控制面持有，否则产品版本、策略、消费者和回滚会被 provider 配置割裂。
2. pg_featureserv、pygeoapi、Martin、TiTiler、pgSTAC/stac-fastapi 和 GeoServer 各自在不同协议和 workload 上有优势，组合式 provider 比单 server 承担所有职责更符合现有 PostGIS/COG/STAC 架构。
3. 3D Tiles 作为开放默认交换层，S3M/I3S 作为 adapter，既保留国产/商业生态，又避免把平台合同锁定为单厂商格式。
4. DolphinScheduler 统一长任务和构建任务，避免 GIS server 再产生不可审计的第二调度系统。
5. immutable revision + active pointer + cache namespace 把数据、样式、路由和缓存纳入同一次可回滚发布，避免混合版本。
6. LLM 可选的同合同多入口保证离线和受限环境仍是完整 Data Platform，Agent 只降低操作复杂度。

## Trade-offs Accepted

- 平台需要维护多个 provider adapter、capability matrix 和 conformance suite，而不是只维护一个 GIS server。
- 不同 provider 的过滤、样式、CRS、事务和 3D 能力不能假装完全等价；provider-native 定义会降低可移植性。
- active revision 和 immutable cache namespace 会增加受控存储副本与短时双版本资源开销。
- GeoServer、SuperMap、ArcGIS 和云 GIS 的高级能力只有逐项认证后才能暴露，首期功能数量可能少于直接透传全部菜单。

## Consequences

### Positive

- GIS 服务成为 DataProduct 的受治理消费产品，而不是散落 endpoint。
- 开源默认、商业兼容、云替换和轻量部署共用一个生命周期和验收标准。
- 图层、样式、二维/三维、缓存、权限、消费者、SLO 和回滚可以端到端追溯。
- provider 或 Gateway 可独立替换，不改变上层 ServiceDefinition 和消费者合同。

### Negative

- 需要新增服务控制对象、发布状态机、provider SPI、Gateway adapter 和跨协议测试资产。
- 多 provider 的镜像、CVE、许可、升级和运维责任增加。
- 复杂制图和跨 provider visual equivalence 不能只用结构化 schema 测试，需要 golden render 和人工审核门。

### Mitigation

- 首条 vertical slice 只认证 Feature、MVT、COG/TiTiler、STAC 和一个 legacy OGC/3D 代表任务，再按真实需求扩展。
- production-supported 清单按 capability 而非产品名称发布，避免“接入 GeoServer/ArcGIS 即支持全部功能”的错误声明。
- provider-native style/process/3D definition 明确标记 portability class，迁移必须产生 ChangeSet 和 consumer impact。
- 统一 OTel、SLO、事故、备份恢复和升级 playbook；未指定 owner/on-call 的 provider 不进入生产。

## Acceptance Conditions

本 ADR 从 Proposed 转为 Accepted 前必须具备：

1. 当前 endpoint、provider、style/cache、consumer、外网暴露和许可事实清单。
2. 冻结的 Feature/MVT/COG/STAC/legacy OGC/3D/Process 数据集、流量、安全负向用例和 SLO/cost 基线。
3. pg_featureserv/pygeoapi 分工、pgSTAC/stac-fastapi、GeoServer 和 APISIX 的真实部署 benchmark；Martin/TiTiler 与当前 PostGIS/MinIO 路径的集成证据。
4. 至少一个商业或云 provider adapter 的 capability discovery 和 deployment dry-run，证明 SPI 没有只为默认开源栈设计。
5. 无 LLM 的 Web/API/SDK/CLI/TUI publish/observe/rollback contract test 设计。
6. Security、GIS Engineering、DataOps、SRE 对 owner、policy enforcement、RPO/RTO、upgrade 和 incident boundary 的批准。

## Revisit Triggers

- 默认 provider 无法达到冻结的协议、SLO、安全、许可或运维成本门。
- 主要客户以 legacy OGC、ArcGIS、SuperMap、云 GIS 或 3D 为主，默认 provider 组合导致不可接受的功能或迁移损失。
- provider capability 差异导致控制面抽象持续泄漏，必须拆分 capability-specific SPI。
- APISIX 无法满足私有化 OIDC、WAF、流式大文件、观测、HA 或升级要求。
- tile/raster/3D 流量使 Gateway/cache 成为瓶颈，需要 CDN、专用 edge 或多区域发布。
- 事务型 WFS-T/Feature editing 成为核心需求，需要把编辑服务与只读发布服务分离评审。
- OGC API、STAC、3D Tiles、S3M 或 I3S 标准/生态发生不兼容演进。

# GIS Data Agent 完整中间件清单

更新时间：2026-08-08

## 1. 文档范围

本文按 GIS Data Agent 仓库当前已接受的架构决策、Compose/Kubernetes 配置和 Windows standalone 离线包整理完整私有化生产架构的中间件 BOM。

本文区分以下状态：

- **当前包已有**：当前 `GIS-Data-Agent-Windows-production.zip` 已携带对应介质。
- **当前包缺失**：完整生产架构需要或仓库已有相关实现，但当前 Windows ZIP 未携带。
- **条件组件**：仅在相应 workload、协议、许可或专项能力启用时部署。
- **版本待冻结**：仓库已选择该组件或能力，但还没有经过认证的精确离线 BOM。

当前 Windows ZIP 实质上是轻量单机 profile，不是本文所列完整生产架构的等价离线部署。

## 2. 数据库与湖仓

| 中间件 | 版本基线 | 作用 | 当前 Windows ZIP |
|---|---|---|---|
| PostgreSQL | 16.x；当前介质 16.4-1 | 控制面、业务库、运行记录和 serving 数据 | 当前包已有 |
| PostGIS | 当前介质 3.6.2-1 | 空间类型、索引和空间 SQL | 当前包已有，但安装脚本静默参数存在缺陷 |
| pgvector | 0.8.6 for PostgreSQL 16 | embedding/vector 检索 | 当前包已有 |
| MinIO Server | Compose 固定 `RELEASE.2025-04-22T22-12-26Z` | Raw、COG、模型、artifact 和湖仓对象存储 | 当前包已有；Windows 二进制版本未登记 |
| MinIO Client (`mc`) | Compose 固定 `RELEASE.2025-04-16T18-13-26Z` | bucket 初始化和对象存储运维 | 当前包已有 |
| Apache Iceberg | 当前 Spark runtime JAR 为 1.6.1 | 表格式、快照、schema evolution 和 time travel | 当前包缺失 |
| Iceberg REST Catalog | 版本待认证 | 多写者 catalog、锁和表元数据服务 | 当前包缺失 |
| DuckDB + Spatial | DuckDB 1.4.3；嵌入式 | 单机、边缘和较小数据集的轻量计算 | 当前包已有；不是独立服务 |

架构依据：[`ADR-001`](../../docs/architecture-decisions/adr-001-geospatial-lakehouse-and-postgis-boundary.md)。

## 3. 批处理与流处理

| 中间件 | 版本基线 | 作用 | 当前 Windows ZIP |
|---|---|---|---|
| Apache Spark | 当前 JAR 坐标面向 Spark 3.5 / Scala 2.12；发行版仍需冻结 | 默认批处理执行器 | 当前包缺失 |
| Apache Sedona | 1.9.0 | Spark 空间 SQL、矢量和栅格计算 | 当前包缺失 |
| Hadoop AWS/S3A | 3.3.4 | Spark 访问 MinIO/S3 | 当前包缺失 |
| Apache Livy | 版本待冻结 | Spark REST 作业提交 | 当前包缺失 |
| Apache Flink | 1.19.3 / Scala 2.12 / Java 11 认证基线 | CDC、流处理、checkpoint 和故障恢复 | 当前包缺失 |
| Flink CDC Connectors | 随认证 BOM 固定 | PostgreSQL CDC 等数据同步 | 当前包缺失 |
| Kafka 或 Redpanda | 版本按 workload 认证 | 高吞吐事件总线和持久缓冲 | 条件组件，默认不启用 |
| Debezium | 随 Flink/CDC BOM 固定 | CDC 日志解析 connector | 条件组件，默认不独立常驻 |

Spark/Flink 是完整生产能力的一部分。是否常驻应由 workload 和 SLO 决定，但其离线介质、配置和认证证据不能从完整交付清单中消失。

## 4. 调度与持久化编排

| 中间件 | 版本基线 | 作用 | 当前 Windows ZIP |
|---|---|---|---|
| Apache DolphinScheduler | 精确版本尚未冻结 | DataOps DAG、定时、补数、资源队列和告警 | 当前包缺失 |
| DolphinScheduler API/Master/Worker/Alert | 随 DolphinScheduler BOM | DolphinScheduler 运行组件 | 当前包缺失 |
| DolphinScheduler metadata DB/registry | 随认证部署 profile | 调度状态和服务注册 | 当前包缺失 |
| Temporal Server | 1.31.2 认证基线 | Agent、审批、长事务、重试和补偿 | 当前包缺失 |
| Temporal Worker/UI | 随 Temporal BOM | 工作流执行和运维界面 | 当前包缺失 |
| Temporal metadata DB | PostgreSQL profile | 持久化 workflow history | 当前包缺失 |

架构依据：[`ADR-007`](../../docs/architecture-decisions/adr-007-dolphinscheduler-temporal-orchestration-platform.md)。

Windows Task Scheduler 只能承担单机进程拉起，不能等价替代 DolphinScheduler 或 Temporal。

## 5. 元数据与治理

| 中间件 | 版本基线 | 作用 | 当前 Windows ZIP |
|---|---|---|---|
| OpenMetadata | 1.13.1 基线 | 治理目录、术语、质量、血缘和搜索 | 当前包缺失 |
| OpenSearch/Elasticsearch | 与 OpenMetadata 认证版本一致 | OpenMetadata 搜索后端 | 当前包缺失 |
| OpenMetadata metadata DB | 独立 PostgreSQL/MySQL profile | OpenMetadata 状态库 | 当前包缺失 |
| Apache Gravitino | 1.3.x 认证线 | technical metadata lake 和 catalog federation | 当前包缺失 |
| Gravitino metadata store | 随 Gravitino BOM | metalake/catalog 状态 | 当前包缺失 |
| OpenLineage | 版本化事件协议 | 串联 Spark、Flink、DolphinScheduler、Temporal 和 OpenMetadata | 仅有代码/合同，完整运行链缺失 |

架构依据：[`ADR-006`](../../docs/architecture-decisions/adr-006-openmetadata-governance-and-active-metadata-platform.md)。

## 6. 缓存、语义与模型服务

| 中间件 | 版本基线 | 作用 | 当前 Windows ZIP |
|---|---|---|---|
| Redis | 7 | 缓存、通知、实时流和轻量队列；不能作为唯一作业真值 | 当前包缺失 |
| OpenJDK/JRE | Temurin 17.0.20+8 | Java 服务运行时 | 当前包已有 |
| Apache Jena/TDB2 | 6.2.0 | RDF 本体加载和存储 | 当前包已有 |
| Apache Fuseki | 6.2.0 | SPARQL/本体查询服务 | 当前包已有 |
| Ollama | 当前 Windows 介质版本未登记 | 本地 LLM 和 embedding 服务 | 当前包已有 |

下列是模型制品，不是中间件程序，但离线模型服务必须携带：

| 模型制品 | 作用 | 当前 Windows ZIP |
|---|---|---|
| Gemma4 26B GGUF | 主问数模型 | 当前包已有 |
| Nomic Embed Text v2 MoE GGUF | embedding 模型 | 当前包已有 |
| Paper9 ONNX ensemble | 农田优化运行模型 | 当前包已有 |

## 7. GIS 发布与访问服务

| 中间件 | 定位 | 当前 Windows ZIP |
|---|---|---|
| GDA typed API + PostGIS/DuckDB adapter | SQL/属性查询和统一控制合同 | 应用内已有 |
| pg_featureserv | PostGIS 的 OGC API Features 轻量出口 | 当前包缺失 |
| pygeoapi | 多源 OGC API/Processes facade | 当前包缺失 |
| Martin | 0.18.0；PostGIS MVT/矢量瓦片服务 | 当前包缺失 |
| TiTiler | MinIO COG 栅格窗口、重采样和渲染 | 当前包缺失 |
| pgSTAC | STAC PostgreSQL catalog | 当前包缺失 |
| stac-fastapi | STAC API 服务 | 当前包缺失 |
| GeoServer | WMS/WFS/WMTS/WCS 和 SLD 兼容 provider | 条件组件，当前包缺失 |
| FROST-Server/EDR provider | SensorThings/时空观测接口 | 条件组件，当前包缺失 |
| Apache APISIX | API Gateway、OIDC、限流和 WAF 私有化候选 | 候选组件，当前包缺失 |
| SuperMap/ArcGIS Enterprise adapter | 商业 GIS provider | 按许可和现场条件提供 |
| PDAL/Entwine/Py3DTilers | 点云和 3D Tiles 构建执行器 | 条件组件，当前包缺失 |

架构依据：[`ADR-017`](../../docs/architecture-decisions/adr-017-gis-service-publishing-control-plane-and-provider-runtime.md)。

## 8. 专项质检与工具服务

| 服务 | 作用 | 当前 Windows ZIP |
|---|---|---|
| CV Service | YOLO、OCR、影像和测绘视觉质检 | 当前包缺失 |
| CAD Parser | DXF/DWG、网格和三维解析 | 当前包缺失 |
| Reference Data Service | 控制点、基准和精度比对 | 当前包缺失 |
| ArcGIS MCP Server | ArcGIS 工具适配 | 当前包缺失 |
| QGIS MCP Server | QGIS 工具适配 | 当前包缺失 |
| Blender MCP Server | 三维工具适配 | 当前包缺失 |

这些专项服务不能由内置 GeoPandas/rasterio 质检自动替代。未部署时必须显式标记对应 capability 不可用。

## 9. 监控、安全与部署基础设施

| 中间件/基础设施 | 作用 | 当前 Windows ZIP |
|---|---|---|
| Prometheus | 指标采集和告警数据源 | 当前包缺失；构建仅产生 warning |
| Grafana | 监控可视化 | 当前包缺失；构建仅产生 warning |
| OpenTelemetry Collector | trace、metric 和 log 汇聚 | 架构要求，部署制品缺失 |
| OIDC Identity Provider | 用户和工作负载身份 | 实现未选择；需接现场 IdP |
| Ingress Controller/API Gateway | TLS、路由和入口控制 | 当前包缺失 |
| Docker/Compose 或 Kubernetes | 承载 Linux 中间件 | 当前 Windows ZIP 主动排除 |

## 10. 完整生产离线交付的必要载体

完整私有化生产交付不应被限定为单一原生 Windows ZIP。建议采用以下交付结构：

1. Windows 应用/GIS 节点包：应用、Python/GIS 运行时、PostgreSQL/PostGIS（如选择本机数据库）、模型和运维脚本。
2. Linux 中间件离线镜像包：Spark/Sedona、Flink、DolphinScheduler、Temporal、OpenMetadata/OpenSearch、Gravitino、Iceberg Catalog、Redis、GIS 发布服务和监控组件。
3. OCI 镜像归档：所有镜像使用 digest 锁定，并通过 `docker save`/兼容 OCI archive 交付。
4. 编排文件：经验证的 Compose 或 Kubernetes manifests、配置模板、Secrets 清单和资源基线。
5. 供应链文件：组件版本、来源、许可证、SHA-256、SBOM、CVE 基线和升级/回滚说明。
6. 验收资产：健康检查、端到端 smoke、备份恢复、断网重启、故障恢复和跨组件 conformance 报告。

## 11. 当前 Windows ZIP 覆盖结论

当前 ZIP 已覆盖：

- PostgreSQL/PostGIS/pgvector
- MinIO 和 `mc`
- DuckDB（嵌入式）
- JRE/Jena/Fuseki
- Ollama
- Gemma4、Nomic embedding 和 Paper9 模型制品

当前 ZIP 未覆盖完整生产架构中的：

- Iceberg 和 Iceberg Catalog
- Spark/Sedona/Livy
- Flink/CDC runtime
- DolphinScheduler
- Temporal
- OpenMetadata/OpenSearch
- Gravitino
- Redis
- 完整 GIS 发布 provider 组合
- 专项 QC 服务
- Prometheus/Grafana/OpenTelemetry
- 生产入口、OIDC 和 Gateway

因此，当前 `production` profile 更准确的名称应是 Windows 单机轻量测试/运行 profile，不能声称与仓库完整私有化生产架构等价。

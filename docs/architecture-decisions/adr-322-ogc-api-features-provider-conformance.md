# ADR-322: OGC API Features provider conformance stays release-bound

## Status

Accepted for the AR-4 P0 implementation slice (2026-08-26)

## Context

AR-0 的首条 GIS 发布链路需要同时支持 OGC API Features 和 MVT。控制面已经能够管理
GIS service、layer、release、deployment、endpoint 和 active pointer，但 OGC API Features
此前只有源连接器，没有可用于部署终态的 provider 证据。仅探测根路径的 HTTP 200 无法证明
collection 可发现、items 可读、GeoJSON 合法，也无法证明响应属于当前产品版本。

## Decision

1. 使用现有 Service Control Plane/Gateway 作为唯一服务、release、deployment 和 endpoint 权威；provider runtime 只负责数据面读取和证据生成。
2. 为 pygeoapi 兼容 provider 定义只读 manifest，并依次探测根路径、`/conformance`、`/collections` 和精确的 `/collections/{collection_id}/items`。
3. endpoint contract 固定为 `gda.ogc_api_features_endpoint.v1` 加 `collection_id`；migration 238 在 endpoint 写入和 active activation 触发器中校验 collection 与 release layer key 一致，防止激活一个未绑定图层的 endpoint。
4. items 响应必须是非空 GeoJSON FeatureCollection，媒体类型为 `application/json` 或 `application/geo+json`，返回 feature 数量不得超过请求 `limit`；bbox 采用有限且有序的四元组。
5. conformance receipt 固化 provider origin/version、产品和 layer identity、release binding、conformance/catalog checksum、请求窗口、响应 checksum 和 feature count，并嵌入已有 `gda.gis_service_deployment_observation.v2` 终态证据。

## Options considered

| 方案 | 取舍 |
| --- | --- |
| 继续复用 `OgcApiConnector` | 适合数据源查询，但没有 release identity、GeoJSON 强校验和部署终态 receipt，不足以作为发布门禁。 |
| 让 provider 自己维护 collection/发布注册表 | 能快速接入，但会产生第二套服务生命周期和 active pointer，与 ADR-017 冲突。 |
| 在现有 Gateway 上增加 release-bound provider runtime | 复用既有 authority、settlement、审计和回滚路径，新增代码只覆盖 Features 数据面合同。 |

## Consequences

- 成功：OGC API Features 与 MVT 使用相同的 deployment terminal settlement 和 active endpoint 机制；provider 可以替换为 pg_featureserv、pygeoapi 或其他兼容实现。
- 成功：错误 collection、空响应、错误媒体类型、非法 GeoJSON、超界 limit/bbox 和 HTTP 5xx 都会 fail closed。
- 代价：当前切片仍是 pygeoapi-compatible，尚未证明真实生产 pygeoapi 集群的 OGC CITE、性能、权限下推、缓存和 HA；这些继续作为 AR-4 退出条件。
- 代价：只读 Features contract 不覆盖事务、过滤语言、分页 token、复杂 CRS 和 OGC API 其他扩展，后续按实际 workload 增量认证。

## Evidence boundary

- 代码和聚焦测试：`data_agent/test_ogc_api_features_provider.py`、`data_agent/test_certify_ogc_api_features_provider.py`。
- disposable 认证：`scripts/certify_ogc_api_features_provider_disposable.py`，报告标记为 `synthetic_disposable`，不计为生产证据。
- 真实环境认证入口：`scripts/certify_ogc_api_features_provider.py`，要求已有 active projection、endpoint owner 和 provider origin；当前未宣称生产完成。
- 真实 provider 认证：`scripts/certify_ogc_api_features_pygeoapi.py` 使用
  `geopython/pygeoapi:latest`（容器内 `pygeoapi 0.25.dev0`）和一次性 GeoJSON collection，5 项检查通过，
  返回 2 个 feature；报告位于 `.tmp/ogc-api-features-pygeoapi-certification/report.json`，SHA-256 为
  `b75c801b8af50fcb839331274df03c82185a17652f3b996850bd53f23d739f08`，receipt SHA-256 为
  `b03dacd2e7933431f954a653c76900900e63eaa2b1824e600932f4e20c7f22f0`。该报告的
  `evidence_class` 为 `real_provider_disposable_control_fixture`：provider HTTP 行为是真实 pygeoapi，
  但控制面 ID 是 disposable fixture，不等于 active Gateway 或生产认证。
- active release 认证：`scripts/certify_ogc_api_features_active_release.py` 在临时 PostgreSQL 中应用
  migration 238，经过 `PlatformGateway` 注册并激活 feature service、release、deployment 和 OGC endpoint，
  再接入真实 pygeoapi 完成 `active_release_read_certified`。报告位于
  `.tmp/ogc-api-features-active-release-certification/report.json`，SHA-256 为
  `f605332fd034766cd56c7a5d2f9b01a73843690568c8b16305dd9d75412a243e`，receipt SHA-256 为
  `ce7aeda568fbde418fd54f923bd65e956db28c65d2907ca993c30b382b89e92a`。该报告还记录了
  migration 238 对错误 `collection_id` 的运行时拒绝。该报告的
  `evidence_class` 为 `real_provider_disposable_postgresql_control_fixture`：它证明 provider 与既有
  Gateway authority 的集成路径，不证明生产数据库、生产 endpoint、OGC CITE、权限下推、性能、缓存或 HA。

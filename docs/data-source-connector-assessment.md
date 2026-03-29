# 数据源接入能力评估与演进规划

**评估对象**: GIS Data Agent (ADK Edition) v14.3.1
**评估日期**: 2026-03-21
**核心问题**: 当前数据来源依赖手动预处理导入，需评估用户自助接入数据源的能力现状与演进路径

---

## 一、现有数据接入通道

系统已具备 5 种数据接入通道：

| 通道 | 模块 | 代码量 | 成熟度 | 说明 |
|------|------|--------|--------|------|
| 文件上传 | `app.py` handle_uploaded_file | — | 成熟 | 10+ 格式，ZIP 自动解压，用户沙箱隔离，500MB 上限 |
| PostGIS 直连 | `database_tools.py` | — | 成熟 | RLS 行级安全，表权限注册，几何列自动检测 |
| 虚拟数据源 | `virtual_sources.py` | 845 行 | 可用 | WFS/STAC/OGC API/自定义 REST，凭证加密，健康检查 |
| IoT 流式接入 | `stream_engine.py` | — | 可用 | HTTP + WebSocket 双通道，地理围栏告警，窗口聚合 |
| MCP 外部工具 | `mcp_hub.py` | 774 行 | 可用 | stdio/SSE/HTTP 三种传输，热加载，工具名前缀隔离 |

---

## 二、各通道详细能力

### 2.1 文件上传（最成熟）

**支持格式：**

| 类别 | 格式 |
|------|------|
| 矢量 | Shapefile (.shp), GeoJSON (.geojson), GeoPackage (.gpkg), KML (.kml), KMZ (.kmz) |
| 栅格 | GeoTIFF (.tif/.tiff), IMG (.img), NetCDF (.nc) |
| 表格 | CSV (.csv), Excel (.xlsx/.xls) |
| 文档 | PDF (.pdf), 图片 (.png/.jpg) |

**关键特性：**
- CSV/Excel 自动检测坐标列（lng/lat, lon/lat, longitude/latitude, x/y）
- KMZ 自动解压提取 KML
- ZIP 自动解压提取 Shapefile 组件（.shp/.dbf/.shx/.prj）
- 多模态分类：空间数据 vs 图片 vs PDF（`classify_upload()`）
- 用户沙箱：`uploads/{user_id}/`，路径解析优先用户目录

### 2.2 PostGIS 直连

**工具集：**
- `query_database(sql_query)` — 只读 SELECT/WITH，几何自动转 GeoDataFrame
- `list_tables()` — 枚举用户可访问的表（`agent_table_ownership` 注册）
- `describe_table(table_name)` — Schema 检查

**安全机制：**
- 查询前注入 `SET app.current_user` / `SET app.current_user_role`
- RLS 预留（策略未实际创建）
- 只读强制（DB 层面）

### 2.3 虚拟数据源（用户自助接入的核心）

**支持的远程源类型：**

| 类型 | 查询能力 | 认证方式 |
|------|----------|----------|
| WFS | FeatureType + CQL 过滤 + BBOX + 版本控制 | Bearer / Basic / API Key / None |
| STAC | Collection + 时间范围 + 云量过滤 | 同上 |
| OGC API Features | Collection + BBOX + JSON 解析 | 同上 |
| 自定义 REST API | 模板 URL + GET/POST/PUT/PATCH + JSON Path 提取 | 同上 |

**管理特性：**
- 每用户最多 50 个数据源
- 凭证 Fernet 加密存储（密钥来自 `CHAINLIT_AUTH_SECRET`）
- 刷新策略：`on_demand`, `interval:5m/30m/1h`, `realtime`
- Schema 映射：embedding 语义推断字段对应关系
- CRS 自动对齐
- 健康检查端点

**Agent 工具：**
- `list_virtual_sources_tool()` — 枚举可用源
- `query_virtual_source_tool()` — BBOX/过滤/限制查询
- `preview_virtual_source_tool()` — 快速预览（前 N 条）
- `register_virtual_source_tool()` — 注册新源
- `check_virtual_source_health_tool()` — 连通性测试

**REST API：**
- `GET /api/virtual-sources` — 列表
- `POST /api/virtual-sources` — 注册
- `GET /api/virtual-sources/{id}` — 详情
- `PUT /api/virtual-sources/{id}` — 更新
- `DELETE /api/virtual-sources/{id}` — 删除
- `POST /api/virtual-sources/{id}/test` — 健康检查

### 2.4 IoT 流式接入

- 命名流创建，可配置聚合窗口（5–3600 秒）
- 地理围栏告警（WKT 多边形）
- 实时统计：事件数、设备数、质心、空间分布
- `POST /api/streams/{id}/ingest` — HTTP 推送
- `WS /ws/streams/{id}` — WebSocket 订阅

### 2.5 MCP 外部工具

- DB + YAML 双配置源
- 三种传输：stdio（本地进程）、SSE（服务端推送）、streamable_http
- 工具名前缀隔离，避免冲突
- 热加载：运行时增删服务器
- 健康状态追踪：connected / disconnected / error / timeout

---

## 三、数据源覆盖度分析

### 已覆盖

| 数据源类型 | 接入方式 | 用户自助 |
|-----------|----------|----------|
| 本地文件（SHP/GeoJSON/CSV/Excel/KML/GPKG/PDF） | 文件上传 | 是 |
| PostgreSQL/PostGIS | 直连 | 否（需管理员导入） |
| WFS (OGC Web Feature Service) | 虚拟数据源 | 是 |
| STAC (时空资产目录) | 虚拟数据源 | 是 |
| OGC API Features | 虚拟数据源 | 是 |
| 自定义 REST API | 虚拟数据源 | 是 |
| IoT 设备流 | 流式引擎 | 是 |
| 外部 AI/工具服务 | MCP Hub | 是 |

### 未覆盖但常见

| 数据源类型 | 典型场景 | 实现难度 | 优先级 |
|-----------|----------|----------|--------|
| WMS/WMTS 瓦片服务 | 底图叠加、遥感影像服务发布 | 低 | P1 |
| ArcGIS REST FeatureServer | 政府/企业 ArcGIS Server 数据 | 中 | P1 |
| 关系型数据库 (MySQL/SQLite/Oracle) | 业务系统数据接入 | 中 | P1 |
| S3/OSS/OBS 对象存储 | 云端数据湖直接拉取 | 中 | P1 |
| FTP/SFTP | 传统数据交换渠道 | 低 | P2 |
| Excel/Google Sheets 在线表格 | 非技术用户数据来源 | 低 | P2 |
| GeoServer REST API | 开源 GIS 服务器管理 | 低 | P2 |
| Kafka/RabbitMQ 消息队列 | 实时数据管道 | 高 | P3 |
| GraphQL API | 现代 API 架构 | 中 | P3 |
| Elasticsearch/OpenSearch | 地理空间搜索引擎 | 中 | P3 |

---

## 四、架构层面的关键缺口

当前的核心问题不是"支持多少种数据源"，而是架构上的 5 个结构性缺口：

### 4.1 连接器未插件化

**现状：** `virtual_sources.py` 中 4 种 source_type 通过 if-elif 分支硬编码，新增类型需修改源码。

**目标：** 抽象为 `BaseConnector` 基类 + 注册机制。

```
BaseConnector
├── WFSConnector          # OGC WFS
├── STACConnector         # 时空资产目录
├── OGCAPIConnector       # OGC API Features
├── RESTConnector         # 通用 REST API
├── ArcGISConnector       # ArcGIS REST FeatureServer  [新增]
├── DatabaseConnector     # 多数据库连接              [新增]
├── ObjectStorageConnector # S3/OSS/OBS              [新增]
└── WMSConnector          # WMS/WMTS 瓦片服务         [新增]
```

**收益：** 用户可通过 User Tools 的 `http_call` 模板自定义连接器，无需改代码。

### 4.2 无增量同步 / CDC

**现状：** 刷新策略有 `on_demand` 和 `interval`，但每次都是全量查询。

**问题：** 对大数据源（百万级记录）不可接受，且浪费带宽和计算。

**目标：**
- 基于时间戳的增量拉取（`WHERE updated_at > last_sync_time`）
- 基于版本号/ETag 的变更检测
- 增量合并策略（upsert / append / replace）

### 4.3 前端缺少数据源管理体验

**现状：**
- 虚拟数据源有完整 REST API（6 个端点）
- 前端 DataPanel 有 "Virtual Sources" Tab
- 但缺少可视化的字段映射编辑器和数据预览面板

**目标：**
- 数据源注册向导（选类型 → 填连接信息 → 测试 → 映射字段 → 预览 → 保存）
- 字段映射拖拽编辑器（源字段 ↔ 目标字段）
- 实时数据预览（前 100 条 + 统计摘要）
- 连接状态仪表盘（健康/异常/离线）

### 4.4 单一数据库实例

**现状：** `db_engine.py` 是单例模式，整个系统只连一个 PostGIS 实例。

**问题：** 用户无法接入自己的数据库（MySQL/PostgreSQL/Oracle）。

**目标：**
- 用户注册外部数据库连接（连接串 + 凭证加密存储）
- 连接池隔离（每个外部连接独立池，防止互相影响）
- 只读强制（外部数据库只允许 SELECT）
- 查询超时保护

### 4.5 凭证管理不完整

**现状：** Fernet 加密已有，支持 Bearer/Basic/API Key 三种认证。

**缺口：**
- 无 OAuth2 完整流程（授权码模式、刷新令牌）
- 无凭证轮换和过期提醒
- 无凭证使用审计（哪个凭证被谁在什么时候使用）

---

## 五、演进路线图

### 第一步：增强现有能力，补齐前端体验（2-3 周）

| 编号 | 改进项 | 模块 | 工作量 |
|------|--------|------|--------|
| S1-1 | DataPanel "数据源管理" Tab 增强 — 注册向导 + 连接测试 + 数据预览 | 前端 | 3-4 天 |
| S1-2 | 字段映射可视化编辑器 — 源字段 ↔ 目标字段拖拽映射 | 前端 | 2-3 天 |
| S1-3 | WMS/WMTS 连接器 — 后端注册管理 + 前端 Leaflet 图层叠加 | virtual_sources.py + MapPanel | 2 天 |
| S1-4 | ArcGIS REST FeatureServer 连接器 — JSON→GeoJSON 转换 | virtual_sources.py | 2 天 |
| S1-5 | 数据源健康监控面板 — 连接状态、最近同步时间、错误日志 | 前端 + API | 1-2 天 |

### 第二步：连接器插件化 + 多数据库（3-4 周）

| 编号 | 改进项 | 模块 | 工作量 |
|------|--------|------|--------|
| S2-1 | `BaseConnector` 抽象基类 + 连接器注册表 | 新模块 connectors/ | 3-4 天 |
| S2-2 | 现有 4 种 source_type 重构为 Connector 子类 | virtual_sources.py 重构 | 2-3 天 |
| S2-3 | `DatabaseConnector` — 用户注册外部数据库（MySQL/PostgreSQL/SQLite） | connectors/ | 3-4 天 |
| S2-4 | `ObjectStorageConnector` — S3/OSS/OBS 直接拉取 | connectors/ | 2-3 天 |
| S2-5 | 连接池隔离 + 查询超时保护 + 只读强制 | db_engine.py 扩展 | 2 天 |
| S2-6 | User Tools `http_call` 模板升级为自定义连接器 | user_tool_engines.py | 2 天 |
| S2-7 | OAuth2 授权码流程支持 | virtual_sources.py | 3 天 |

### 第三步：增量同步 + 数据编排（4-5 周）

| 编号 | 改进项 | 模块 | 工作量 |
|------|--------|------|--------|
| S3-1 | 增量同步引擎 — 时间戳/ETag 变更检测 + upsert/append 合并 | 新模块 sync_engine.py | 5-7 天 |
| S3-2 | Workflow Engine 增加 DataSource 节点类型 — 定时拉取→转换→入库 | workflow_engine.py | 3-4 天 |
| S3-3 | 同步历史记录 + 失败重试 + 告警通知 | sync_engine.py + audit | 2-3 天 |
| S3-4 | 数据源编排仪表盘 — 同步状态、数据量趋势、错误分布 | 前端 | 3-4 天 |
| S3-5 | FTP/SFTP 连接器 | connectors/ | 2 天 |
| S3-6 | Kafka/消息队列连接器（可选） | connectors/ | 5-7 天 |
| S3-7 | 数据源依赖图 — 哪些管道/报表依赖哪些数据源 | data_catalog.py 扩展 | 2-3 天 |

---

## 六、连接器插件化架构设计（参考）

```
data_agent/
├── connectors/
│   ├── __init__.py           # ConnectorRegistry 注册表
│   ├── base.py               # BaseConnector 抽象基类
│   ├── wfs.py                # WFSConnector
│   ├── stac.py               # STACConnector
│   ├── ogc_api.py            # OGCAPIConnector
│   ├── rest_api.py           # RESTConnector (通用)
│   ├── arcgis.py             # ArcGISConnector [新增]
│   ├── database.py           # DatabaseConnector [新增]
│   ├── object_storage.py     # ObjectStorageConnector [新增]
│   ├── wms.py                # WMSConnector [新增]
│   ├── ftp.py                # FTPConnector [新增]
│   └── kafka.py              # KafkaConnector [新增]
├── virtual_sources.py        # 重构：调用 ConnectorRegistry
└── sync_engine.py            # 增量同步引擎 [新增]
```

### BaseConnector 接口定义（概念）

```python
class BaseConnector(ABC):
    """数据源连接器基类"""

    connector_type: str           # 连接器类型标识
    display_name: str             # 显示名称
    auth_methods: list[str]       # 支持的认证方式
    supports_bbox: bool           # 是否支持空间过滤
    supports_incremental: bool    # 是否支持增量同步

    @abstractmethod
    async def test_connection(self, config: dict) -> dict:
        """测试连通性，返回 {ok: bool, message: str, latency_ms: int}"""

    @abstractmethod
    async def query(self, config: dict, params: QueryParams) -> QueryResult:
        """执行查询，返回 GeoDataFrame 或 dict"""

    @abstractmethod
    async def preview(self, config: dict, limit: int = 100) -> dict:
        """快速预览，返回前 N 条 + schema 信息"""

    @abstractmethod
    async def get_schema(self, config: dict) -> dict:
        """获取数据源 schema（字段名、类型、示例值）"""

    def get_incremental_cursor(self, config: dict, last_sync: dict) -> dict:
        """返回增量同步游标（默认不支持，子类可覆盖）"""
        raise NotImplementedError("This connector does not support incremental sync")
```

### ConnectorRegistry

```python
class ConnectorRegistry:
    """连接器注册表 — 支持内置 + 用户自定义"""

    _connectors: dict[str, type[BaseConnector]] = {}

    @classmethod
    def register(cls, connector_class: type[BaseConnector]):
        cls._connectors[connector_class.connector_type] = connector_class

    @classmethod
    def get(cls, connector_type: str) -> type[BaseConnector]:
        return cls._connectors[connector_type]

    @classmethod
    def list_types(cls) -> list[dict]:
        return [
            {
                "type": c.connector_type,
                "name": c.display_name,
                "auth_methods": c.auth_methods,
                "supports_bbox": c.supports_bbox,
                "supports_incremental": c.supports_incremental,
            }
            for c in cls._connectors.values()
        ]
```

---

## 七、与治理能力的关联

数据源接入能力的增强直接影响治理评估中的多个领域：

| 治理领域 | 关联点 |
|----------|--------|
| **元数据自动采集** | 连接器注册时自动采集远程源的 schema 元数据 |
| **数据血缘** | 数据源 → 同步任务 → 本地资产的完整链路追踪 |
| **数据质量监控** | 同步后自动触发质量检查（接入 Workflow Engine） |
| **数据安全** | 外部数据库连接的凭证管理、访问审计、只读强制 |
| **数据资源** | 更多数据源 = 更丰富的数据目录 = 更好的智能推荐 |

---

## 附录：现有代码文件索引

| 文件 | 数据接入相关功能 |
|------|-----------------|
| `app.py` | 文件上传处理、ZIP 解压、多模态分类 |
| `virtual_sources.py` | 虚拟数据源 CRUD、4 种连接器、凭证加密、健康检查 (845 行) |
| `database_tools.py` | PostGIS 查询、表枚举、Schema 检查、RLS 注入 |
| `stream_engine.py` | IoT 流创建、地理围栏、窗口聚合 |
| `mcp_hub.py` | MCP 服务器管理、3 种传输协议、热加载 (774 行) |
| `data_catalog.py` | 资产注册、元数据提取、血缘追踪、语义搜索 (1100+ 行) |
| `fusion/` | 多源融合、兼容性评估、质量验证 (22 模块) |
| `toolsets/fusion_tools.py` | 融合工具集 Agent 接口 |
| `toolsets/datalake_tools.py` | 数据湖工具集（资产管理、血缘查询） |
| `toolsets/virtual_source_tools.py` | 虚拟数据源 Agent 工具 |
| `toolsets/remote_sensing_tools.py` | 遥感数据下载（LULC/DEM/Sentinel-2/Landsat） |
| `user_tools.py` + `user_tool_engines.py` | 用户自定义工具（http_call 可作为自定义连接器） |
| `workflow_engine.py` | 工作流引擎（Cron/Webhook 触发，可编排数据拉取） |
| `frontend_api.py` | 虚拟数据源 REST API (6 端点) |

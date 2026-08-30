# ADR-183: NL2Semantic2SQL 双执行引擎

- 状态：accepted
- 日期：2026-08-08
- 决策范围：GIS Data Agent 智能问数

## 背景

系统已有稳定路线：自然语言经过数据模型、本体映射和语义层生成 SQL，最终由
PostgreSQL/PostGIS 执行。FileGDB 入湖和治理后同时会形成 GeoParquet；如果每次问数都要求先把
治理记录再次装载到 PostGIS，会增加一份物理副本、一次装载等待和一段额外血缘。

数据湖不能代替 PostGIS 的全部能力。复杂空间关系、成熟 PostGIS 函数、并发交互查询、事务、
行级权限和在线服务仍然更适合 PostGIS。因此问题不是二选一，而是让同一语义查询在受控条件下
选择不同物理执行器。

## 决策

保留以下两条并行路线：

1. `NL2Semantic2SQL -> PostgreSQL/PostGIS`：默认路线和生产基线。
2. `NL2Semantic2SQL -> DuckDB -> governed GeoParquet`：数据湖直查路线。

两条路线必须共享数据模型、本体概念、术语映射、指标口径、候选逻辑表和安全规则。差异只允许
发生在物理绑定、SQL 方言和执行器。选择方式为工具参数 `execution_engine`、请求上下文或环境变量
`GDA_NL2SQL_EXECUTION_ENGINE`；优先级依次为工具参数、请求上下文、环境变量、默认 `postgis`。

湖上执行器只能注册语义目录已经发布且文件存在的 GeoParquet 投影。模型生成的 SQL 不能调用
`read_parquet`、`read_csv`、`ATTACH`、`COPY`、`INSTALL`、`LOAD`、DDL 或 DML。运行时限制行数、
内存、线程和超时，并返回 projection ID/path 作为执行证据。

本体库不复制全部地类图斑记录。本体负责概念、关系、约束和到逻辑字段的映射；数据记录保留在
湖投影或 PostGIS 中。语义层把用户问题解析成同一逻辑查询，再由执行绑定选择物理来源。

Windows 物理隔离包固定 `duckdb==1.4.3`，必须携带同版 Windows AMD64
`spatial.duckdb_extension`。安装验收必须实际加载扩展并执行 `ST_Area`，不得现场联网安装。

## 选择原则

| 条件 | 默认选择 |
|---|---|
| 生产交互、复杂空间关系、RLS/事务、地图在线服务 | PostGIS |
| 刚完成治理、无需重复装载、属性筛选/聚合、批处理分析 | 数据湖 |
| 湖投影不存在 | PostGIS 或明确失败，不读任意文件 |
| 数据湖空间 SQL 但离线 Spatial 不可用 | 明确失败，不静默切换或降级 |

`auto` 只在调用方明确要求时使用；普通用户界面只显示 PostGIS 和数据湖两个确定选项，且默认
PostGIS，避免执行来源不透明。

## 后果

- DLTB 入湖治理后可直接问数，也可按发布策略装载 PostGIS；两者不再被描述成必然重复入库。
- Paper9 可消费同一治理投影，问数和算法通过 projection ID 共享来源和血缘。
- SQL 方言必须分别后处理，空间函数兼容性需要持续测试。
- 湖上路线不是 PostGIS 的替代声明；发布前必须对同一业务问题执行双引擎对账。

## 验证

重庆规划院 DLTB 治理投影共 101,657 条记录。四个固定问题在 DuckDB/GeoParquet 和临时 PostGIS
表上均成功，返回行数和抽样数值全部一致。证据见
`docs/reports/dltb_dual_nl2sql_engine_validation_2026-08-08.md`。

# ADR-004: Windows 物理隔离环境采用文件湖优先的离线接入

## Status

Accepted

## Context

宁夏时空数据底座部署在无容器、无外网的 Windows 主机；输入包括 FileGDB 目录、GeoTIFF/DEM、OSGB/OBJ 和大体量表格。接入必须支持断电续传、审计、标准映射、质量门禁和血缘重放。

## Decision

采用本地文件湖作为原始权威区，以 `OfflineIngestStore` 维护 upload session、SHA-256 manifest、分片 staging、原始区原子提交和 per-run JSONL 诊断。PostGIS 仅承载通过治理的标准化矢量；COG/STAC 和三维索引承载栅格/模型派生资产；本体只绑定通过质量门禁的标准化对象和语义索引。

## Rationale

1. 目录和大文件可以在 Windows 原生文件系统中可靠保存，不要求 Docker、S3 或消息队列。
2. FileGDB 作为 bundle 保留，避免拆分后无法恢复；GIS Data Agent 随安装包内置 `pyogrio/geopandas/rasterio/pyarrow` 及其 GDAL/PROJ 运行库，直接读取 FileGDB/SHP/TIFF，不依赖 ArcPy、ArcGIS Pro、MCP、容器或联网安装。
3. 分片 hash、全文件 hash、原子 rename 和 run manifest 能在断电或人工拷贝中断后恢复并审计。
4. 本体与原始载体解耦，避免把数亿条记录或栅格像元错误灌入知识库。

## Trade-offs

- 本地文件湖需要容量规划、备份和防篡改权限；由 Windows 文件服务器快照、离线备份和只读 ACL 缓解。
- 没有容器编排时，worker、PostgreSQL 和服务需要 Windows Service/任务计划单独运维；提供固定端口、日志轮转和诊断 zip。
- 内置运行时是正式执行路径；外部 `ogr2ogr/gdal_translate` 只作为超大规模任务的可选增强。发布包必须带版本锁定的 Windows wheels，并在启动前通过 FileGDB 读取、GeoParquet 写入和 COG 写入预检。

## Revisit triggers

当数据规模、并发采集或跨部门共享超过单机文件湖能力，或内网提供受控对象存储/调度平台时，重新评估 lakehouse 和集中式 lineage backend；原始不可变和质量门禁原则保持不变。

---
name: database
description: "数据库查询、表管理、数据导入与共享技能。PostgreSQL/PostGIS集成，支持SQL空间查询、表结构描述、数据导入。"
metadata:
  domain: database
  version: "1.0"
  intent_triggers: "database, sql, query, import, postgis"
---

# 数据库技能

## 核心能力

1. **SQL 查询**: `query_database` 执行 SQL 查询（支持 PostGIS 空间函数 ST_*）
2. **表管理**: `list_tables` 列出所有表、`describe_table` 描述表结构（字段名/类型/约束）
3. **数据导入**: `import_to_postgis` 将 SHP/GeoJSON/GPKG 导入 PostGIS（自动 CRS 检测）
4. **数据共享**: `share_table` 将查询结果共享为数据目录资产
5. **数据目录**: `list_data_assets` 浏览数据目录、`search_data_assets` 按关键词搜索

## PostGIS 使用规范

- 空间查询使用 `ST_Transform(geom, 4326)` 确保坐标系一致
- 面积计算使用 `ST_Area(ST_Transform(geom, <投影CRS>))` 获取平方米结果
- 距离计算使用 `ST_Distance(geom1::geography, geom2::geography)` 获取米制距离
- 空间索引: 查询性能依赖 GIST 索引，导入时自动创建
- RLS 已启用: `app.current_user` 上下文自动注入，查询结果限定为用户可见范围

---
name: postgis-analysis
description: "PostGIS空间数据库分析技能。使用ST_*空间函数执行空间查询、距离计算、面积统计和空间关系判断。"
metadata:
  domain: database
  version: "2.0"
  intent_triggers: "PostGIS, SQL, 空间查询, ST_, 数据库分析, 空间SQL"
---

# PostGIS 空间数据库分析技能

## 概述

本技能用于通过 PostGIS 空间函数对入库的矢量数据执行高效空间分析。涵盖空间关系判断、
距离与面积计算、几何操作和空间聚合，适用于用地合规检查、缓冲区分析、叠加统计等场景。
所有查询通过 `database_tools.py` 执行，自动注入用户上下文（`SET app.current_user`）。

## 核心空间函数

### 空间关系判断
- `ST_Intersects(A, B)`：A 与 B 是否有交集（最常用，配合空间索引高效过滤）
- `ST_Within(A, B)`：A 是否完全在 B 内部（如：地块是否在规划区内）
- `ST_Contains(A, B)`：B 是否完全包含 A（与 ST_Within 互逆）
- `ST_Crosses(A, B)`：A 是否穿越 B（如：道路是否穿越保护区）
- `ST_Touches(A, B)`：A 与 B 是否仅边界相接（邻接分析）
- `ST_Disjoint(A, B)`：A 与 B 是否完全不相交（排除分析）
- `ST_DWithin(A, B, distance)`：A 与 B 距离是否在阈值内（近邻搜索，利用索引）

### 距离与面积计算
- `ST_Distance(A::geography, B::geography)`：返回两几何体间最短距离（米）
- `ST_Area(geom::geography)`：返回面积（平方米），自动考虑椭球体
- `ST_Length(geom::geography)`：返回线要素长度（米）
- `ST_Perimeter(geom::geography)`：返回多边形周长（米）
- 注意：必须转为 `geography` 类型或投影坐标系才能获得米制单位结果

### 几何操作
- `ST_Buffer(geom, radius)`：缓冲区生成（geography 类型单位为米）
- `ST_Intersection(A, B)`：求交集几何体（叠加裁剪）
- `ST_Difference(A, B)`：A 减去 B 的差集（擦除操作）
- `ST_Union(geom)`：聚合函数，合并多个几何体（融合/溶解）
- `ST_Collect(geom)`：聚合函数，收集为 MultiGeometry（不合并边界）
- `ST_Centroid(geom)`：质心点（用于标注定位）
- `ST_ConvexHull(geom)`：凸包（最小外接凸多边形）
- `ST_MakeValid(geom)`：修复无效几何体（自相交、重复点等）

### 坐标变换
- `ST_Transform(geom, srid)`：坐标系转换
- 常用 SRID：4326（WGS84 经纬度）、4490（CGCS2000 经纬度）、32650（UTM 50N 投影）
- 面积计算前务必转换：`ST_Area(ST_Transform(geom, 32650))` 或 `ST_Area(geom::geography)`

## 空间索引优化

### GIST 索引原理
- PostGIS 使用 R-Tree 结构的 GIST 索引加速空间查询
- 索引作用于几何列的包围盒（Bounding Box），快速排除不相关记录
- 创建：`CREATE INDEX idx_geom ON table USING GIST(geom);`

### 查询优化策略
- 两阶段过滤：先用 `&&`（包围盒相交）粗筛，再用精确函数细筛
- `ST_Intersects` 已内置两阶段优化，优先使用
- 避免在 WHERE 中对几何列做函数变换（如 `ST_Transform`），会导致索引失效
- 正确做法：对比较对象做变换，或创建函数索引
- 大表连接：确保两张表的几何列都有 GIST 索引

### 查询模板

```sql
-- 缓冲区内要素统计（高效写法）
SELECT b.name, COUNT(*) AS cnt, SUM(ST_Area(a.geom::geography)) AS total_area_m2
FROM parcels a
JOIN protected_zones b ON ST_DWithin(a.geom::geography, b.geom::geography, 500)
GROUP BY b.name;

-- 叠加分析：耕地与规划区交集
SELECT a.parcel_id, b.zone_name,
       ST_Area(ST_Intersection(a.geom, b.geom)::geography) AS overlap_m2
FROM farmland a
JOIN planning_zones b ON ST_Intersects(a.geom, b.geom);

-- 面积汇总（按行政区）
SELECT district, SUM(ST_Area(geom::geography)) / 10000 AS area_hectares
FROM land_parcels
GROUP BY district
ORDER BY area_hectares DESC;
```

## 常见分析模式

### 合规检查
- 判断地块是否在禁建区/限建区内：`ST_Within(parcel.geom, zone.geom)`
- 计算侵占面积：`ST_Area(ST_Intersection(...)::geography)`
- 缓冲区退让检查：`ST_DWithin(building.geom::geography, river.geom::geography, 30)`

### 邻近分析
- K 近邻查询：`ORDER BY geom <-> ST_SetSRID(ST_MakePoint(lng, lat), 4326) LIMIT k`
- 服务区覆盖：`ST_Buffer` + `ST_Union` 生成服务范围，统计覆盖人口

### 空间聚合
- 按区域汇总：`GROUP BY district` + `SUM(ST_Area(...))`
- 融合同类地块：`ST_Union(geom)` + `GROUP BY land_type`
- 生成统计网格：结合 `ST_SquareGrid` 或 `ST_HexagonGrid`（PostGIS 3.1+）

## 工作流程

1. `list_tables` 查看可用数据表
2. `describe_table` 了解表结构、几何类型和坐标系
3. 根据分析需求构建空间 SQL（选择合适的 ST_* 函数）
4. 确认坐标系一致性（必要时加入 `ST_Transform`）
5. `execute_sql` 执行查询，检查结果
6. 将结果导出为 GeoJSON 或推送到前端地图可视化

## 常见问题与解决

- 面积为 0 或极小值：未转换坐标系，经纬度直接计算面积无意义，需转 geography 或投影坐标系
- 空间连接无结果：两表 SRID 不一致，用 `ST_Transform` 统一后再连接
- 查询极慢：检查是否缺少 GIST 索引；避免全表 `ST_Distance` 排序，改用 `ST_DWithin` 预过滤
- 无效几何报错：先执行 `ST_MakeValid(geom)` 修复，再做空间运算
- SQL 注入风险：所有用户输入通过参数化查询传递，禁止字符串拼接

## 相关工具

- `list_tables`：列出当前数据库中的空间表
- `describe_table`：查看表结构、字段类型、几何列信息
- `execute_sql`：执行 SQL 查询（自动注入用户上下文，支持 RLS）
- `import_to_postgis`：将本地文件导入 PostGIS 表

# PostGIS 常用空间函数速查

## 空间关系判断

| 函数 | 说明 | 示例 |
|------|------|------|
| `ST_Intersects(a, b)` | 是否相交（最常用） | `WHERE ST_Intersects(a.geom, b.geom)` |
| `ST_Within(a, b)` | a 完全在 b 内部 | 查找某区域内的所有点 |
| `ST_Contains(a, b)` | a 包含 b | 与 ST_Within 相反 |
| `ST_Overlaps(a, b)` | 部分重叠（同维度） | 查找重叠的面要素 |
| `ST_Touches(a, b)` | 边界相切但不重叠 | 查找相邻图斑 |
| `ST_Disjoint(a, b)` | 完全不相交 | 排除相交要素 |
| `ST_DWithin(a, b, d)` | 距离在 d 以内 | 缓冲区查询（比 ST_Buffer + ST_Intersects 快） |

## 空间操作

| 函数 | 说明 | 注意事项 |
|------|------|----------|
| `ST_Buffer(geom, dist)` | 创建缓冲区 | 投影坐标系下 dist 单位为米 |
| `ST_Intersection(a, b)` | 求交集 | 返回两个几何的公共部分 |
| `ST_Union(a, b)` | 求并集 | 合并两个几何 |
| `ST_Difference(a, b)` | 求差集 | a 减去 b 的部分 |
| `ST_SymDifference(a, b)` | 对称差 | 不重叠的部分 |
| `ST_Clip(rast, geom)` | 栅格裁剪 | 用矢量裁剪栅格 |

## 几何属性

| 函数 | 说明 | 注意事项 |
|------|------|----------|
| `ST_Area(geom)` | 面积 | 地理坐标系返回平方度！用 `::geography` 或投影 |
| `ST_Length(geom)` | 长度/周长 | 同上，注意单位 |
| `ST_Distance(a, b)` | 两几何距离 | `::geography` 返回米 |
| `ST_Centroid(geom)` | 质心 | 可能落在几何外部（凹多边形） |
| `ST_PointOnSurface(geom)` | 表面上的点 | 保证在几何内部 |
| `ST_Envelope(geom)` | 外接矩形 | 用于快速范围查询 |
| `ST_GeometryType(geom)` | 几何类型 | ST_Polygon, ST_MultiPolygon 等 |
| `ST_SRID(geom)` | 坐标系 SRID | 检查当前坐标系 |
| `ST_IsValid(geom)` | 几何是否有效 | 检查自相交等问题 |
| `ST_MakeValid(geom)` | 修复无效几何 | 自动修复自相交等 |

## 坐标系转换

```sql
-- 转换到 WGS84
SELECT ST_Transform(geom, 4326) FROM table;

-- 面积计算（方法1: geography 类型，返回平方米）
SELECT ST_Area(geom::geography) FROM table;

-- 面积计算（方法2: 投影到高斯带，返回平方米）
SELECT ST_Area(ST_Transform(geom, 4547)) FROM table;

-- 距离计算（米）
SELECT ST_Distance(a.geom::geography, b.geom::geography) FROM a, b;
```

## 聚合函数

| 函数 | 说明 | 用途 |
|------|------|------|
| `ST_Union(geom)` | 聚合合并 | 融合/溶解操作 |
| `ST_Collect(geom)` | 聚合收集 | 不合并，只打包为 Multi |
| `ST_Extent(geom)` | 聚合外接矩形 | 获取数据范围 |

## 空间索引

```sql
-- 创建 GIST 索引（必须！）
CREATE INDEX idx_table_geom ON table USING GIST (geom);

-- 查询时自动使用索引的条件:
-- 1. 使用 ST_Intersects, ST_DWithin, ST_Contains 等
-- 2. 使用 && 操作符（bbox 相交）
-- 3. WHERE 子句中包含空间谓词
```

## 查询优化模式

```sql
-- 好: 先用 && 过滤再精确计算
SELECT * FROM parcels a, rivers b
WHERE a.geom && ST_Expand(b.geom, 1000)
  AND ST_DWithin(a.geom::geography, b.geom::geography, 1000);

-- 好: 用 ST_DWithin 替代 ST_Buffer + ST_Intersects
SELECT * FROM points WHERE ST_DWithin(geom, target_geom, 500);

-- 差: 全表扫描
SELECT * FROM parcels WHERE ST_Area(geom) > 1000;
-- 好: 加索引列过滤
SELECT * FROM parcels WHERE geom && bbox AND ST_Area(geom) > 1000;
```

## 常见陷阱

1. **面积单位错误**: `ST_Area(geom)` 在 EPSG:4326 下返回平方度，不是平方米
2. **忘记空间索引**: 大表查询从秒级变分钟级
3. **ST_Centroid 在凹多边形外**: 用 `ST_PointOnSurface` 替代
4. **跨 SRID 操作**: `ST_Intersects(geom_4326, geom_4490)` 会报错，需先统一
5. **ST_Buffer 在地理坐标系**: 单位是度，buffer(1) = 约 111km

# Schema and table reference (family-invariant)

The benchmark's PostGIS database has these primary tables. Other tables exist
in the schema; only those listed here are guaranteed available for benchmark
questions.

## Tables

### `cq_land_use_dltb` — 国土调查地类图斑
- `"BSM"` (string) — 标识码 (parcel ID, primary key)
- `"DLBM"` (string) — 地类编码 (land-use code, hierarchical: e.g. 0101=水田 under 01=耕地)
- `"DLMC"` (string) — 地类名称 (land-use name, e.g. "水田", "旱地", "有林地")
- `"QSDWMC"` (string) — 权属单位名称 (ownership unit name)
- `"ZLDWMC"` (string) — 坐落单位名称 (location unit name)
- `"TBMJ"` (numeric) — 图斑面积 (PROJECTED area, do NOT use for real-world m²)
- `geometry` — geometry column (SRID 4490; cast to geography for real-world measurements)

### `cq_amap_poi_2024` — 高德 POI 数据
- `"ID"` (string) — POI primary key
- `"名称"` (string) — POI name
- `"类别"` (string) — POI category
- `geometry` — point geometry (SRID 4326)
- 1.19 million rows; queries must LIMIT or aggregate.

### `cq_buildings_2021` — 重庆中心城区建筑数据
- `"Id"` (string) — 建筑 ID
- `"Floor"` (int) — 楼层数 (number of floors)
- `geometry` — polygon geometry

### `cq_osm_roads_2021` — OpenStreetMap 道路
- `osm_id` (string) — OSM road ID
- `name` (string) — road name (lowercase column, no quoting)
- `fclass` (string) — road class: 'primary', 'secondary', 'residential', etc.
- `maxspeed` (int) — speed limit
- `oneway` (string) — 'F' / 'T' / 'B' (one-way direction)
- `bridge` (string) — 'T' / 'F' (is this a bridge segment)
- `geometry` — linestring geometry

### `cq_dltb` — 地类图斑（lowercase variant — older snapshot)
- `dlmc` (string) — 地类名称 (lowercase column, no quoting)
- `geometry` — geometry

### `cq_historic_districts` — 历史文化街区
- `jqmc` (string) — 街区名称
- `shape` (geometry) — boundary geometry (SRID may differ — check before joining)

## Identifier quoting reminder
- Uppercase or mixed-case columns must be double-quoted: `"DLMC"`, `"Floor"`, `"TBMJ"`.
- Lowercase columns may be used unquoted: `name`, `fclass`, `dlmc`.
- All string literals use single quotes: `WHERE "DLMC" = '水田'`.

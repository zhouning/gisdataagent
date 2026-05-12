-- =============================================================================
-- Migration DRAFT: register cq_land_use_dltb + cq_osm_roads_2021 in semantic layer
-- =============================================================================
--
-- STATUS: DRAFT — do NOT apply until v6 Phase 3 Gemma N=3 completes.
-- Applying this now would change the grounding results of the in-flight
-- experiment (s3 would see different semantic_layer matches than s1/s2).
--
-- MOTIVATION:
-- v6 audit (2026-05-11) found that two benchmark-covered tables were not
-- registered in agent_semantic_sources / agent_semantic_registry at
-- experiment time:
--   cq_land_use_dltb  — used in 13 golden_sql
--   cq_osm_roads_2021 — used in  7 golden_sql
-- The grounding fuzzy matcher was returning cq_dltb / cq_osm_roads as a
-- fallback, giving partial coverage. This migration registers the two
-- tables with column-level semantic annotations cloned from their parent
-- analogues (cq_dltb / cq_osm_roads), adapted for:
--   - UPPERCASE column names in cq_land_use_dltb (vs lowercase in cq_dltb)
--   - Absence of objectid and presence of SHAPE_Length/SHAPE_Area in
--     cq_land_use_dltb
--   - Absence of objectid and shape (geometry column is "geometry") in
--     cq_osm_roads_2021
--
-- POST-MIGRATION VERIFICATION:
--   1. Re-run the audit snippet from docs/nl2sql_v6_short_report.md §7.3
--      and confirm both tables now resolve via their own registry entry,
--      not via the fallback.
--   2. Run `resolve_semantic_context` with a test query referring to
--      cq_land_use_dltb and confirm sources[] contains cq_land_use_dltb.
--
-- OWNER: audit (inherits from migration 058_agent_aliases convention)
-- DATE: 2026-05-11 drafted, to be applied post-v6.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Part 1: agent_semantic_sources — table-level registration
-- -----------------------------------------------------------------------------
INSERT INTO agent_semantic_sources
  (table_name, display_name, description, geometry_type, srid, synonyms,
   suggested_analyses, owner_username)
VALUES
  ('cq_land_use_dltb',
   '土地利用现状图斑',
   '土地利用现状图斑（2021年更新版本），记录了更精细的土地利用类型、权属、面积等属性。地类编码遵循 GB/T 21010 标准。',
   'MULTIPOLYGON',
   4326,
   '["土地利用现状", "土地利用图斑", "现状地类图斑", "land use dltb", "dltb 2021", "土地利用现状数据"]'::json,
   '[]'::json,
   'audit')
ON CONFLICT (table_name) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  description = EXCLUDED.description,
  geometry_type = EXCLUDED.geometry_type,
  srid = EXCLUDED.srid,
  synonyms = EXCLUDED.synonyms,
  updated_at = NOW();

INSERT INTO agent_semantic_sources
  (table_name, display_name, description, geometry_type, srid, synonyms,
   suggested_analyses, owner_username)
VALUES
  ('cq_osm_roads_2021',
   '重庆OSM道路(2021)',
   '重庆市基于 OpenStreetMap 2021 年度快照的道路网络数据。',
   'GEOMETRY',
   4326,
   '["重庆OSM道路", "2021道路", "道路网 2021", "OSM 道路", "路网"]'::json,
   '[]'::json,
   'audit')
ON CONFLICT (table_name) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  description = EXCLUDED.description,
  geometry_type = EXCLUDED.geometry_type,
  srid = EXCLUDED.srid,
  synonyms = EXCLUDED.synonyms,
  updated_at = NOW();

-- -----------------------------------------------------------------------------
-- Part 2: agent_semantic_registry — column-level annotations
-- -----------------------------------------------------------------------------
-- cq_land_use_dltb columns (all UPPERCASE except geometry + SHAPE_Length/Area):
--   BSM (pk double), YSDM, DLBM, DLMC, QSDWDM, QSDWMC, ZLDWDM, ZLDWMC,
--   TBMJ, SHAPE_Length, SHAPE_Area, geometry
-- Cloned from cq_dltb registry, UPPERCASE column names, + 2 new shape stat cols.
-- -----------------------------------------------------------------------------
INSERT INTO agent_semantic_registry
  (table_name, column_name, semantic_domain, aliases, unit, description,
   is_geometry, owner_username)
VALUES
  ('cq_land_use_dltb', 'BSM',    'ID',       '["标识码", "bsm"]'::json,        '', '标识码，用于唯一标识图斑。', false, 'audit'),
  ('cq_land_use_dltb', 'YSDM',   'CODE',     '["要素代码", "ysdm"]'::json,      '', '要素代码，用于标识要素类型。', false, 'audit'),
  ('cq_land_use_dltb', 'DLBM',   'CODE',     '["地类编码", "dlbm"]'::json,      '', '地类编码，表示土地利用类型编码。', false, 'audit'),
  ('cq_land_use_dltb', 'DLMC',   'NAME',     '["地类名称", "dlmc"]'::json,      '', '地类名称，表示土地利用类型名称。', false, 'audit'),
  ('cq_land_use_dltb', 'QSDWDM', 'CODE',     '["权属单位代码", "qsdwdm"]'::json, '', '权属单位代码，表示土地所有权单位的代码。', false, 'audit'),
  ('cq_land_use_dltb', 'QSDWMC', 'NAME',     '["权属单位名称", "qsdwmc"]'::json, '', '权属单位名称，表示土地所有权单位的名称。', false, 'audit'),
  ('cq_land_use_dltb', 'ZLDWDM', 'CODE',     '["坐落单位代码", "zldwdm"]'::json, '', '坐落单位代码，表示土地坐落单位的代码。', false, 'audit'),
  ('cq_land_use_dltb', 'ZLDWMC', 'NAME',     '["坐落单位名称", "zldwmc"]'::json, '', '坐落单位名称，表示土地坐落单位的名称。', false, 'audit'),
  ('cq_land_use_dltb', 'TBMJ',   'AREA',     '["图斑面积", "tbmj"]'::json,      '平方米', '图斑面积，表示地块的面积。', false, 'audit'),
  ('cq_land_use_dltb', 'SHAPE_Length', 'LENGTH',   '["几何周长", "shape_length"]'::json, '米', '几何周长（ArcGIS 自动字段），单位取决于数据源投影。', false, 'audit'),
  ('cq_land_use_dltb', 'SHAPE_Area',   'AREA',     '["几何面积", "shape_area"]'::json,   '平方米', '几何面积（ArcGIS 自动字段），单位取决于数据源投影。', false, 'audit'),
  ('cq_land_use_dltb', 'geometry',     'GEOMETRY', '["几何信息", "几何", "geom"]'::json,  '', '几何信息，表示地块的几何形状。', true,  'audit')
ON CONFLICT (table_name, column_name) DO UPDATE SET
  semantic_domain = EXCLUDED.semantic_domain,
  aliases = EXCLUDED.aliases,
  unit = EXCLUDED.unit,
  description = EXCLUDED.description,
  is_geometry = EXCLUDED.is_geometry,
  updated_at = NOW();

-- -----------------------------------------------------------------------------
-- cq_osm_roads_2021 columns (lowercase, no objectid, geometry not shape):
--   osm_id, code, fclass, name, ref, oneway, maxspeed, layer, bridge, tunnel, geometry
-- -----------------------------------------------------------------------------
INSERT INTO agent_semantic_registry
  (table_name, column_name, semantic_domain, aliases, unit, description,
   is_geometry, owner_username)
VALUES
  ('cq_osm_roads_2021', 'osm_id',   'ID',       '["osm id", "OSM ID", "OpenStreetMap ID"]'::json, '', 'OpenStreetMap 中道路的唯一标识符。', false, 'audit'),
  ('cq_osm_roads_2021', 'code',     'CODE',     '["道路代码", "功能代码"]'::json,     '', '道路的功能分类代码。',            false, 'audit'),
  ('cq_osm_roads_2021', 'fclass',   'CATEGORY', '["功能分类", "道路等级"]'::json,     '', '道路的功能分类（primary/secondary/residential/motorway/footway 等）。', false, 'audit'),
  ('cq_osm_roads_2021', 'name',     'NAME',     '["道路名称", "路名"]'::json,         '', '道路的名称。',                  false, 'audit'),
  ('cq_osm_roads_2021', 'ref',      'ID',       '["道路编号", "参考编号"]'::json,     '', '道路的参考编号。',              false, 'audit'),
  ('cq_osm_roads_2021', 'oneway',   'FLAG',     '["单行道", "是否单行"]'::json,       '', '指示道路是否为单行道（T/F）。',  false, 'audit'),
  ('cq_osm_roads_2021', 'maxspeed', 'VELOCITY', '["最高限速", "限速"]'::json,         'km/h', '道路的最高限速。',         false, 'audit'),
  ('cq_osm_roads_2021', 'layer',    'INDEX',    '["图层", "高程层"]'::json,            '', '道路的图层信息（立体交叉层级）。', false, 'audit'),
  ('cq_osm_roads_2021', 'bridge',   'FLAG',     '["桥梁", "是否桥梁"]'::json,          '', '指示道路是否为桥梁（T/F）。',   false, 'audit'),
  ('cq_osm_roads_2021', 'tunnel',   'FLAG',     '["隧道", "是否隧道"]'::json,          '', '指示道路是否为隧道（T/F）。',   false, 'audit'),
  ('cq_osm_roads_2021', 'geometry', 'GEOMETRY', '["几何形状", "几何", "geom"]'::json,   '', '道路的几何形状。',              true,  'audit')
ON CONFLICT (table_name, column_name) DO UPDATE SET
  semantic_domain = EXCLUDED.semantic_domain,
  aliases = EXCLUDED.aliases,
  unit = EXCLUDED.unit,
  description = EXCLUDED.description,
  is_geometry = EXCLUDED.is_geometry,
  updated_at = NOW();

COMMIT;

-- =============================================================================
-- POST-APPLY VERIFICATION (run manually after COMMIT)
-- =============================================================================
-- SELECT table_name, COUNT(*) FROM agent_semantic_registry
--   WHERE table_name IN ('cq_land_use_dltb','cq_osm_roads_2021')
--   GROUP BY table_name;
-- Expected: cq_land_use_dltb=12, cq_osm_roads_2021=11
--
-- SELECT table_name FROM agent_semantic_sources
--   WHERE table_name IN ('cq_land_use_dltb','cq_osm_roads_2021');
-- Expected: 2 rows
-- =============================================================================

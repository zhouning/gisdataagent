"""Register Chongqing GIS benchmark tables to the semantic layer.

Provides rich annotations that enable the semantic layer to:
1. Map Chinese column names (DLMC, BSM, TBMJ) to their meanings
2. Provide SQL generation hints (quoting rules, spatial function guidance)
3. Inject domain knowledge (land use hierarchy, POI categories)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from data_agent.db_engine import get_engine

OWNER = "cq_benchmark"

TABLES = {
    "cq_land_use_dltb": {
        "display_name": "重庆市国土调查地类图斑 (DLTB)",
        "description": "第三次全国国土调查地类图斑数据，含土地利用分类编码(DLBM/DLMC)、权属单位、图斑面积。注意：TBMJ是投影面积(m²)，如需真实椭球面积应使用ST_Area(geometry::geography)。",
        "synonyms": ["地类图斑", "DLTB", "土地利用", "国土调查", "三调", "land use", "图斑", "权属", "权属单位", "QSDWMC"],
        "suggested_analyses": ["land_use_statistics", "area_calculation", "spatial_join"],
    },
    "cq_amap_poi_2024": {
        "display_name": "重庆市高德POI兴趣点 (2024)",
        "description": "高德地图POI数据，含名称、地址、类别、WGS84坐标。119万+条记录，查询时务必加WHERE或LIMIT。",
        "synonyms": ["POI", "兴趣点", "高德", "amap", "地点", "设施"],
        "suggested_analyses": ["poi_search", "spatial_join", "buffer_analysis"],
    },
    "cq_buildings_2021": {
        "display_name": "重庆市建筑物轮廓 (2021)",
        "description": "建筑物面数据，含楼层数(Floor)和几何轮廓。10.7万栋。",
        "synonyms": ["建筑", "建筑物", "楼房", "buildings", "房屋"],
        "suggested_analyses": ["height_analysis", "spatial_join", "buffer_analysis"],
    },
    "cq_osm_roads_2021": {
        "display_name": "重庆市OSM道路网 (2021)",
        "description": "OpenStreetMap道路数据，含道路等级(fclass)、名称、单行道标记、桥梁/隧道标记。5万+条。",
        "synonyms": ["道路", "路网", "公路", "roads", "OSM", "街道"],
        "suggested_analyses": ["road_statistics", "spatial_join", "network_analysis"],
    },
}

# Detailed column annotations with SQL generation hints
COLUMNS = {
    "cq_land_use_dltb": {
        "BSM":          {"domain": "ID",        "aliases": ["图斑标识码", "标识码", "BSM", "编号"], "unit": "", "desc": "图斑唯一标识码。PostgreSQL中必须双引号引用: \"BSM\""},
        "YSDM":         {"domain": "LAND_USE",  "aliases": ["要素代码", "YSDM"], "unit": "", "desc": "要素代码"},
        "DLBM":         {"domain": "LAND_USE",  "aliases": ["地类编码", "DLBM", "用地编码", "land use code"], "unit": "", "desc": "地类编码(如01=耕地,03=林地)。引用: \"DLBM\"。筛选用LIKE '01%'匹配一级类"},
        "DLMC":         {"domain": "LAND_USE",  "aliases": ["地类名称", "DLMC", "用地名称", "land use name"], "unit": "", "desc": "地类中文名称(如水田、旱地、有林地)。引用: \"DLMC\""},
        "QSDWDM":       {"domain": "ADMIN_CODE","aliases": ["权属单位代码", "QSDWDM"], "unit": "", "desc": "权属单位行政区划代码。引用: \"QSDWDM\""},
        "QSDWMC":       {"domain": "OWNERSHIP", "aliases": ["权属单位名称", "QSDWMC", "权属单位", "所属单位"], "unit": "", "desc": "权属单位名称(如XX街道XX社区)。引用: \"QSDWMC\"。模糊匹配用LIKE '%关键词%'"},
        "ZLDWDM":       {"domain": "ADMIN_CODE","aliases": ["坐落单位代码", "ZLDWDM"], "unit": "", "desc": "坐落单位代码"},
        "ZLDWMC":       {"domain": "NAME",      "aliases": ["坐落单位名称", "ZLDWMC", "坐落单位"], "unit": "", "desc": "坐落单位名称"},
        "TBMJ":         {"domain": "AREA",      "aliases": ["图斑面积", "TBMJ", "面积"], "unit": "m²", "desc": "图斑投影面积(m²)。注意：这是投影面积，如需真实椭球面积请用ST_Area(geometry::geography)。引用: \"TBMJ\""},
        "SHAPE_Length":  {"domain": "PERIMETER", "aliases": ["周长", "SHAPE_Length"], "unit": "投影单位", "desc": "图斑周长(投影坐标系单位，非米)。真实长度用ST_Perimeter(geometry::geography)"},
        "SHAPE_Area":    {"domain": "AREA",      "aliases": ["形状面积", "SHAPE_Area"], "unit": "投影单位", "desc": "形状面积(投影坐标系单位，非m²)。真实面积用ST_Area(geometry::geography)。引用: \"SHAPE_Area\""},
        "geometry":      {"domain": None,        "aliases": [], "unit": "", "desc": "MultiPolygon几何列，SRID=4326(WGS84)。面积计算必须::geography转换"},
    },
    "cq_amap_poi_2024": {
        "ID":           {"domain": "ID",        "aliases": ["POI编号", "ID"], "unit": "", "desc": "POI唯一ID。引用: \"ID\""},
        "名称":         {"domain": "NAME",      "aliases": ["POI名称", "名称", "name", "地点名"], "unit": "", "desc": "POI名称。引用: \"名称\"。支持LIKE模糊搜索"},
        "地址":         {"domain": "ADDRESS",   "aliases": ["地址", "address", "位置"], "unit": "", "desc": "详细地址。引用: \"地址\""},
        "电话":         {"domain": None,        "aliases": ["电话", "phone"], "unit": "", "desc": "联系电话"},
        "类别":         {"domain": "CATEGORY",  "aliases": ["POI类别", "类别", "category", "类型"], "unit": "", "desc": "POI分类(如餐饮、医疗、教育)。引用: \"类别\"。支持LIKE模糊匹配"},
        "高德ID":       {"domain": "ID",        "aliases": ["高德ID", "amap_id"], "unit": "", "desc": "高德地图内部ID"},
        "经度wgs84":    {"domain": "LONGITUDE", "aliases": ["经度", "lng", "longitude"], "unit": "度", "desc": "WGS84经度"},
        "纬度wgs84":    {"domain": "LATITUDE",  "aliases": ["纬度", "lat", "latitude"], "unit": "度", "desc": "WGS84纬度"},
        "geometry":     {"domain": None,        "aliases": [], "unit": "", "desc": "Point几何列，SRID=4326。距离计算用::geography"},
    },
    "cq_buildings_2021": {
        "Id":           {"domain": "ID",        "aliases": ["建筑ID", "Id", "编号"], "unit": "", "desc": "建筑物唯一ID。PostgreSQL引用: \"Id\"(注意大小写)"},
        "Floor":        {"domain": None,        "aliases": ["楼层", "Floor", "层数", "楼高", "层高"], "unit": "层", "desc": "建筑楼层数。引用: \"Floor\"(注意大写F)。高层>=10层，超高层>=40层"},
        "geometry":     {"domain": None,        "aliases": [], "unit": "", "desc": "MultiPolygon建筑轮廓，SRID=4326"},
    },
    "cq_osm_roads_2021": {
        "osm_id":       {"domain": "ID",        "aliases": ["OSM编号", "osm_id", "道路ID"], "unit": "", "desc": "OpenStreetMap要素ID"},
        "code":         {"domain": None,        "aliases": ["道路代码", "code"], "unit": "", "desc": "OSM道路数字代码"},
        "fclass":       {"domain": "CATEGORY",  "aliases": ["道路等级", "fclass", "道路类型", "等级", "road class"], "unit": "", "desc": "道路功能等级(primary/secondary/tertiary/residential等)"},
        "name":         {"domain": "NAME",      "aliases": ["道路名称", "name", "路名"], "unit": "", "desc": "道路名称。支持LIKE模糊搜索"},
        "oneway":       {"domain": None,        "aliases": ["单行道", "oneway"], "unit": "", "desc": "单行道标记: F=正向单行, T=反向单行, B=双向"},
        "bridge":       {"domain": None,        "aliases": ["桥梁", "bridge"], "unit": "", "desc": "桥梁标记: T=是桥梁, F=非桥梁"},
        "tunnel":       {"domain": None,        "aliases": ["隧道", "tunnel"], "unit": "", "desc": "隧道标记: T=是隧道, F=非隧道"},
        "geometry":     {"domain": None,        "aliases": [], "unit": "", "desc": "LineString道路几何，SRID=4326。长度计算用ST_Length(geometry::geography)得到米"},
    },
}


def main() -> int:
    engine = get_engine()
    if engine is None:
        print("ERROR: get_engine() returned None.", file=sys.stderr)
        return 2

    with engine.begin() as conn:
        for table, meta in TABLES.items():
            # Detect geometry
            geom = conn.execute(text(
                "SELECT type, srid FROM geometry_columns "
                "WHERE f_table_schema='public' AND f_table_name=:t LIMIT 1"
            ), {"t": table}).fetchone()

            conn.execute(text("""
                INSERT INTO agent_semantic_sources
                    (table_name, display_name, description, geometry_type, srid,
                     synonyms, suggested_analyses, owner_username)
                VALUES (:t, :dn, :desc, :gt, :srid,
                        CAST(:syn AS jsonb), CAST(:sa AS jsonb), :owner)
                ON CONFLICT (table_name) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    geometry_type = EXCLUDED.geometry_type,
                    srid = EXCLUDED.srid,
                    synonyms = EXCLUDED.synonyms,
                    suggested_analyses = EXCLUDED.suggested_analyses,
                    updated_at = NOW()
            """), {
                "t": table,
                "dn": meta["display_name"],
                "desc": meta["description"],
                "gt": geom[0] if geom else None,
                "srid": geom[1] if geom else None,
                "syn": json.dumps(meta["synonyms"]),
                "sa": json.dumps(meta["suggested_analyses"]),
                "owner": OWNER,
            })

            col_meta = COLUMNS.get(table, {})
            n = 0
            for col_name, ann in col_meta.items():
                is_geom = col_name == "geometry"
                conn.execute(text("""
                    INSERT INTO agent_semantic_registry
                        (table_name, column_name, semantic_domain, aliases,
                         unit, description, is_geometry, owner_username)
                    VALUES (:t, :col, :domain, CAST(:aliases AS jsonb),
                            :unit, :desc, :is_geom, :owner)
                    ON CONFLICT (table_name, column_name) DO UPDATE SET
                        semantic_domain = EXCLUDED.semantic_domain,
                        aliases = EXCLUDED.aliases,
                        unit = EXCLUDED.unit,
                        description = EXCLUDED.description,
                        is_geometry = EXCLUDED.is_geometry,
                        updated_at = NOW()
                """), {
                    "t": table,
                    "col": col_name,
                    "domain": ann.get("domain"),
                    "aliases": json.dumps(ann.get("aliases", [])),
                    "unit": ann.get("unit", ""),
                    "desc": ann.get("desc", ""),
                    "is_geom": is_geom,
                    "owner": OWNER,
                })
                n += 1
            print(f"  {table:25s} → {n} columns annotated")

    try:
        from data_agent.semantic_layer import invalidate_semantic_cache
        invalidate_semantic_cache()
    except Exception:
        pass

    print("\n[register-cq] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

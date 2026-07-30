"""Tests for config-driven NL2SQL semantic SQL rewrites."""
from __future__ import annotations


def test_semantic_rewrite_uses_column_aliases_for_arbitrary_table():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "city_places",
            "columns": [
                {
                    "column_name": "place_name",
                    "quoted_ref": "place_name",
                    "aliases": ["name", "title"],
                    "needs_quoting": False,
                },
                {
                    "column_name": "geom",
                    "quoted_ref": "geom",
                    "aliases": ["geometry", "shape"],
                    "is_geometry": True,
                    "pg_type": "geometry(Point,4326)",
                    "needs_quoting": False,
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "list place names",
        "SELECT p.name FROM city_places AS p WHERE ST_Intersects(p.geometry, z.geom)",
        context,
    )

    assert "p.place_name" in rewritten
    assert "p.geom" in rewritten
    assert "p.name" not in rewritten
    assert "p.geometry" not in rewritten
    assert "semantic_column_alias" in corrections


def test_semantic_rewrite_does_not_use_unreferenced_table_for_unqualified_column_alias():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "official_land_use",
                "columns": [
                    {"column_name": "DLMC", "quoted_ref": '"DLMC"', "needs_quoting": True},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4326)",
                    },
                ],
            },
            {
                "table_name": "legacy_land_use",
                "columns": [
                    {"column_name": "dlmc", "quoted_ref": "dlmc", "aliases": ["DLMC"]},
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "aliases": ["geometry"],
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4610)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "sum real spatial area where DLMC is paddy field",
        "SELECT SUM(ST_Area(geometry::geography)) / 10000 FROM official_land_use WHERE \"DLMC\" = 'paddy'",
        context,
    )

    assert "legacy_land_use.shape" not in rewritten
    assert "ST_Area(official_land_use.geometry::geography)" in rewritten
    assert "semantic_area_geometry_qualified" in corrections


def test_semantic_rewrite_prefers_table_with_exact_physical_columns():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "official_land_use",
                "columns": [
                    {"column_name": "DLMC", "quoted_ref": '"DLMC"', "needs_quoting": True},
                    {"column_name": "BSM", "quoted_ref": '"BSM"', "needs_quoting": True},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4326)",
                    },
                ],
            },
            {
                "table_name": "legacy_land_use",
                "columns": [
                    {"column_name": "dlmc", "quoted_ref": "dlmc"},
                    {"column_name": "bsm", "quoted_ref": "bsm"},
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4610)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return centroid WKT for parcels where DLMC is forest, plus BSM",
        "SELECT bsm, ST_AsText(ST_Centroid(shape)) FROM legacy_land_use WHERE dlmc = 'forest'",
        context,
    )

    assert "FROM official_land_use" in rewritten
    assert '"BSM"' in rewritten
    assert '"DLMC"' in rewritten
    assert "ST_Centroid(geometry)" in rewritten
    assert "semantic_exact_column_table" in corrections
    assert "semantic_column_alias" in corrections


def test_semantic_rewrite_prefers_table_with_single_explicit_objectid_column():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "land_use_generic",
                "columns": [
                    {"column_name": "DLMC", "quoted_ref": '"DLMC"', "needs_quoting": True},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
            {
                "table_name": "land_parcels",
                "columns": [
                    {"column_name": "objectid", "quoted_ref": "objectid"},
                    {"column_name": "dlmc", "quoted_ref": "dlmc", "aliases": ["DLMC"]},
                    {"column_name": "shape", "quoted_ref": "shape", "aliases": ["geometry"], "is_geometry": True},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "take the first parcel ordered by objectid",
        'SELECT geometry FROM land_use_generic WHERE "DLMC" = \'tea garden\' ORDER BY objectid LIMIT 1',
        context,
    )

    assert "FROM land_parcels" in rewritten
    assert "shape" in rewritten
    assert "dlmc = 'tea garden'" in rewritten
    assert "semantic_exact_column_table" in corrections


def test_semantic_rewrite_prefers_question_aliased_table_over_sql_referenced_fallback():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "cq_amap_poi_2024",
                "display_name": "重庆高德POI 2024",
                "table_aliases": ["高德POI", "POI", "兴趣点"],
                "columns": [
                    {"column_name": "名称", "quoted_ref": '"名称"', "needs_quoting": True, "aliases": ["name"]},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Point,4326)",
                    },
                ],
            },
            {
                "table_name": "cq_land_use_dltb",
                "table_aliases": ["土地利用图斑"],
                "columns": [
                    {"column_name": "QSDWMC", "quoted_ref": '"QSDWMC"', "needs_quoting": True},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4326)",
                    },
                ],
            },
            {
                "table_name": "public.cq_baidu_aoi_2024",
                "columns": [
                    {"column_name": "名称", "quoted_ref": '"名称"', "needs_quoting": True},
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4490)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "找出土地利用图斑范围内的 POI 名称列表，限制 50 条。",
        'SELECT DISTINCT b."名称" FROM public.cq_baidu_aoi_2024 b '
        'JOIN cq_land_use_dltb l ON ST_Contains(l.geometry, ST_Transform(b.shape, 4326)) '
        'WHERE l."QSDWMC" LIKE \'%璧山县璧城街道%\' LIMIT 50; AND b."名称" IS NOT NULL',
        context,
    )

    assert "cq_baidu_aoi_2024" not in rewritten
    assert "cq_amap_poi_2024 b" in rewritten
    assert "b.geometry" in rewritten
    assert "; AND" not in rewritten
    assert "semantic_question_alias_table" in corrections
    assert "semantic_column_alias" in corrections


def test_semantic_rewrite_respects_explicit_physical_table_mention():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "official_land_use",
                "columns": [
                    {"column_name": "DLMC", "quoted_ref": '"DLMC"', "needs_quoting": True},
                    {"column_name": "BSM", "quoted_ref": '"BSM"', "needs_quoting": True},
                ],
            },
            {
                "table_name": "legacy_land_use",
                "columns": [
                    {"column_name": "dlmc", "quoted_ref": "dlmc"},
                    {"column_name": "bsm", "quoted_ref": "bsm"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "query legacy_land_use using DLMC and BSM aliases",
        "SELECT bsm FROM legacy_land_use WHERE dlmc = 'forest'",
        context,
    )

    assert "FROM legacy_land_use" in rewritten
    assert "semantic_exact_column_table" not in corrections


def test_semantic_rewrite_column_aliases_match_public_schema_qualified_tables():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "roads",
            "columns": [
                {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                {
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "aliases": ["shape"],
                    "is_geometry": True,
                    "pg_type": "geometry(LineString,4326)",
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return road names near the target geometry",
        "SELECT r.name FROM public.roads AS r WHERE ST_Intersects(r.shape, r.geometry)",
        context,
    )

    assert "r.shape" not in rewritten
    assert "ST_Intersects(r.geometry, r.geometry)" in rewritten
    assert "semantic_column_alias" in corrections


def test_semantic_rewrite_moves_geography_cast_outside_st_union_area():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "land_use",
            "columns": [
                {"column_name": "DLMC", "quoted_ref": '"DLMC"', "needs_quoting": True},
                {
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(MultiPolygon,4326)",
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "area of unioned tea garden polygons in square kilometres",
        "SELECT ST_Area(ST_Union(geometry::geography)) / 1000000.0 FROM land_use WHERE \"DLMC\" = 'tea garden'",
        context,
    )

    assert "ST_Union(geometry::geography)" not in rewritten
    assert "ST_Area(ST_Union(geometry)::geography)" in rewritten
    assert "semantic_st_union_geography" in corrections


def test_semantic_rewrite_converts_geography_area_to_square_kilometres():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "parcels",
            "columns": [
                {"column_name": "land_type", "quoted_ref": "land_type", "needs_quoting": False},
                {
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(MultiPolygon,4326)",
                    "needs_quoting": False,
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "sum parcel area in square kilometres",
        "SELECT SUM(ST_Area(p.geometry::geography)) AS area_km2 "
        "FROM parcels AS p WHERE p.land_type = 'forest'",
        context,
    )

    assert "SUM((ST_Area(p.geometry::geography) / 1000000.0)) AS area_km2" in rewritten
    assert "semantic_area_square_km" in corrections


def test_semantic_rewrite_does_not_double_convert_square_kilometre_area():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "parcels",
            "columns": [
                {
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(MultiPolygon,4326)",
                    "needs_quoting": False,
                },
            ],
        }],
    }

    sql = (
        "SELECT SUM(ST_Area(p.geometry::geography)) / 1000000.0 AS area_km2 "
        "FROM parcels AS p"
    )
    rewritten, corrections = apply_semantic_sql_rewrites(
        "\u7edf\u8ba1\u9762\u79ef\uff0c\u5355\u4f4d\u4e3a\u5e73\u65b9\u516c\u91cc",
        sql,
        context,
    )

    assert rewritten == sql
    assert "semantic_area_square_km" not in corrections


def test_semantic_rewrite_keeps_geography_area_in_square_metres():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "parcels",
            "columns": [
                {
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(MultiPolygon,4326)",
                    "needs_quoting": False,
                },
            ],
        }],
    }

    sql = "SELECT SUM(ST_Area(p.geometry::geography)) AS area_m2 FROM parcels AS p"
    rewritten, corrections = apply_semantic_sql_rewrites(
        "sum parcel area in square meters",
        sql,
        context,
    )

    assert rewritten == sql
    assert "semantic_area_square_km" not in corrections


def test_semantic_rewrite_converts_geography_area_to_hectares():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "parcels",
            "columns": [
                {
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(MultiPolygon,4326)",
                    "needs_quoting": False,
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "\u7edf\u8ba1\u771f\u5b9e\u7a7a\u95f4\u9762\u79ef\uff0c\u5355\u4f4d\u4e3a\u516c\u9877",
        "SELECT ROUND(SUM(ST_Area(geometry::geography))::numeric, 2) FROM parcels",
        context,
    )

    assert "SUM((ST_Area(parcels.geometry::geography) / 10000))" in rewritten
    assert "semantic_area_hectare" in corrections


def test_semantic_rewrite_existential_sum_spatial_join_with_alias_uses_exists():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "polygons",
                "columns": [
                    {"column_name": "land_type", "quoted_ref": "land_type", "needs_quoting": False},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "bridge", "quoted_ref": "bridge", "needs_quoting": False},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "sum the area of polygons that intersect any bridge road",
        "SELECT SUM(ST_Area(p.geometry::geography)) AS total_area "
        "FROM polygons AS p JOIN roads AS r ON ST_Intersects(p.geometry, r.geometry) "
        "WHERE p.land_type = 'paddy' AND r.bridge = 'T'",
        context,
    )

    assert "JOIN roads" not in rewritten
    assert "EXISTS (SELECT 1 FROM roads AS r" in rewritten
    assert "r.bridge = 'T'" in rewritten
    assert "semantic_existential_spatial_join" in corrections


def test_semantic_rewrite_expands_value_group_from_value_semantics():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "transport_edges",
            "columns": [{
                "column_name": "road_class",
                "quoted_ref": "road_class",
                "aliases": ["fclass"],
                "needs_quoting": False,
                "value_semantics": {
                    "semantic_groups": [{
                        "aliases": ["main road"],
                        "values": ["primary", "motorway"],
                    }],
                },
            }],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count main road segments above 100 km/h",
        "SELECT COUNT(*) FROM transport_edges WHERE road_class = 'primary'",
        context,
    )

    assert "road_class IN ('primary', 'motorway')" in rewritten
    assert "semantic_value_group" in corrections


def test_semantic_rewrite_expands_value_group_from_quoted_ascii_column():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "transport_edges",
            "columns": [{
                "column_name": "road_class",
                "quoted_ref": "road_class",
                "aliases": ["fclass"],
                "needs_quoting": False,
                "value_semantics": {
                    "semantic_groups": [{
                        "aliases": ["main road"],
                        "values": ["primary", "motorway"],
                    }],
                },
            }],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "list main road segments above 100 km/h",
        'SELECT "name" FROM transport_edges WHERE "road_class" = \'primary\'',
        context,
    )

    assert '"road_class" IN (\'primary\', \'motorway\')' in rewritten
    assert "semantic_value_group" in corrections


def test_semantic_rewrite_injects_explicit_question_string_filter():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "roads",
            "columns": [
                {
                    "column_name": "oneway",
                    "quoted_ref": "oneway",
                    "needs_quoting": False,
                },
                {
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(MultiLineString,4326)",
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "calculate total length where oneway = 'F' or 'T'",
        "SELECT SUM(ST_Length(geometry::geography)) / 1000.0 FROM roads",
        context,
    )

    assert "WHERE roads.oneway IN ('F', 'T')" in rewritten
    assert "semantic_explicit_filter" in corrections


def test_semantic_rewrite_completes_requested_scalar_aggregates():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "buildings",
            "columns": [{"column_name": "Floor", "quoted_ref": '"Floor"', "needs_quoting": True}],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return the maximum, minimum, and average Floor",
        'SELECT AVG("Floor") FROM buildings',
        context,
    )

    assert rewritten == 'SELECT MAX("Floor"), MIN("Floor"), AVG("Floor") FROM buildings'
    assert "semantic_requested_aggregate" in corrections


def test_semantic_rewrite_wraps_requested_sum_projection():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "districts",
            "columns": [{"column_name": "protected_count", "quoted_ref": "protected_count"}],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return the total sum of protected_count",
        "SELECT protected_count FROM districts LIMIT 100000",
        context,
    )

    assert rewritten == "SELECT SUM(protected_count) FROM districts LIMIT 100000"
    assert "semantic_requested_aggregate" in corrections


def test_semantic_rewrite_transforms_geometry_to_target_srid():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "source_points",
                "columns": [{
                    "column_name": "geom",
                    "quoted_ref": "geom",
                    "aliases": [],
                    "is_geometry": True,
                    "pg_type": "geometry(Point,4326)",
                    "needs_quoting": False,
                }],
            },
            {
                "table_name": "target_polygons",
                "columns": [{
                    "column_name": "shape",
                    "quoted_ref": "shape",
                    "aliases": [],
                    "is_geometry": True,
                    "pg_type": "geometry(MultiPolygon,4610)",
                    "needs_quoting": False,
                }],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count points inside target polygons",
        "SELECT COUNT(*) FROM source_points AS p "
        "JOIN target_polygons AS d ON ST_Intersects(p.geom, d.shape)",
        context,
    )

    assert "ST_Contains(ST_Transform(d.shape, 4326), p.geom)" in rewritten
    assert "semantic_srid_transform" in corrections


def test_semantic_rewrite_normalizes_quoted_alias_refs_before_srid_transform():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "historic_districts",
                "columns": [
                    {"column_name": "jqmc", "quoted_ref": "jqmc", "needs_quoting": False},
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4490)",
                    },
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "ID", "quoted_ref": '"ID"', "needs_quoting": True},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Point,4326)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count POIs in each historic district",
        'SELECT "h"."jqmc", COUNT("p"."ID") FROM public.historic_districts "h" '
        'JOIN public.pois "p" ON ST_Intersects("h"."shape", "p"."geometry") '
        'GROUP BY "h"."jqmc"',
        context,
    )

    assert '"h"."shape"' not in rewritten
    assert 'ST_Intersects(ST_Transform(h."shape", 4326), p."geometry")' in rewritten
    assert "semantic_alias_ref_normalized" in corrections
    assert "semantic_srid_transform" in corrections


def test_semantic_rewrite_aligns_srid_for_contains_with_existing_wrong_transform():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "districts",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name"},
                    {"column_name": "shape", "quoted_ref": "shape", "is_geometry": True, "pg_type": "geometry(MultiPolygon,4490)"},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "id", "quoted_ref": "id"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count POIs within each district",
        "SELECT d.name, COUNT(p.id) FROM districts AS d LEFT JOIN pois AS p "
        "ON ST_Contains(d.shape, ST_Transform(p.geometry, 4610)) GROUP BY d.name",
        context,
    )

    assert "ST_Contains(ST_Transform(d.shape, 4326), p.geometry)" in rewritten
    assert "ST_Transform(p.geometry, 4610)" not in rewritten
    assert "semantic_srid_transform" in corrections


def test_semantic_rewrite_scalar_spatial_subquery_to_join():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "historic_districts",
                "columns": [
                    {"column_name": "jqmc", "quoted_ref": "jqmc", "needs_quoting": False},
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "aliases": ["geometry"],
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4490)",
                    },
                ],
            },
            {
                "table_name": "roads",
                "columns": [
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiLineString,4326)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "districts that intersect any road",
        "SELECT DISTINCT jqmc FROM historic_districts "
        "WHERE ST_Intersects(geometry, (SELECT geometry FROM roads))",
        context,
    )

    assert "SELECT geometry FROM roads" not in rewritten
    assert "JOIN roads AS r ON ST_Intersects(ST_Transform(historic_districts.shape, 4326), r.geometry)" in rewritten
    assert "semantic_scalar_spatial_subquery" in corrections
    assert "semantic_srid_transform" in corrections


def test_semantic_rewrite_scalar_spatial_subquery_uses_left_table_geometry():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "aliases": ["shape"],
                        "is_geometry": True,
                        "pg_type": "geometry(MultiLineString,4326)",
                    },
                ],
            },
            {
                "table_name": "historic_districts",
                "columns": [
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4490)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "roads that intersect any historic district",
        "SELECT DISTINCT name FROM roads "
        "WHERE ST_Intersects(shape, (SELECT shape FROM historic_districts)) "
        "AND name IS NOT NULL LIMIT 30",
        context,
    )

    assert "SELECT shape FROM historic_districts" not in rewritten
    assert "JOIN historic_districts AS d ON ST_Intersects(roads.geometry, ST_Transform(d.shape, 4326))" in rewritten
    assert "WHERE name IS NOT NULL" in rewritten
    assert "semantic_scalar_spatial_subquery" in corrections
    assert "semantic_srid_transform" in corrections


def test_semantic_rewrite_transforms_mixed_srid_distance_to_geography():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [{
                    "column_name": "geom",
                    "quoted_ref": "geom",
                    "aliases": [],
                    "is_geometry": True,
                    "pg_type": "geometry(LineString,4326)",
                    "needs_quoting": False,
                }],
            },
            {
                "table_name": "districts",
                "columns": [{
                    "column_name": "shape",
                    "quoted_ref": "shape",
                    "aliases": [],
                    "is_geometry": True,
                    "pg_type": "geometry(MultiPolygon,4490)",
                    "needs_quoting": False,
                }],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "distance in meters",
        "SELECT ST_Distance(r.geom, d.shape) FROM roads AS r "
        "JOIN districts AS d ON ST_Intersects(r.geom, d.shape)",
        context,
    )

    assert "ST_Distance(r.geom::geography, ST_Transform(d.shape, 4326)::geography)" in rewritten
    assert "semantic_distance_srid_transform" in corrections


def test_semantic_rewrite_distance_to_cte_geometry_uses_known_geography_side():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [{
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(LineString,4326)",
                    "needs_quoting": False,
                }],
            },
            {
                "table_name": "buildings",
                "columns": [{
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(Polygon,4326)",
                    "needs_quoting": False,
                }],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "nearest roads and distance in meters",
        "WITH target_building AS (SELECT geometry FROM buildings LIMIT 1) "
        "SELECT r.name, ST_Distance(r.geometry, b.geometry) AS distance "
        "FROM roads AS r, target_building AS b ORDER BY r.geometry <-> b.geometry LIMIT 10",
        context,
    )

    assert "ST_Distance(r.geometry::geography, b.geometry::geography)" in rewritten
    assert "semantic_distance_srid_transform" in corrections


def test_semantic_rewrite_redirects_literal_to_configured_value_column():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "land_parcels",
            "columns": [
                {"column_name": "land_code", "quoted_ref": "land_code", "aliases": [], "needs_quoting": False},
                {
                    "column_name": "land_name",
                    "quoted_ref": "land_name",
                    "aliases": [],
                    "needs_quoting": False,
                    "value_semantics": {
                        "literal_column_overrides": [{
                            "value": "Village",
                            "wrong_columns": ["land_code"],
                        }],
                    },
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "village parcels",
        "SELECT COUNT(*) FROM land_parcels AS d WHERE d.land_code = 'Village'",
        context,
    )

    assert "d.land_name = 'Village'" in rewritten
    assert "d.land_code = 'Village'" not in rewritten
    assert "semantic_literal_column_override" in corrections


def test_semantic_rewrite_scales_threshold_from_unit_semantics():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "district_population",
            "columns": [{
                "column_name": "registered_population_10k",
                "quoted_ref": "registered_population_10k",
                "aliases": ["registered_population"],
                "unit": "10k persons",
                "needs_quoting": False,
                "value_semantics": {
                    "stored_unit_multiplier": 10000,
                    "natural_unit_aliases": ["people", "persons"],
                },
            }],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "districts with registered population over 1000000 people",
        "SELECT district_name FROM district_population "
        "WHERE registered_population_10k > 1000000",
        context,
    )

    assert "registered_population_10k > 100" in rewritten
    assert "> 1000000" not in rewritten
    assert "semantic_unit_threshold" in corrections


def test_semantic_rewrite_uses_question_unit_when_sql_threshold_is_over_scaled():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "district_population",
            "columns": [{
                "column_name": "registered_population_10k",
                "quoted_ref": "registered_population_10k",
                "aliases": ["registered_population"],
                "unit": "\u4e07\u4eba",
                "needs_quoting": False,
                "value_semantics": {
                    "stored_unit_multiplier": 10000,
                    "natural_unit_aliases": ["\u4eba", "people", "persons"],
                },
            }],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "\u6237\u7c4d\u4eba\u53e3\u8d85\u8fc7 100 \u4e07\u4eba\u7684\u533a\u53bf",
        "SELECT district_name FROM district_population "
        "WHERE registered_population_10k > 1",
        context,
    )

    assert "registered_population_10k > 100" in rewritten
    assert "registered_population_10k > 1 " not in f"{rewritten} "
    assert "semantic_unit_threshold" in corrections


def test_semantic_rewrite_infers_stored_unit_alias_from_column_description():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "district_population",
            "columns": [{
                "column_name": "registered_population",
                "quoted_ref": "registered_population",
                "aliases": ["population"],
                "description": "\u767b\u8bb0\u4eba\u53e3\uff0c\u5355\u4f4d\u4e3a\u4e07\u4eba\u3002",
                "needs_quoting": False,
                "value_semantics": {
                    "stored_unit_multiplier": 10000,
                    "natural_unit_aliases": ["\u4eba", "people", "persons"],
                },
            }],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "\u767b\u8bb0\u4eba\u53e3\u8d85\u8fc7 100 \u4e07\u4eba\u7684\u533a\u57df",
        "SELECT district_name FROM district_population "
        "WHERE registered_population > 1",
        context,
    )

    assert "registered_population > 100" in rewritten
    assert "registered_population > 1 " not in f"{rewritten} "
    assert "semantic_unit_threshold" in corrections


def test_semantic_rewrite_scales_population_wan_threshold_without_unit_metadata():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "district_population",
            "columns": [
                {"column_name": "name", "quoted_ref": "name"},
                {"column_name": "resident_population", "quoted_ref": "resident_population"},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "\u5e38\u4f4f\u4eba\u53e3\u8d85\u8fc7 100 \u4e07\u7684\u533a\u53bf",
        "SELECT name FROM district_population WHERE resident_population > 10000",
        context,
    )

    assert "resident_population > 100" in rewritten
    assert "resident_population > 10000" not in rewritten
    assert "semantic_unit_threshold" in corrections


def test_semantic_rewrite_excludes_population_total_row_for_district_level_query():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "district_population",
            "columns": [
                {"column_name": "district_name", "quoted_ref": "district_name"},
                {"column_name": "resident_population", "quoted_ref": "resident_population", "semantic_domain": "POPULATION"},
                {
                    "column_name": "admin_division_code",
                    "quoted_ref": "admin_division_code",
                    "semantic_domain": "CODE",
                    "aliases": ["administrative division code"],
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "for districts with resident population over 100, return district name",
        "SELECT district_name FROM district_population "
        "WHERE resident_population > 100 /* explanation AND admin_division_code != 500000 */",
        context,
    )

    assert "/*" not in rewritten
    assert "admin_division_code != 500000" in rewritten
    assert "semantic_sql_comment_pruned" in corrections
    assert "semantic_population_total_exclusion" in corrections


def test_semantic_rewrite_normalizes_unique_versioned_table_reference():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "roads_2024",
            "columns": [{"column_name": "name", "quoted_ref": "name", "aliases": [], "needs_quoting": False}],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "roads with a name",
        "SELECT name FROM roads WHERE name IS NOT NULL",
        context,
    )

    assert "FROM roads_2024" in rewritten
    assert "FROM roads " not in rewritten
    assert "semantic_table_normalized" in corrections


def test_semantic_rewrite_collapses_duplicate_union_after_table_normalization():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "roads_2024",
            "columns": [
                {"column_name": "name", "quoted_ref": "name", "aliases": [], "needs_quoting": False},
                {"column_name": "kind", "quoted_ref": "kind", "aliases": [], "needs_quoting": False},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "list tunnel roads",
        "SELECT name, kind FROM roads WHERE tunnel = 'T' "
        "UNION SELECT name, kind FROM roads_2024 WHERE tunnel = 'T' LIMIT 100",
        context,
    )

    assert rewritten == "SELECT name, kind FROM roads_2024 WHERE tunnel = 'T' LIMIT 100"
    assert "UNION" not in rewritten.upper()
    assert "semantic_duplicate_union" in corrections


def test_semantic_rewrite_collapses_generic_and_versioned_duplicate_union():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "kind", "quoted_ref": "kind", "needs_quoting": False},
                ],
            },
            {
                "table_name": "roads_2024",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "kind", "quoted_ref": "kind", "needs_quoting": False},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "list tunnel roads",
        "SELECT name, kind FROM roads WHERE tunnel = 'T' "
        "UNION SELECT name, kind FROM roads_2024 WHERE tunnel = 'T' LIMIT 100",
        context,
    )

    assert rewritten == "SELECT name, kind FROM roads_2024 WHERE tunnel = 'T' LIMIT 100"
    assert "UNION" not in rewritten.upper()
    assert "semantic_duplicate_union" in corrections


def test_semantic_rewrite_prunes_invalid_trailing_clause_after_semicolon():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "places",
            "columns": [{"column_name": "name", "quoted_ref": "name"}],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return place names",
        "WITH x AS (SELECT name FROM places) SELECT name FROM x; AND places.name = 'bad' LIMIT 100000",
        context,
    )

    assert rewritten == "WITH x AS (SELECT name FROM places) SELECT name FROM x"
    assert "semantic_trailing_clause_pruned" in corrections


def test_semantic_rewrite_prunes_cte_trailing_clause_without_cross_scope_filter_injection():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "district_population",
                "columns": [
                    {"column_name": "区划名称", "quoted_ref": '"区划名称"', "needs_quoting": True},
                    {"column_name": "常住人口", "quoted_ref": '"常住人口"', "needs_quoting": True},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "名称", "quoted_ref": '"名称"', "needs_quoting": True, "semantic_domain": "NAME"},
                    {"column_name": "类型", "quoted_ref": '"类型"', "needs_quoting": True, "semantic_domain": "CATEGORY"},
                ],
            },
        ],
    }

    sql = (
        "WITH pop AS (SELECT \"常住人口\" FROM district_population WHERE \"区划名称\" = '渝中区'), "
        "bank AS (SELECT COUNT(*) AS count FROM pois WHERE \"类型\" LIKE '%银行%') "
        "SELECT p.\"常住人口\", b.count FROM pop p CROSS JOIN bank b; "
        "AND pois.\"名称\" = '渝中区' LIMIT 100000"
    )
    rewritten, corrections = apply_semantic_sql_rewrites(
        "use CTE to get 区划名称='渝中区' population and count bank POIs",
        sql,
        context,
    )

    assert rewritten.endswith("CROSS JOIN bank b")
    assert "pois.\"名称\" = '渝中区'" not in rewritten
    assert "semantic_trailing_clause_pruned" in corrections


def test_semantic_rewrite_adds_limit_from_question_when_sql_omits_it():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "places",
            "columns": [{"column_name": "name", "quoted_ref": "name", "aliases": [], "needs_quoting": False}],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "\u8fd4\u56de\u524d50\u6761\u8bb0\u5f55",
        "SELECT name FROM places WHERE name IS NOT NULL",
        context,
    )

    assert rewritten.endswith("LIMIT 50")
    assert "semantic_question_limit" in corrections


def test_semantic_rewrite_removes_degree_to_meter_multiplier_for_geographic_distance():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [{
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(LineString,4326)",
                    "needs_quoting": False,
                }],
            },
            {
                "table_name": "stations",
                "columns": [{
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(Point,4326)",
                    "needs_quoting": False,
                }],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return nearest roads and straight-line distance in meters",
        "SELECT ST_DISTANCE(r.geometry, s.geometry) * 111319.9 AS dist_m "
        "FROM roads AS r CROSS JOIN stations AS s",
        context,
    )

    assert "ST_Distance(r.geometry::geography, s.geometry::geography)" in rewritten
    assert "111319.9" not in rewritten
    assert "semantic_distance_srid_transform" in corrections


def test_semantic_rewrite_literal_override_replaces_wrong_column_like_predicate():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "land_parcels",
            "columns": [
                {"column_name": "land_code", "quoted_ref": "land_code", "needs_quoting": False},
                {
                    "column_name": "land_name",
                    "quoted_ref": "land_name",
                    "needs_quoting": False,
                    "value_semantics": {
                        "literal_column_overrides": [{
                            "value": "Village",
                            "wrong_columns": ["land_code"],
                        }],
                    },
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "hospital points inside Village land parcels",
        "SELECT p.name FROM pois AS p JOIN land_parcels AS d "
        "ON ST_Within(p.geometry, d.geometry) WHERE d.land_code LIKE '07%'",
        context,
    )

    assert "d.land_name = 'Village'" in rewritten
    assert "d.land_code LIKE" not in rewritten
    assert "semantic_literal_column_override" in corrections


def test_semantic_rewrite_adds_enum_filter_when_question_names_enum_meanings():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "commuting",
            "columns": [
                {
                    "column_name": "sex",
                    "quoted_ref": "sex",
                    "needs_quoting": False,
                    "value_semantics": {
                        "enum": [
                            {"value": 1, "meaning": "male"},
                            {"value": 2, "meaning": "female"},
                            {"value": 9, "meaning": "unknown"},
                        ],
                    },
                },
                {"column_name": "sample_population", "quoted_ref": "sample_population", "needs_quoting": False},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "sum total population for male and female commuters separately",
        "SELECT sex, SUM(sample_population) FROM commuting "
        "WHERE cross_district = 0 GROUP BY sex",
        context,
    )

    assert "sex IN (1, 2)" in rewritten
    assert "GROUP BY sex" in rewritten
    assert "semantic_enum_filter" in corrections


def test_semantic_rewrite_preserves_explicit_enum_codes_in_grouped_output():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "commuting",
            "columns": [
                {
                    "column_name": "sex",
                    "quoted_ref": "sex",
                    "needs_quoting": False,
                    "value_semantics": {
                        "enum": [
                            {"value": 1, "meaning": "male"},
                            {"value": 2, "meaning": "female"},
                        ],
                    },
                },
                {"column_name": "sample_population", "quoted_ref": "sample_population", "needs_quoting": False},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "sum sample population for sex = 1 and sex = 2, output sex codes",
        "SELECT CASE WHEN sex = 1 THEN 'male' ELSE 'female' END AS sex, "
        "SUM(sample_population) AS total_pop FROM commuting "
        "WHERE cross_district = 0 AND sex IN (1, 2) GROUP BY sex",
        context,
    )

    assert "CASE WHEN" not in rewritten
    assert "SELECT sex AS sex, SUM(sample_population) AS total_pop" in rewritten
    assert "semantic_enum_display" in corrections


def test_semantic_rewrite_removes_unrequested_positive_filter_before_aggregate():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "roads",
            "columns": [
                {"column_name": "fclass", "quoted_ref": "fclass", "needs_quoting": False},
                {"column_name": "maxspeed", "quoted_ref": "maxspeed", "needs_quoting": False},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "group by road class and return average maxspeed and maximum maxspeed, keep average above 20",
        "SELECT fclass, AVG(maxspeed) AS avg_speed, MAX(maxspeed) AS max_speed "
        "FROM roads WHERE maxspeed > 0 GROUP BY fclass "
        "HAVING AVG(maxspeed) > 20 ORDER BY avg_speed DESC",
        context,
    )

    assert "WHERE maxspeed > 0" not in rewritten
    assert "FROM roads GROUP BY fclass HAVING AVG(maxspeed) > 20" in rewritten
    assert "semantic_unrequested_positive_filter" in corrections


def test_semantic_rewrite_existential_spatial_join_aggregate_uses_exists():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "parcels",
                "columns": [
                    {"column_name": "land_name", "quoted_ref": "land_name", "needs_quoting": False},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4326)",
                        "needs_quoting": False,
                    },
                ],
            },
            {
                "table_name": "roads",
                "columns": [{
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(LineString,4326)",
                    "needs_quoting": False,
                }],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "sum real area for parcels that intersect any road",
        "SELECT SUM(ST_AREA(CAST(p.geometry AS GEOGRAPHY))) "
        "FROM parcels AS p JOIN roads AS r "
        "ON ST_INTERSECTS(p.geometry, r.geometry) "
        "WHERE p.land_name = 'paddy' LIMIT 100000",
        context,
    )

    assert "JOIN roads" not in rewritten
    assert "EXISTS (SELECT 1 FROM roads AS r WHERE ST_INTERSECTS(p.geometry, r.geometry))" in rewritten
    assert "p.land_name = 'paddy'" in rewritten
    assert "semantic_existential_spatial_join" in corrections


def test_semantic_rewrite_adds_not_null_for_distinct_name_listing():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "roads",
            "columns": [
                {"column_name": "name", "quoted_ref": "name", "aliases": ["名称"], "needs_quoting": False},
                {"column_name": "fclass", "quoted_ref": "fclass", "needs_quoting": False},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return distinct road names",
        "SELECT DISTINCT r.name FROM roads AS r WHERE r.fclass = 'residential' LIMIT 30",
        context,
    )

    assert "r.name IS NOT NULL" in rewritten
    assert "r.fclass = 'residential'" in rewritten
    assert "semantic_distinct_not_null" in corrections


def test_semantic_rewrite_adds_not_null_for_unqualified_distinct_name_listing():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "fclass", "quoted_ref": "fclass", "needs_quoting": False},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
            {
                "table_name": "districts",
                "columns": [
                    {"column_name": "shape", "quoted_ref": "shape", "is_geometry": True},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return distinct road names",
        "SELECT DISTINCT name FROM roads "
        "WHERE ST_Intersects(geometry, (SELECT shape FROM districts)) "
        "AND fclass = 'residential' LIMIT 30",
        context,
    )

    assert "name IS NOT NULL" in rewritten
    assert "semantic_distinct_not_null" in corrections


def test_semantic_rewrite_count_by_left_group_uses_left_join():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "districts",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "population", "quoted_ref": "population", "needs_quoting": False},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "id", "quoted_ref": "id", "needs_quoting": False},
                    {"column_name": "address", "quoted_ref": "address", "needs_quoting": False},
                    {"column_name": "type", "quoted_ref": "type", "needs_quoting": False},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "for districts with population over one million, count hospital POIs by district",
        "SELECT d.name, COUNT(p.id) AS poi_count FROM districts AS d "
        "JOIN pois AS p ON p.address LIKE '%' || d.name || '%' "
        "WHERE d.population > 100 AND p.type LIKE '%hospital%' "
        "GROUP BY d.name ORDER BY poi_count DESC",
        context,
    )

    assert "LEFT JOIN pois AS p ON p.address LIKE '%' || d.name || '%' AND p.type LIKE '%hospital%'" in rewritten
    assert "WHERE d.population > 100" in rewritten
    assert "semantic_left_join_count" in corrections


def test_semantic_rewrite_join_condition_override_before_left_count():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "districts",
                "columns": [
                    {"column_name": "code", "quoted_ref": "code", "needs_quoting": False},
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "population", "quoted_ref": "population", "needs_quoting": False},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "id", "quoted_ref": "id", "needs_quoting": False},
                    {"column_name": "address", "quoted_ref": "address", "needs_quoting": False},
                    {
                        "column_name": "region_id",
                        "quoted_ref": "region_id",
                        "needs_quoting": False,
                        "value_semantics": {
                            "join_condition_overrides": [{
                                "other_table": "districts",
                                "other_column": "code",
                                "self_replacement_column": "address",
                                "other_replacement_column": "name",
                                "operator": "self_like_contains_other",
                            }],
                        },
                    },
                    {"column_name": "type", "quoted_ref": "type", "needs_quoting": False},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "for districts with population over one million, count hospital POIs by district",
        "SELECT d.name, COUNT(p.id) AS poi_count FROM districts AS d "
        "JOIN pois AS p ON p.region_id = d.code "
        "WHERE d.population > 100 AND p.type LIKE '%hospital%' "
        "GROUP BY d.name ORDER BY poi_count DESC",
        context,
    )

    assert "LEFT JOIN pois AS p ON p.address LIKE '%' || d.name || '%' AND p.type LIKE '%hospital%'" in rewritten
    assert "WHERE d.population > 100" in rewritten
    assert "semantic_join_condition_override" in corrections
    assert "semantic_left_join_count" in corrections


def test_semantic_rewrite_reorders_grouped_count_join_after_join_override():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "districts",
                "columns": [
                    {"column_name": "code", "quoted_ref": "code", "needs_quoting": False},
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "population", "quoted_ref": "population", "needs_quoting": False},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "id", "quoted_ref": "id", "needs_quoting": False},
                    {"column_name": "address", "quoted_ref": "address", "needs_quoting": False},
                    {
                        "column_name": "region_id",
                        "quoted_ref": "region_id",
                        "needs_quoting": False,
                        "value_semantics": {
                            "join_condition_overrides": [{
                                "other_table": "districts",
                                "other_column": "code",
                                "self_replacement_column": "address",
                                "other_replacement_column": "name",
                                "operator": "self_like_contains_other",
                            }],
                        },
                    },
                    {"column_name": "type", "quoted_ref": "type", "needs_quoting": False},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "for districts with population over one million, count hospital POIs by district",
        "SELECT d.name, COUNT(p.id) AS poi_count FROM pois AS p "
        "JOIN districts AS d ON p.region_id = d.code "
        "WHERE p.type LIKE '%hospital%' AND d.population > 100 "
        "GROUP BY d.name ORDER BY poi_count DESC",
        context,
    )

    assert "FROM districts AS d LEFT JOIN pois AS p" in rewritten
    assert "ON p.address LIKE '%' || d.name || '%' AND p.type LIKE '%hospital%'" in rewritten
    assert "WHERE d.population > 100" in rewritten
    assert "semantic_join_condition_override" in corrections
    assert "semantic_grouped_count_join_order" in corrections


def test_semantic_rewrite_grouped_spatial_count_uses_right_entity_identifier():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "districts",
                "columns": [
                    {
                        "column_name": "object_id",
                        "quoted_ref": "object_id",
                        "needs_quoting": False,
                        "value_semantics": {"identifier": True},
                    },
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4610)",
                        "needs_quoting": False,
                    },
                ],
            },
            {
                "table_name": "buildings",
                "columns": [
                    {
                        "column_name": "id",
                        "quoted_ref": "id",
                        "needs_quoting": False,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Polygon,4326)",
                        "needs_quoting": False,
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count buildings contained within each district",
        "SELECT d.name, COUNT(DISTINCT d.object_id) AS building_count "
        "FROM districts AS d JOIN buildings AS b "
        "ON ST_INTERSECTS(ST_Transform(d.shape, 4326), b.geometry) "
        "GROUP BY d.name ORDER BY building_count DESC",
        context,
    )

    assert "COUNT(DISTINCT b.id) AS building_count" in rewritten
    assert "LEFT JOIN buildings AS b" in rewritten
    assert "ST_Contains(ST_Transform(d.shape, 4326), b.geometry)" in rewritten
    assert "semantic_grouped_spatial_count" in corrections


def test_semantic_rewrite_grouped_spatial_count_distincts_right_identifier():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "districts",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4490)",
                    },
                ],
            },
            {
                "table_name": "buildings",
                "columns": [
                    {
                        "column_name": "Id",
                        "quoted_ref": '"Id"',
                        "needs_quoting": True,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Polygon,4326)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count buildings within each district",
        "SELECT d.name, COUNT(b.\"Id\") AS building_count "
        "FROM districts AS d JOIN buildings AS b "
        "ON ST_Intersects(d.shape, b.geometry) "
        "GROUP BY d.name ORDER BY building_count DESC",
        context,
    )

    assert "COUNT(DISTINCT b.\"Id\") AS building_count" in rewritten
    assert "semantic_grouped_spatial_count" in corrections


def test_semantic_rewrite_respects_requested_intersects_for_grouped_counts():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "kind", "quoted_ref": "kind", "needs_quoting": False},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Point,4326)",
                        "needs_quoting": False,
                    },
                ],
            },
            {
                "table_name": "buildings",
                "columns": [
                    {
                        "column_name": "id",
                        "quoted_ref": "id",
                        "needs_quoting": False,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Polygon,4326)",
                        "needs_quoting": False,
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count buildings that intersect each school POI",
        "SELECT p.name, COUNT(b.id) AS building_count "
        "FROM pois AS p LEFT JOIN buildings AS b "
        "ON ST_CONTAINS(p.geometry, b.geometry) AND b.height > 20 "
        "WHERE p.kind LIKE '%school%' "
        "GROUP BY p.name ORDER BY p.name LIMIT 10",
        context,
    )

    assert "JOIN buildings AS b ON ST_Intersects(p.geometry, b.geometry)" in rewritten
    assert "LEFT JOIN" not in rewritten
    assert "COUNT(DISTINCT b.id) AS building_count" in rewritten
    assert "semantic_requested_spatial_predicate" in corrections
    assert "semantic_distinct_join_count" in corrections


def test_semantic_rewrite_allows_attribute_contains_with_requested_intersects():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "kind", "quoted_ref": "kind", "needs_quoting": False},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Point,4326)",
                        "needs_quoting": False,
                    },
                ],
            },
            {
                "table_name": "buildings",
                "columns": [
                    {"column_name": "id", "quoted_ref": "id", "needs_quoting": False},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Polygon,4326)",
                        "needs_quoting": False,
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "\u7edf\u8ba1\u7c7b\u578b\u5305\u542b\u5b66\u6821\u7684 POI\uff0c"
        "\u4e0e\u5176\u51e0\u4f55\u76f8\u4ea4\uff08ST_Intersects\uff09\u7684\u5efa\u7b51\u6570\u91cf",
        "SELECT p.name, COUNT(b.id) AS building_count "
        "FROM pois AS p LEFT JOIN buildings AS b "
        "ON ST_CONTAINS(p.geometry, b.geometry) "
        "WHERE p.kind LIKE '%school%' "
        "GROUP BY p.name LIMIT 10",
        context,
    )

    assert "JOIN buildings AS b ON ST_Intersects(p.geometry, b.geometry)" in rewritten
    assert "LEFT JOIN" not in rewritten
    assert "semantic_requested_spatial_predicate" in corrections


def test_semantic_rewrite_requested_intersects_changes_left_join_when_predicate_already_matches():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "kind", "quoted_ref": "kind", "needs_quoting": False},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Point,4326)",
                        "needs_quoting": False,
                    },
                ],
            },
            {
                "table_name": "buildings",
                "columns": [
                    {
                        "column_name": "Id",
                        "quoted_ref": "\"Id\"",
                        "needs_quoting": True,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Polygon,4326)",
                        "needs_quoting": False,
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count buildings that intersect each school POI using ST_Intersects",
        "SELECT p.name, COUNT(b.\"Id\") AS building_count "
        "FROM pois AS p LEFT JOIN buildings AS b "
        "ON ST_INTERSECTS(p.geometry, b.geometry) "
        "WHERE p.kind LIKE '%school%' "
        "GROUP BY p.name ORDER BY p.name LIMIT 10",
        context,
    )

    assert "JOIN buildings AS b ON ST_INTERSECTS(p.geometry, b.geometry)" in rewritten
    assert "LEFT JOIN" not in rewritten
    assert "COUNT(DISTINCT b.\"Id\") AS building_count" in rewritten
    assert "semantic_requested_spatial_predicate" in corrections
    assert "semantic_distinct_join_count" in corrections


def test_semantic_rewrite_counts_distinct_entity_for_exists_spatial_count():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "cq_buildings_2021",
                "table_aliases": ["建筑物", "建筑物轮廓"],
                "columns": [
                    {
                        "column_name": "Id",
                        "quoted_ref": '"Id"',
                        "needs_quoting": True,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4326)",
                    },
                ],
            },
            {
                "table_name": "cq_osm_roads_2021",
                "table_aliases": ["道路", "桥梁"],
                "columns": [
                    {"column_name": "bridge", "quoted_ref": "bridge", "needs_quoting": False},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiLineString,4326)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "统计出空间上与道路网络中任意桥梁（bridge = T）相交（Intersects）的建筑物轮廓数量。",
        "SELECT COUNT(*) FROM cq_buildings_2021 AS b "
        "WHERE EXISTS(SELECT 1 FROM cq_osm_roads_2021 AS r "
        "WHERE r.bridge = 'T' AND ST_INTERSECTS(b.geometry, r.geometry))",
        context,
    )

    assert 'COUNT(DISTINCT b."Id")' in rewritten
    assert "semantic_distinct_join_count" in corrections


def test_semantic_rewrite_counts_identifier_instead_of_distinct_geometry():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "buildings",
                "columns": [
                    {
                        "column_name": "Id",
                        "quoted_ref": '"Id"',
                        "needs_quoting": True,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4326)",
                    },
                ],
            },
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "bridge", "quoted_ref": "bridge", "needs_quoting": False},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiLineString,4326)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count buildings that intersect bridge roads",
        "SELECT COUNT(DISTINCT b.geometry) FROM buildings AS b "
        "JOIN roads AS r ON ST_INTERSECTS(b.geometry, r.geometry) "
        "WHERE r.bridge = 'T'",
        context,
    )

    assert 'COUNT(DISTINCT b."Id")' in rewritten
    assert "COUNT(DISTINCT b.geometry)" not in rewritten
    assert "semantic_distinct_join_count" in corrections


def test_semantic_rewrite_exists_spatial_count_uses_outer_from_table_not_subquery_order():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "cq_osm_roads_2021",
                "table_aliases": ["道路", "桥梁"],
                "columns": [
                    {
                        "column_name": "osm_id",
                        "quoted_ref": "osm_id",
                        "needs_quoting": False,
                        "value_semantics": {"identifier": True},
                    },
                    {"column_name": "bridge", "quoted_ref": "bridge", "needs_quoting": False},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiLineString,4326)",
                    },
                ],
            },
            {
                "table_name": "cq_buildings_2021",
                "table_aliases": ["建筑物", "建筑物轮廓"],
                "columns": [
                    {
                        "column_name": "Id",
                        "quoted_ref": '"Id"',
                        "needs_quoting": True,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4326)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "统计出空间上与道路网络中任意桥梁（bridge = T）相交（Intersects）的建筑物轮廓数量。",
        "SELECT COUNT(*) FROM cq_buildings_2021 AS b "
        "WHERE EXISTS(SELECT 1 FROM cq_osm_roads_2021 AS r "
        "WHERE r.bridge = 'T' AND ST_INTERSECTS(b.geometry, r.geometry))",
        context,
    )

    assert 'COUNT(DISTINCT b."Id")' in rewritten
    assert "COUNT(DISTINCT r.osm_id)" not in rewritten
    assert "semantic_distinct_join_count" in corrections


def test_semantic_rewrite_counts_distinct_entity_for_quoted_exists_outer_table():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "buildings",
                "columns": [
                    {
                        "column_name": "Id",
                        "quoted_ref": '"Id"',
                        "needs_quoting": True,
                        "value_semantics": {"identifier": True},
                    },
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "bridge", "quoted_ref": "bridge", "needs_quoting": False},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count buildings that intersect any bridge road",
        'SELECT COUNT(*) FROM "buildings" '
        'WHERE EXISTS(SELECT 1 FROM "roads" '
        'WHERE "roads".bridge = \'T\' AND ST_INTERSECTS("buildings".geometry, "roads".geometry))',
        context,
    )

    assert 'COUNT(DISTINCT buildings."Id")' in rewritten
    assert "semantic_distinct_join_count" in corrections


def test_semantic_rewrite_line_length_aggregate_uses_st_length_geography():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "transport_edges",
            "columns": [
                {"column_name": "road_class", "quoted_ref": "road_class", "needs_quoting": False},
                {
                    "column_name": "geometry",
                    "quoted_ref": "geometry",
                    "is_geometry": True,
                    "pg_type": "geometry(MultiLineString,4326)",
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count roads by class and report total length in kilometers",
        "SELECT road_class, COUNT(*) AS road_count, "
        "ROUND((CAST((SUM(CAST(ST_XMAX(geometry) AS DECIMAL) - CAST(ST_XMIN(geometry) AS DECIMAL)) * 0) "
        "AS DECIMAL))::numeric, 2) AS total_length_km "
        "FROM transport_edges GROUP BY road_class ORDER BY road_count DESC",
        context,
    )

    assert "ST_XMAX" not in rewritten
    assert "SUM(ST_Length(geometry::geography)) / 1000.0" in rewritten
    assert "semantic_length_metric" in corrections


def test_semantic_rewrite_centroid_text_projection_places_label_first():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "districts",
            "columns": [
                {"column_name": "name", "quoted_ref": "name", "semantic_domain": "NAME"},
                {"column_name": "shape", "quoted_ref": "shape", "is_geometry": True},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return each district name and centroid WKT",
        "SELECT ST_AsText(ST_Centroid(shape)) AS centroid_wkt, name FROM districts",
        context,
    )

    assert rewritten.startswith("SELECT name, ST_AsText(ST_Centroid(shape)) AS centroid_wkt FROM districts")
    assert "semantic_centroid_projection_order" in corrections


def test_semantic_rewrite_conditional_sum_pivot_to_grouped_rows():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "commute",
            "columns": [
                {"column_name": "gender", "quoted_ref": "gender"},
                {"column_name": "population", "quoted_ref": "population"},
                {"column_name": "cross_area", "quoted_ref": "cross_area"},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "report male and female population separately",
        "SELECT SUM(CASE WHEN gender = 1 THEN population ELSE 0 END) AS male_population, "
        "SUM(CASE WHEN gender = 2 THEN population ELSE 0 END) AS female_population "
        "FROM commute WHERE cross_area = 0 LIMIT 100",
        context,
    )

    assert "SELECT gender, SUM(population) AS total_value" in rewritten
    assert "gender IN (1, 2)" in rewritten
    assert "GROUP BY gender ORDER BY gender LIMIT 100" in rewritten
    assert "semantic_conditional_sum_group_rows" in corrections


def test_semantic_rewrite_grouped_spatial_count_uses_question_target_entity_alias():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "table_aliases": ["道路", "road"],
                "columns": [
                    {"column_name": "fclass", "quoted_ref": "fclass", "needs_quoting": False},
                    {
                        "column_name": "osm_id",
                        "quoted_ref": "osm_id",
                        "needs_quoting": False,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(LineString,4326)",
                    },
                ],
            },
            {
                "table_name": "buildings",
                "table_aliases": ["建筑", "building"],
                "columns": [
                    {
                        "column_name": "Id",
                        "quoted_ref": '"Id"',
                        "needs_quoting": True,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "Floor",
                        "quoted_ref": '"Floor"',
                        "needs_quoting": True,
                        "aliases": ["楼层"],
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Polygon,4326)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "按道路分类统计与道路相交且楼层超过 20 层的建筑数量",
        "SELECT r.fclass, COUNT(DISTINCT r.osm_id) AS building_count "
        "FROM roads AS r JOIN buildings AS b "
        "ON ST_INTERSECTS(r.geometry, b.geometry) "
        "WHERE b.\"Floor\" > 20 GROUP BY r.fclass ORDER BY building_count DESC",
        context,
    )

    assert "COUNT(DISTINCT b.\"Id\") AS building_count" in rewritten
    assert "COUNT(DISTINCT r.osm_id)" not in rewritten
    assert "semantic_distinct_join_count" in corrections


def _cq_spatial_context():
    return {
        "candidate_tables": [
            {
                "table_name": "cq_osm_roads_2021",
                "table_aliases": ["道路", "道路网络", "桥梁", "road"],
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "fclass", "quoted_ref": "fclass", "needs_quoting": False},
                    {"column_name": "bridge", "quoted_ref": "bridge", "needs_quoting": False},
                    {
                        "column_name": "osm_id",
                        "quoted_ref": "osm_id",
                        "needs_quoting": False,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiLineString,4326)",
                    },
                ],
            },
            {
                "table_name": "cq_amap_poi_2024",
                "table_aliases": ["POI", "高德 POI", "学校"],
                "columns": [
                    {
                        "column_name": "ID",
                        "quoted_ref": '"ID"',
                        "needs_quoting": True,
                        "value_semantics": {"identifier": True},
                    },
                    {"column_name": "名称", "quoted_ref": '"名称"', "needs_quoting": True},
                    {"column_name": "类型", "quoted_ref": '"类型"', "needs_quoting": True},
                    {"column_name": "地址", "quoted_ref": '"地址"', "needs_quoting": True},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Point,4326)",
                    },
                ],
            },
            {
                "table_name": "cq_buildings_2021",
                "table_aliases": ["建筑", "建筑物", "建筑物轮廓"],
                "columns": [
                    {
                        "column_name": "Id",
                        "quoted_ref": '"Id"',
                        "needs_quoting": True,
                        "value_semantics": {"identifier": True},
                    },
                    {
                        "column_name": "Floor",
                        "quoted_ref": '"Floor"',
                        "needs_quoting": True,
                        "aliases": ["floor", "楼层"],
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4326)",
                    },
                ],
            },
            {
                "table_name": "cq_historic_districts",
                "table_aliases": ["历史文化街区", "街区"],
                "columns": [
                    {"column_name": "jqmc", "quoted_ref": "jqmc", "needs_quoting": False},
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4547)",
                    },
                ],
            },
        ],
    }


def test_semantic_rewrite_cq_hard_10_primary_road_poi_count_uses_distinct():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    rewritten, corrections = apply_semantic_sql_rewrites(
        "对每条 fclass 为 primary 的道路，统计与其几何相交的 POI 数量，"
        "返回道路名称和 POI 数量，取 POI 最多的前 5 条道路。",
        'SELECT r.name, COUNT(p."ID") AS poi_cnt '
        "FROM cq_osm_roads_2021 r JOIN cq_amap_poi_2024 p "
        "ON ST_Intersects(r.geometry, p.geometry) "
        "WHERE r.fclass = 'primary' GROUP BY r.name ORDER BY poi_cnt DESC LIMIT 5",
        _cq_spatial_context(),
    )

    assert 'COUNT(DISTINCT p."ID") AS poi_cnt' in rewritten
    assert "ST_Intersects(r.geometry, p.geometry)" in rewritten
    assert "GROUP BY r.name ORDER BY poi_cnt DESC LIMIT 5" in rewritten
    assert "semantic_distinct_join_count" in corrections


def test_semantic_rewrite_cq_hard_14_dwithin_uses_geography_and_floor_quote():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    rewritten, corrections = apply_semantic_sql_rewrites(
        "找出距离'重庆大学'1 千米内（ST_DWithin geography）且楼层（Floor）大于 10 层的建筑数量。",
        'SELECT COUNT(*) FROM cq_buildings_2021 b '
        'CROSS JOIN (SELECT geometry FROM cq_amap_poi_2024 WHERE "名称" LIKE \'%重庆大学%\' LIMIT 1) u '
        "WHERE ST_DWithin(b.geometry, u.geometry, 1000) AND b.Floor > 10",
        _cq_spatial_context(),
    )

    assert "ST_DWithin(b.geometry::geography, u.geometry::geography, 1000)" in rewritten
    assert 'b."Floor" > 10' in rewritten
    assert rewritten.startswith("SELECT COUNT(*) FROM cq_buildings_2021 b")
    assert 'COUNT(DISTINCT b."Id")' not in rewritten
    assert "semantic_st_dwithin_geography" in corrections
    assert "semantic_column_alias" in corrections


def test_semantic_rewrite_keeps_longest_bridge_cte_on_roads_table():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "cq_amap_poi_2024",
                "table_aliases": ["高德POI", "POI", "兴趣点"],
                "schema_complete": True,
                "columns": [
                    {"column_name": "ID", "quoted_ref": '"ID"', "needs_quoting": True},
                    {"column_name": "名称", "quoted_ref": '"名称"', "needs_quoting": True},
                    {"column_name": "geometry", "is_geometry": True},
                ],
            },
            {
                "table_name": "cq_osm_roads_2021",
                "table_aliases": ["路网", "道路网 2021"],
                "schema_complete": True,
                "columns": [
                    {"column_name": "name"},
                    {"column_name": "fclass"},
                    {"column_name": "bridge"},
                    {"column_name": "geometry", "is_geometry": True},
                ],
            },
            {
                "table_name": "cq_osm_roads",
                "table_aliases": ["路网", "道路数据"],
                "schema_complete": True,
                "columns": [
                    {"column_name": "name"},
                    {"column_name": "fclass"},
                    {"column_name": "bridge"},
                    {"column_name": "geometry", "is_geometry": True},
                ],
            },
        ]
    }
    sql = (
        "WITH longest_bridge AS ("
        "SELECT geometry FROM cq_osm_roads_2021 WHERE bridge = 'T' "
        "ORDER BY ST_Length(geometry::geography) DESC LIMIT 1"
        ") "
        'SELECT COUNT(DISTINCT p."ID") FROM cq_amap_poi_2024 AS p, '
        "longest_bridge AS lb WHERE "
        "ST_DWithin(p.geometry::geography, lb.geometry::geography, 100)"
    )

    rewritten, corrections = apply_semantic_sql_rewrites(
        "统计距离道路网络中最长桥梁100米范围内的高德POI数量。",
        sql,
        context,
    )

    assert "FROM cq_osm_roads_2021" in rewritten
    assert "FROM cq_amap_poi_2024 WHERE bridge" not in rewritten
    assert rewritten != "SELECT 1"
    assert "semantic_unknown_column_refusal" not in corrections


def test_semantic_rewrite_cq_hard_25_grouped_road_length_uses_geography_km():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    rewritten, corrections = apply_semantic_sql_rewrites(
        "统计 cq_osm_roads_2021 中每种道路等级 fclass 的道路数量和总长度，单位千米，保留 2 位小数。",
        "SELECT fclass, COUNT(*) AS total_cnt, "
        "ROUND((SUM(CAST(ST_XMAX(geometry) AS DECIMAL) - CAST(ST_XMIN(geometry) AS DECIMAL)) * 0)::numeric, 2) AS total_km "
        "FROM cq_osm_roads_2021 GROUP BY fclass ORDER BY total_cnt DESC",
        _cq_spatial_context(),
    )

    assert "ST_XMAX" not in rewritten
    assert "SUM(ST_Length(geometry::geography)) / 1000.0" in rewritten
    assert "GROUP BY fclass ORDER BY total_cnt DESC" in rewritten
    assert "semantic_length_metric" in corrections


def test_semantic_rewrite_bridge_length_webmercator_uses_geography_km():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    rewritten, corrections = apply_semantic_sql_rewrites(
        "统计重庆2021年道路网络中所有桥梁道路（bridge = T）的总长度，单位为公里。",
        "SELECT SUM(ST_LENGTH(ST_TRANSFORM(geometry, 3857)) / 1000.0) "
        "FROM cq_osm_roads_2021 WHERE bridge = 'T'",
        _cq_spatial_context(),
    )

    assert "ST_TRANSFORM" not in rewritten.upper()
    assert "ST_Length(geometry::geography)" in rewritten
    assert "semantic_length_geography" in corrections


def test_semantic_rewrite_cq_medium_23_preserves_left_join_poi_row_count():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    rewritten, corrections = apply_semantic_sql_rewrites(
        "统计每个历史文化街区（jqmc）内包含的高德 POI 数量，返回街区名称和 POI 数量，按 POI 数量降序排列。",
        'SELECT h.jqmc, COUNT(p."ID") AS poi_cnt '
        "FROM cq_historic_districts h LEFT JOIN cq_amap_poi_2024 p "
        "ON ST_Contains(ST_Transform(h.shape, 4326), p.geometry) "
        "GROUP BY h.jqmc ORDER BY poi_cnt DESC",
        _cq_spatial_context(),
    )

    assert 'COUNT(p."ID") AS poi_cnt' in rewritten
    assert 'COUNT(DISTINCT p."ID")' not in rewritten
    assert "LEFT JOIN cq_amap_poi_2024 p" in rewritten
    assert "ST_Contains(ST_Transform(h.shape, 4326), p.geometry)" in rewritten
    assert "semantic_distinct_join_count" not in corrections


def test_semantic_rewrite_prunes_unrequested_unreferenced_spatial_join():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "buildings",
                "columns": [
                    {
                        "column_name": "id",
                        "quoted_ref": "id",
                        "needs_quoting": False,
                        "value_semantics": {"identifier": True},
                    },
                    {"column_name": "floor", "quoted_ref": "floor", "needs_quoting": False},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
            {
                "table_name": "districts",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "shape", "quoted_ref": "shape", "is_geometry": True},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count buildings with floor >= 40",
        "SELECT COUNT(DISTINCT b.id) FROM buildings AS b "
        "JOIN districts AS d ON ST_INTERSECTS(b.geometry, d.shape) "
        "WHERE b.floor >= 40 LIMIT 100000",
        context,
    )

    assert "JOIN districts" not in rewritten
    assert "WHERE b.floor >= 40" in rewritten
    assert "semantic_unrequested_spatial_join_pruned" in corrections


def test_semantic_rewrite_enum_comparison_removes_single_value_filter_and_raw_output():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "roads",
            "columns": [
                {"column_name": "fclass", "quoted_ref": "fclass", "needs_quoting": False},
                {
                    "column_name": "bridge",
                    "quoted_ref": "bridge",
                    "needs_quoting": False,
                    "value_semantics": {
                        "enum": [
                            {"value": "T", "meaning": "bridge"},
                            {"value": "F", "meaning": "non-bridge"},
                        ],
                    },
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "compare counts by fclass for bridge = 'T' and non-bridge, output fclass, bridge, count",
        "SELECT fclass, CASE WHEN bridge = 'T' THEN 'bridge' ELSE 'non-bridge' END AS bridge, "
        "COUNT(*) AS count FROM roads WHERE bridge IN ('F') GROUP BY fclass, bridge LIMIT 100",
        context,
    )

    assert "CASE WHEN" not in rewritten
    assert "bridge IN ('F')" not in rewritten
    assert "WHERE" not in rewritten
    assert "SELECT fclass, bridge AS bridge, COUNT(*) AS count" in rewritten
    assert "GROUP BY fclass, bridge" in rewritten
    assert "semantic_enum_comparison" in corrections


def test_semantic_rewrite_preview_uses_configured_default_sort_metric():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "search_index",
            "columns": [
                {"column_name": "origin", "quoted_ref": "origin", "needs_quoting": False},
                {"column_name": "destination", "quoted_ref": "destination", "needs_quoting": False},
                {
                    "column_name": "pc_count",
                    "quoted_ref": "pc_count",
                    "needs_quoting": False,
                    "semantic_domain": "MEASURE",
                    "value_semantics": {"default_preview_sort": "desc", "default_sort_priority": 10},
                },
                {
                    "column_name": "mobile_count",
                    "quoted_ref": "mobile_count",
                    "needs_quoting": False,
                    "semantic_domain": "MEASURE",
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "preview first 10 search-index rows with origin, destination, pc count and mobile count",
        "SELECT origin, destination, pc_count, mobile_count FROM search_index LIMIT 10",
        context,
    )

    assert rewritten.endswith("ORDER BY pc_count DESC LIMIT 10")
    assert "semantic_default_preview_sort" in corrections


def test_semantic_rewrite_preview_matches_redundantly_quoted_ascii_sort_metric():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "search_index",
            "columns": [
                {"column_name": "origin", "quoted_ref": "origin", "needs_quoting": False},
                {
                    "column_name": "pc_count",
                    "quoted_ref": "pc_count",
                    "needs_quoting": False,
                    "semantic_domain": "MEASURE",
                    "value_semantics": {"default_preview_sort": "desc", "default_sort_priority": 10},
                },
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "preview first 10 search-index rows with origin and pc count",
        'SELECT "origin", "pc_count" FROM search_index LIMIT 10',
        context,
    )

    assert rewritten.endswith('ORDER BY "pc_count" DESC LIMIT 10')
    assert "semantic_default_preview_sort" in corrections


def test_semantic_rewrite_knn_order_by_distance_alias_uses_geometry_operator():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "transport_edges",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "geom", "quoted_ref": "geom", "is_geometry": True, "pg_type": "geometry(LineString,4326)"},
                ],
            },
            {
                "table_name": "stations",
                "columns": [
                    {"column_name": "station_name", "quoted_ref": "station_name", "needs_quoting": False},
                    {"column_name": "geom", "quoted_ref": "geom", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "find the nearest 5 transport edges to Central Station and return straight-line distance",
        "SELECT e.name, ST_Distance(e.geom::geography, s.geom::geography) AS distance_meters "
        "FROM transport_edges AS e CROSS JOIN ("
        "SELECT geom FROM stations WHERE station_name = 'Central Station' LIMIT 1"
        ") AS s ORDER BY distance_meters ASC LIMIT 5",
        context,
    )

    assert "ORDER BY e.geom <-> s.geom LIMIT 5" in rewritten
    assert "ORDER BY distance_meters" not in rewritten
    assert "semantic_knn_order" in corrections


def test_semantic_rewrite_prefers_versioned_candidate_over_generic_table():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "transport_edges_2021",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "road_class", "quoted_ref": "road_class", "needs_quoting": False},
                    {"column_name": "tunnel", "quoted_ref": "tunnel", "needs_quoting": False},
                ],
            },
            {
                "table_name": "transport_edges",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "road_class", "quoted_ref": "road_class", "needs_quoting": False},
                    {"column_name": "tunnel", "quoted_ref": "tunnel", "needs_quoting": False},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "list roads with tunnels",
        "SELECT name, road_class FROM transport_edges WHERE tunnel = 'T'",
        context,
    )

    assert "FROM transport_edges_2021" in rewritten
    assert "FROM transport_edges " not in rewritten
    assert "semantic_table_normalized" in corrections


def test_semantic_rewrite_explicit_geometry_type_request_overrides_wrong_sql():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "buildings_2021",
            "columns": [
                {"column_name": "id", "quoted_ref": "id", "value_semantics": {"identifier": True}},
                {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "query the first row geometry type in buildings_2021 using ST_GeometryType",
        "SELECT name, address FROM pois WHERE type LIKE '%hospital%' LIMIT 1000",
        context,
    )

    assert rewritten == "SELECT ST_GeometryType(geometry) FROM buildings_2021 LIMIT 1"
    assert "semantic_explicit_geometry_function" in corrections


def test_semantic_rewrite_removes_unrequested_code_filter_when_literal_filter_is_present():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "land_use",
            "columns": [
                {"column_name": "DLBM", "quoted_ref": '"DLBM"', "needs_quoting": True, "semantic_domain": "CODE", "aliases": ["land use code"]},
                {"column_name": "DLMC", "quoted_ref": '"DLMC"', "needs_quoting": True, "semantic_domain": "CATEGORY", "aliases": ["land use name"]},
                {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "calculate the total area for land-use name 'paddy field'",
        "SELECT SUM(ST_Area(geometry::geography)) FROM land_use "
        "WHERE \"DLBM\" LIKE '0103%' AND \"DLMC\" = 'paddy field'",
        context,
    )

    assert '"DLBM" LIKE' not in rewritten
    assert '"DLMC" = \'paddy field\'' in rewritten
    assert "semantic_unrequested_code_filter" in corrections


def test_semantic_rewrite_splits_composite_name_or_type_like_filter():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "pois",
            "columns": [
                {"column_name": "name", "quoted_ref": "name", "semantic_domain": "NAME"},
                {"column_name": "type", "quoted_ref": "type", "semantic_domain": "CATEGORY"},
                {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "find buildings within 500m of POIs whose name or type contains 'AAA BBB', 'AAA' and 'BBB'",
        "SELECT AVG(b.floor) FROM buildings AS b JOIN pois AS p "
        "ON ST_DWithin(b.geometry::geography, p.geometry::geography, 500) "
        "WHERE p.type LIKE '%AAA BBB%'",
        context,
    )

    assert "(p.name LIKE '%AAA%' OR p.type LIKE '%AAA%') AND p.type LIKE '%BBB%'" in rewritten
    assert "semantic_composite_like_filter" in corrections


def test_semantic_rewrite_qualifies_unqualified_knn_target_projection_columns():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "table_aliases": ["road"],
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "semantic_domain": "NAME"},
                    {"column_name": "fclass", "quoted_ref": "fclass", "aliases": ["road class"]},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "名称", "quoted_ref": '"名称"', "needs_quoting": True, "semantic_domain": "NAME"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "find nearest 5 roads to station POI and return road name and fclass",
        'SELECT "名称", "fclass", ST_Distance(r.geometry::geography, p.geometry::geography) AS distance '
        "FROM roads r CROSS JOIN (SELECT geometry FROM pois WHERE \"名称\" = 'Central' LIMIT 1) p "
        "ORDER BY r.geometry <-> p.geometry LIMIT 5",
        context,
    )

    assert "SELECT r.name, r.fclass, ST_Distance" in rewritten
    assert "semantic_projection_column" in corrections


def test_semantic_rewrite_corrects_one_character_projection_typo_to_question_column():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "districts",
                "columns": [
                    {"column_name": "jqmc", "quoted_ref": "jqmc", "semantic_domain": "NAME"},
                    {"column_name": "shape", "quoted_ref": "shape", "is_geometry": True},
                ],
            },
            {
                "table_name": "buildings",
                "columns": [
                    {"column_name": "Id", "quoted_ref": '"Id"', "needs_quoting": True, "value_semantics": {"identifier": True}},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count buildings in each historic district, return jqmc and building count",
        'SELECT "hqmc", COUNT(DISTINCT b."Id") AS building_count '
        "FROM districts AS h LEFT JOIN buildings AS b ON ST_Contains(h.shape, b.geometry) "
        "GROUP BY h.jqmc ORDER BY building_count DESC",
        context,
    )

    assert "SELECT h.jqmc, COUNT" in rewritten
    assert "semantic_projection_column" in corrections


def test_semantic_rewrite_orders_count_before_sum_when_question_requests_that_order():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "parcels",
            "columns": [
                {"column_name": "owner", "quoted_ref": "owner"},
                {"column_name": "area_m2", "quoted_ref": "area_m2"},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return owner parcel count and total area",
        "SELECT owner, SUM(area_m2) AS total_area, COUNT(*) AS parcel_count "
        "FROM parcels GROUP BY owner ORDER BY parcel_count DESC LIMIT 5",
        context,
    )

    assert "SELECT owner, COUNT(*) AS parcel_count, SUM(area_m2) AS total_area FROM" in rewritten
    assert "semantic_aggregate_projection_order" in corrections


def test_semantic_rewrite_uses_destination_projection_when_origin_is_filter():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "search_index",
            "columns": [
                {"column_name": "odjsmc", "quoted_ref": "odjsmc", "aliases": ["origin city"]},
                {"column_name": "ddjsmc", "quoted_ref": "ddjsmc", "aliases": ["destination city"]},
                {"column_name": "pcsscs", "quoted_ref": "pcsscs"},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "for origin city odjsmc LIKE '%Chongqing%', return destination city and total pc searches",
        "SELECT odjsmc, SUM(pcsscs) AS total_pc FROM search_index "
        "WHERE odjsmc LIKE '%Chongqing%' GROUP BY odjsmc ORDER BY total_pc DESC LIMIT 10",
        context,
    )

    assert "SELECT ddjsmc, SUM(pcsscs)" in rewritten
    assert "WHERE odjsmc LIKE" in rewritten
    assert "GROUP BY ddjsmc" in rewritten
    assert "semantic_origin_destination_projection" in corrections


def test_semantic_rewrite_reorders_grouped_count_join_to_preserve_zero_rows():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {"table_name": "pois", "columns": [{"column_name": "id", "quoted_ref": "id"}, {"column_name": "address", "quoted_ref": "address"}, {"column_name": "type", "quoted_ref": "type"}]},
            {"table_name": "districts", "columns": [{"column_name": "name", "quoted_ref": "name"}, {"column_name": "population", "quoted_ref": "population"}]},
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "for districts with population over 100, count hospital POIs by district",
        "SELECT d.name, COUNT(p.id) AS hospital_count FROM pois AS p "
        "JOIN districts AS d ON p.address LIKE '%' || d.name || '%' "
        "WHERE p.type LIKE '%hospital%' AND d.population > 100 "
        "GROUP BY d.name ORDER BY hospital_count DESC",
        context,
    )

    assert "FROM districts AS d LEFT JOIN pois AS p" in rewritten
    assert "ON p.address LIKE '%' || d.name || '%' AND p.type LIKE '%hospital%'" in rewritten
    assert "WHERE d.population > 100" in rewritten
    assert "semantic_left_join_count" in corrections


def test_semantic_rewrite_uses_contains_for_requested_containment_predicate():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "districts",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name"},
                    {"column_name": "shape", "quoted_ref": "shape", "is_geometry": True, "pg_type": "geometry(MultiPolygon,4610)"},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "id", "quoted_ref": "id", "value_semantics": {"identifier": True}},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count POIs within each district",
        "SELECT d.name, COUNT(p.id) AS poi_count FROM districts AS d JOIN pois AS p "
        "ON ST_Intersects(ST_Transform(d.shape, 4326), p.geometry) GROUP BY d.name",
        context,
    )

    assert "ST_Contains(ST_Transform(d.shape, 4326), p.geometry)" in rewritten
    assert "semantic_requested_containment" in corrections


def test_semantic_rewrite_flips_contains_direction_by_geometry_type():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "id", "quoted_ref": "id"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
            {
                "table_name": "parcels",
                "columns": [
                    {"column_name": "shape", "quoted_ref": "shape", "is_geometry": True, "pg_type": "geometry(MultiPolygon,4610)"},
                    {"column_name": "land_name", "quoted_ref": "land_name"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count POIs within village parcels",
        "SELECT COUNT(DISTINCT p.id) FROM pois AS p JOIN parcels AS d "
        "ON ST_Contains(p.geometry, ST_Transform(d.shape, 4326)) WHERE d.land_name = 'village'",
        context,
    )

    assert "ST_Contains(ST_Transform(d.shape, 4326), p.geometry)" in rewritten
    assert "ST_Contains(p.geometry" not in rewritten
    assert "semantic_requested_containment" in corrections


def test_semantic_rewrite_adds_not_null_for_ranked_metric():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [{
            "table_name": "aoi",
            "columns": [
                {"column_name": "district", "quoted_ref": "district"},
                {"column_name": "name", "quoted_ref": "name"},
                {"column_name": "rating", "quoted_ref": "rating"},
            ],
        }],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "return the highest rated AOI in each district",
        "SELECT district, name, rating FROM ("
        "SELECT district, name, rating, ROW_NUMBER() OVER (PARTITION BY district ORDER BY rating DESC, name ASC) rn "
        "FROM aoi) ranked WHERE rn = 1",
        context,
    )

    assert "WHERE rn = 1 AND rating IS NOT NULL" in rewritten
    assert "semantic_rank_metric_not_null" in corrections


def test_semantic_rewrite_flips_contains_for_generic_area_geometry_metadata():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "ID", "quoted_ref": '"ID"', "needs_quoting": True},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(POINT,4326)",
                        "description": "point geometry for places",
                    },
                ],
            },
            {
                "table_name": "land_parcels",
                "columns": [
                    {"column_name": "land_name", "quoted_ref": "land_name"},
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "is_geometry": True,
                        "pg_type": "geometry(GEOMETRY,4610)",
                        "description": "parcel boundary geometry",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "count POIs within village parcel areas",
        'SELECT COUNT(DISTINCT p."ID") FROM pois AS p JOIN land_parcels AS d '
        "ON ST_Contains(p.geometry, ST_Transform(d.shape, 4326)) "
        "WHERE d.land_name = 'village'",
        context,
    )

    assert "ST_Contains(ST_Transform(d.shape, 4326), p.geometry)" in rewritten
    assert "semantic_requested_containment" in corrections


def test_semantic_rewrite_strips_invalid_geometry_type_modifier_casts():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(LineString,4326)"},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "find nearest roads and return distance",
        "SELECT r.name, ST_Distance(CAST(r.geometry AS GEOMETRY(4326)), "
        "CAST(p.geometry AS geometry(POINT, 4326))) AS dist_m "
        "FROM roads AS r CROSS JOIN pois AS p "
        "ORDER BY ST_Distance(CAST(r.geometry AS GEOMETRY(4326)), "
        "CAST(p.geometry AS geometry(POINT, 4326))) ASC LIMIT 5",
        context,
    )

    assert "CAST(r.geometry AS GEOMETRY(4326))" not in rewritten
    assert "CAST(p.geometry AS geometry(POINT, 4326))" not in rewritten
    assert "semantic_geometry_cast" in corrections


def test_semantic_rewrite_prunes_unmatched_closing_parentheses():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    rewritten, corrections = apply_semantic_sql_rewrites(
        "average building floor",
        'SELECT AVG("Floor") FROM buildings) LIMIT 100000',
        {"candidate_tables": []},
    )

    assert rewritten == 'SELECT AVG("Floor") FROM buildings LIMIT 100000'
    assert "semantic_unmatched_paren_pruned" in corrections


def test_semantic_rewrite_chinese_knn_order_by_distance_expression():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(LineString,4326)"},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "\u627e\u5230\u8ddd\u79bb'Central'\u6700\u8fd1\u7684 5 \u6761\u9053\u8def\uff0c\u8fd4\u56de\u76f4\u7ebf\u8ddd\u79bb",
        "SELECT r.name, ST_Distance(r.geometry::geography, p.geometry::geography) AS dist_m "
        "FROM roads AS r CROSS JOIN pois AS p WHERE p.name = 'Central' "
        "ORDER BY ST_Distance(r.geometry, p.geometry) ASC LIMIT 5",
        context,
    )

    assert "ORDER BY r.geometry <-> p.geometry LIMIT 5" in rewritten
    assert "semantic_knn_order" in corrections


def test_semantic_rewrite_distance_with_transform_uses_geography():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(LineString,4326)"},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "nearest roads with distance in meters",
        "SELECT ST_Distance(r.geometry, ST_Transform(p.geometry, 4326)) AS dist_m "
        "FROM roads AS r CROSS JOIN pois AS p ORDER BY r.geometry <-> p.geometry LIMIT 5",
        context,
    )

    assert "ST_Distance(r.geometry::geography, ST_Transform(p.geometry, 4326)::geography)" in rewritten
    assert "semantic_distance_srid_transform" in corrections


def test_semantic_rewrite_knn_radius_join_to_cross_join_and_adds_order():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(LineString,4326)"},
                ],
            },
            {
                "table_name": "buildings",
                "columns": [
                    {"column_name": "Id", "quoted_ref": '"Id"', "needs_quoting": True},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "find nearest 10 roads to buildings with Floor >= 50",
        "SELECT r.name, ST_Distance(CAST(r.geometry AS GEOGRAPHY), CAST(b.geometry AS GEOGRAPHY)) AS distance "
        "FROM roads AS r JOIN buildings AS b "
        "ON ST_DWithin(CAST(r.geometry AS GEOGRAPHY), CAST(b.geometry AS GEOGRAPHY), 50) "
        'WHERE b."Floor" >= 50 LIMIT 10',
        context,
    )

    assert "JOIN buildings AS b ON ST_DWithin" not in rewritten
    assert "CROSS JOIN buildings AS b" in rewritten
    assert "ORDER BY r.geometry <-> b.geometry LIMIT 10" in rewritten
    assert "semantic_knn_join" in corrections
    assert "semantic_knn_order" in corrections


def test_semantic_rewrite_knn_removes_unrequested_and_duplicate_string_filters():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "semantic_domain": "NAME"},
                    {"column_name": "fclass", "quoted_ref": "fclass"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(LineString,4326)"},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "semantic_domain": "NAME"},
                    {"column_name": "type", "quoted_ref": "type", "semantic_domain": "CATEGORY"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "find the nearest 5 roads to POI name = 'Central Station'",
        "SELECT r.name, r.fclass, ST_Distance(r.geometry::geography, p.geometry::geography) AS dist_m "
        "FROM roads AS r JOIN pois AS p ON ST_DWithin(r.geometry::geography, p.geometry::geography, 50) "
        "WHERE p.type LIKE '%hospital%' AND r.name ILIKE '%Central Station%' "
        "AND p.name = 'Central Station' ORDER BY dist_m ASC LIMIT 5",
        context,
    )

    assert "p.type LIKE '%hospital%'" not in rewritten
    assert "r.name ILIKE '%Central Station%'" not in rewritten
    assert "CROSS JOIN (SELECT * FROM pois WHERE name = 'Central Station' LIMIT 1) AS p" in rewritten
    assert "WHERE WHERE" not in rewritten
    assert "semantic_knn_filter" in corrections
    assert "semantic_knn_target" in corrections


def test_semantic_rewrite_knn_replaces_missing_target_relation_with_subquery():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "cq_amap_poi_2024",
                "table_aliases": ["高德POI", "POI"],
                "columns": [
                    {"column_name": "名称", "quoted_ref": '"名称"', "needs_quoting": True},
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "is_geometry": True,
                        "pg_type": "geometry(Point,4326)",
                    },
                ],
            },
            {
                "table_name": "cq_dltb",
                "table_aliases": ["地类图斑", "图斑"],
                "columns": [
                    {"column_name": "objectid", "quoted_ref": "objectid"},
                    {"column_name": "dlmc", "quoted_ref": "dlmc", "aliases": ["地类", "地类名称"]},
                    {
                        "column_name": "shape",
                        "quoted_ref": "shape",
                        "is_geometry": True,
                        "pg_type": "geometry(MultiPolygon,4610)",
                    },
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "找到距离某个地类为'茶园'的图斑（取第一个，按 objectid 排序）最近的 5 个高德 POI，返回 POI 名称和距离（米）。",
        'SELECT p."名称", ST_Distance(CAST(p.geometry AS GEOGRAPHY), CAST(t.shape AS GEOGRAPHY)) AS distance_m '
        'FROM cq_amap_poi_2024 AS p, target AS t ORDER BY p.geometry <-> t.shape LIMIT 5',
        context,
    )

    assert "target AS t" not in rewritten
    assert (
        "CROSS JOIN (SELECT shape FROM cq_dltb WHERE dlmc = '茶园' "
        "ORDER BY objectid LIMIT 1) AS t"
    ) in rewritten
    assert "ST_Distance(ST_Transform(p.geometry, 4610)::geography, t.shape::geography)" in rewritten
    assert "ORDER BY ST_Transform(p.geometry, 4610) <-> t.shape" in rewritten
    assert "semantic_missing_target_relation" in corrections
    assert "semantic_subquery_srid_transform" in corrections


def test_semantic_rewrite_knn_wraps_single_target_cross_join_filter():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "roads",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(LineString,4326)"},
                ],
            },
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "find the nearest 5 roads to POI name = 'Central Station'",
        "SELECT r.name, ST_Distance(r.geometry::geography, p.geometry::geography) AS dist_m "
        "FROM roads AS r CROSS JOIN pois AS p "
        "WHERE p.name = 'Central Station' ORDER BY r.geometry <-> p.geometry LIMIT 5",
        context,
    )

    assert "CROSS JOIN (SELECT * FROM pois WHERE name = 'Central Station' LIMIT 1) AS p" in rewritten
    assert "WHERE p.name = 'Central Station'" not in rewritten
    assert "ORDER BY r.geometry <-> p.geometry LIMIT 5" in rewritten
    assert "semantic_knn_target" in corrections


def test_semantic_rewrite_knn_wraps_first_target_with_question_order_column():
    from data_agent.nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    context = {
        "candidate_tables": [
            {
                "table_name": "pois",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name"},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True, "pg_type": "geometry(Point,4326)"},
                ],
            },
            {
                "table_name": "parcels",
                "columns": [
                    {"column_name": "objectid", "quoted_ref": "objectid"},
                    {"column_name": "land_name", "quoted_ref": "land_name"},
                    {"column_name": "shape", "quoted_ref": "shape", "is_geometry": True, "pg_type": "geometry(Polygon,4610)"},
                ],
            },
        ],
    }

    rewritten, corrections = apply_semantic_sql_rewrites(
        "find nearest 5 POIs to a parcel where land_name = 'tea garden', take the first ordered by objectid",
        "SELECT p.name, ST_Distance(p.geometry::geography, ST_Transform(d.shape, 4326)::geography) AS dist_m "
        "FROM pois AS p CROSS JOIN parcels AS d "
        "WHERE d.land_name = 'tea garden' ORDER BY p.geometry <-> ST_Transform(d.shape, 4326) LIMIT 5",
        context,
    )

    assert (
        "CROSS JOIN (SELECT * FROM parcels WHERE land_name = 'tea garden' "
        "ORDER BY objectid LIMIT 1) AS d"
    ) in rewritten
    assert "semantic_knn_target" in corrections

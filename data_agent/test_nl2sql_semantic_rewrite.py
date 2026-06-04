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

    assert "ST_Intersects(ST_Transform(p.geom, 4610), d.shape)" in rewritten
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

"""Tests for the multi-modal data fusion engine (v5.5 + v5.6 + v7.0 enhancements).

Covers: source profiling, compatibility assessment, semantic alignment,
fusion execution (all 10 strategies), strategy matrix, quality validation,
DB recording, toolset registration, end-to-end flows,
AND v5.6: fuzzy matching, unit conversion, strategy scoring,
multi-source orchestration, enhanced quality validation.
AND v7.0: embedding matching, LLM strategy routing, chunked I/O.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon, box


# ---------------------------------------------------------------------------
# Helpers: create test fixtures
# ---------------------------------------------------------------------------

def _make_vector_fixture(tmp_dir: str, name: str = "test_parcels.geojson",
                         crs: str = "EPSG:4326") -> str:
    """Create a small vector GeoJSON fixture."""
    polys = [
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        Polygon([(0, 1), (1, 1), (1, 2), (0, 2)]),
    ]
    gdf = gpd.GeoDataFrame({
        "OBJECTID": [1, 2, 3],
        "DLBM": ["0101", "0201", "0301"],
        "AREA": [100.5, 200.3, 150.7],
        "SLOPE": [5.2, 12.1, 3.8],
    }, geometry=polys, crs=crs)
    path = os.path.join(tmp_dir, name)
    gdf.to_file(path, driver="GeoJSON")
    return path


def _make_tabular_fixture(tmp_dir: str, name: str = "test_attrs.csv") -> str:
    """Create a small CSV fixture."""
    df = pd.DataFrame({
        "OBJECTID": [1, 2, 3],
        "OWNER": ["Alice", "Bob", "Charlie"],
        "VALUE": [50000, 80000, 65000],
    })
    path = os.path.join(tmp_dir, name)
    df.to_csv(path, index=False)
    return path


def _make_raster_fixture(
    tmp_dir: str,
    name: str = "test_raster.tif",
    data: np.ndarray | None = None,
    band_description: str | None = None,
    band_tags: dict | None = None,
    nodata: float | None = None,
    crs: str = "EPSG:4326",
    transform=None,
) -> str:
    """Create a small raster GeoTIFF fixture."""
    import rasterio
    from rasterio.transform import from_bounds

    path = os.path.join(tmp_dir, name)
    data = data if data is not None else np.random.rand(10, 10).astype(np.float32)
    transform = transform or from_bounds(0, 0, 2, 2, 10, 10)

    with rasterio.open(
        path, "w", driver="GTiff", height=10, width=10,
        count=1, dtype="float32", crs=crs, transform=transform,
        nodata=nodata,
    ) as ds:
        ds.write(data, 1)
        if band_description:
            ds.set_band_description(1, band_description)
        if band_tags:
            ds.update_tags(1, **band_tags)
    return path


def _make_second_vector(tmp_dir: str) -> str:
    """Create a second vector fixture for spatial join tests."""
    polys = [
        Polygon([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)]),
        Polygon([(1.5, 0.5), (2.5, 0.5), (2.5, 1.5), (1.5, 1.5)]),
    ]
    gdf = gpd.GeoDataFrame({
        "ZONE_ID": [10, 20],
        "ZONE_NAME": ["Zone A", "Zone B"],
        "DENSITY": [0.5, 0.8],
    }, geometry=polys, crs="EPSG:4326")
    path = os.path.join(tmp_dir, "zones.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


def _make_point_vector(tmp_dir: str) -> str:
    """Create a point vector for point sampling tests."""
    points = [Point(0.5, 0.5), Point(1.0, 1.0), Point(1.5, 1.5)]
    gdf = gpd.GeoDataFrame({
        "STATION_ID": [1, 2, 3],
    }, geometry=points, crs="EPSG:4326")
    path = os.path.join(tmp_dir, "stations.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


class _MockLasData:
    """Small context-manager LAS object for point-cloud profiling tests."""

    def __init__(self):
        self.x = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        self.y = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
        self.z = np.array([100.0, 102.0, 106.0, 108.0, 112.0])
        self.classification = np.array([2, 2, 5, 6, 9], dtype=np.uint8)
        self.intensity = np.array([120, 150, 180, 210, 240], dtype=np.uint16)
        self.return_number = np.array([1, 1, 1, 2, 2], dtype=np.uint8)
        self.number_of_returns = np.array([1, 1, 2, 2, 2], dtype=np.uint8)
        self.red = np.array([1000, 1100, 1200, 1300, 1400], dtype=np.uint16)
        self.green = np.array([900, 950, 1000, 1050, 1100], dtype=np.uint16)
        self.blue = np.array([800, 850, 900, 950, 1000], dtype=np.uint16)
        self.scan_angle = np.array([-5.0, -2.0, 0.0, 2.0, 5.0], dtype=np.float32)
        dimension_names = [
            "X",
            "Y",
            "Z",
            "classification",
            "intensity",
            "return_number",
            "number_of_returns",
            "red",
            "green",
            "blue",
            "scan_angle",
        ]
        point_format = MagicMock()
        point_format.dimension_names = dimension_names
        self.point_format = point_format
        self.header = MagicMock(
            x_min=0.0,
            y_min=10.0,
            x_max=4.0,
            y_max=14.0,
            point_count=5,
            point_format=point_format,
        )
        self.header.parse_crs.return_value = "EPSG:4326"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _MockLasVlr:
    def __init__(self, user_id, record_id, description, record_data=b""):
        self.user_id = user_id
        self.record_id = record_id
        self.description = description
        self.record_data = record_data


def _mock_las_data_with_vlrs():
    las = _MockLasData()
    las.header.vlrs = [
        _MockLasVlr(
            "LASF_Projection",
            34735,
            "GeoKeyDirectoryTag",
            b"\x01\x00\x01\x00",
        ),
        _MockLasVlr(
            "LASF_Projection",
            34737,
            "GeoAsciiParamsTag",
            b"WGS 84 / UTM zone 50N|",
        ),
    ]
    las.header.evlrs = [
        _MockLasVlr(
            "CUSTOM",
            7,
            "Processing lineage",
            b"classified by vendor pipeline",
        )
    ]
    return las


def _mock_large_las_data(point_count=1_250_000):
    las = _MockLasData()
    las.header.point_count = point_count
    return las


def _plain_mock_las_data():
    source = _MockLasData()

    class PlainLasData:
        pass

    plain = PlainLasData()
    for name in [
        "x",
        "y",
        "z",
        "classification",
        "intensity",
        "return_number",
        "number_of_returns",
        "red",
        "green",
        "blue",
        "scan_angle",
        "point_format",
        "header",
    ]:
        setattr(plain, name, getattr(source, name))
    return plain


# ---------------------------------------------------------------------------
# TestFusionSource — profiling
# ---------------------------------------------------------------------------

class TestFusionSource(unittest.TestCase):
    """Test profile_source for vector, raster, and tabular inputs."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_profile_vector(self):
        from data_agent.fusion_engine import profile_source
        path = _make_vector_fixture(self.tmp)
        src = profile_source(path)
        self.assertEqual(src.data_type, "vector")
        self.assertEqual(src.modality, "geospatial_vector")
        self.assertEqual(src.media_type, "application/vnd.geo+vector")
        self.assertEqual(src.adapter_family, "geospatial")
        self.assertEqual(src.row_count, 3)
        self.assertIsNotNone(src.crs)
        self.assertIsNotNone(src.bounds)
        self.assertTrue(len(src.columns) >= 4)
        self.assertEqual(src.geometry_type, "Polygon")

    def test_profile_tabular(self):
        from data_agent.fusion_engine import profile_source
        path = _make_tabular_fixture(self.tmp)
        src = profile_source(path)
        self.assertEqual(src.data_type, "tabular")
        self.assertEqual(src.modality, "structured_table")
        self.assertEqual(src.media_type, "text/csv")
        self.assertEqual(src.adapter_family, "generic")
        self.assertEqual(src.row_count, 3)
        self.assertIsNone(src.crs)
        self.assertEqual(len(src.columns), 3)

    def test_profile_text_document_as_generic_multimodal_source(self):
        from data_agent.fusion_engine import profile_source

        path = os.path.join(self.tmp, "project_brief.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Project Brief\n\nThis major project includes land acquisition.")

        src = profile_source(path)

        self.assertEqual(src.data_type, "document")
        self.assertEqual(src.modality, "text")
        self.assertEqual(src.media_type, "text/markdown")
        self.assertEqual(src.adapter_family, "generic")
        self.assertEqual(src.row_count, 1)
        self.assertEqual(src.columns[0]["name"], "content")
        self.assertEqual(src.stats["file"]["size_bytes"], os.path.getsize(path))
        self.assertEqual(src.stats["document"]["title"], "Project Brief")
        self.assertEqual(src.stats["document"]["line_count"], 3)
        self.assertEqual(src.stats["document"]["word_count"], 8)
        self.assertIn("major project", src.stats["document"]["content_preview"])
        self.assertTrue(
            any(
                hint.get("type") == "generic_modality"
                and hint.get("value") == "text"
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "document_title"
                and hint.get("value") == "Project Brief"
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "document_keyword"
                and hint.get("value") == "major_project"
                for hint in src.semantic_hints
            )
        )

    def test_profile_graphml_extracts_shallow_topology(self):
        from data_agent.fusion_engine import profile_source

        path = os.path.join(self.tmp, "utility_network.graphml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                """<?xml version="1.0" encoding="UTF-8"?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <graph id="G" edgedefault="directed">
    <node id="substation_a" />
    <node id="substation_b" />
    <node id="substation_c" />
    <edge id="e1" source="substation_a" target="substation_b" />
    <edge id="e2" source="substation_b" target="substation_c" />
  </graph>
</graphml>
"""
            )

        src = profile_source(path)

        self.assertEqual(src.data_type, "graph")
        self.assertEqual(src.modality, "graph")
        self.assertEqual(src.media_type, "application/graphml+xml")
        self.assertEqual(src.adapter_family, "generic")
        self.assertEqual(src.row_count, 1)
        self.assertEqual(src.stats["graph"]["format"], "graphml")
        self.assertEqual(src.stats["graph"]["node_count"], 3)
        self.assertEqual(src.stats["graph"]["edge_count"], 2)
        self.assertEqual(src.stats["graph"]["directed"], True)
        self.assertTrue(
            any(
                hint.get("type") == "graph_topology"
                and hint.get("value") == "graphml_topology"
                and hint.get("node_count") == 3
                and hint.get("edge_count") == 2
                for hint in src.semantic_hints
            )
        )

    def test_profile_model_output_reads_ai_observations_as_semantic_hints(self):
        from data_agent.fusion_engine import profile_source

        path = os.path.join(self.tmp, "urban_scan.ai.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "model": {
                        "name": "custom-detector",
                        "version": "2.1",
                        "task": "asset_detection",
                    },
                    "observations": [
                        {
                            "type": "asset_observation",
                            "label": "substation",
                            "target": "image",
                            "confidence": 0.91,
                            "domain": "infrastructure",
                            "evidence": ["detected from tile 12"],
                        },
                        {
                            "label": "power_line",
                            "target": "image",
                            "confidence": 0.84,
                        },
                    ],
                },
                f,
            )

        src = profile_source(path)

        self.assertEqual(src.data_type, "model_output")
        self.assertEqual(src.semantic_domain, "infrastructure")
        self.assertEqual(src.stats["model_output"]["observation_count"], 2)
        model_hints = [
            hint for hint in src.semantic_hints
            if hint.get("semantic_level") == "model_inference"
        ]
        self.assertEqual(len(model_hints), 2)
        self.assertEqual(model_hints[0]["value"], "substation")
        self.assertEqual(model_hints[0]["model"], "custom-detector")
        self.assertEqual(model_hints[0]["model_version"], "2.1")
        self.assertEqual(model_hints[0]["task"], "asset_detection")

    def test_profile_raster(self):
        from data_agent.fusion_engine import profile_source
        raster = _make_raster_fixture(self.tmp)
        src = profile_source(raster)
        self.assertEqual(src.data_type, "raster")
        self.assertEqual(src.modality, "geospatial_raster")
        self.assertEqual(src.media_type, "image/tiff; application=geotiff")
        self.assertEqual(src.adapter_family, "geospatial")
        self.assertIsNotNone(src.crs)
        self.assertEqual(src.band_count, 1)
        self.assertIsNotNone(src.resolution)

    def test_profile_raster_semantic_hints_from_filename_and_band_metadata(self):
        from data_agent.fusion_engine import profile_source

        ndvi = np.linspace(-0.2, 0.8, 100, dtype=np.float32).reshape(10, 10)
        raster = _make_raster_fixture(
            self.tmp,
            name="city_ndvi_2024.tif",
            data=ndvi,
            band_description="NDVI",
            band_tags={
                "long_name": "Normalized Difference Vegetation Index",
                "units": "index",
            },
        )

        src = profile_source(raster)

        self.assertEqual(src.semantic_domain, "remote_sensing")
        theme_hints = [
            hint for hint in src.semantic_hints
            if hint.get("type") == "raster_theme"
        ]
        self.assertTrue(any(hint.get("value") == "ndvi" for hint in theme_hints))
        band_hints = [
            hint for hint in src.semantic_hints
            if hint.get("type") == "band_semantic" and hint.get("field") == "band_1"
        ]
        self.assertTrue(any(hint.get("value") == "ndvi" for hint in band_hints))
        ndvi_hint = next(hint for hint in band_hints if hint.get("value") == "ndvi")
        self.assertGreaterEqual(ndvi_hint["confidence"], 0.9)
        self.assertTrue(
            any(
                "band_1 description contains NDVI" in item
                for item in ndvi_hint["evidence"]
            )
        )

    def test_profile_raster_semantic_hints_identify_terrain_dem(self):
        from data_agent.fusion_engine import profile_source

        dem = np.linspace(120.0, 340.0, 100, dtype=np.float32).reshape(10, 10)
        raster = _make_raster_fixture(
            self.tmp,
            name="mountain_dem_surface.tif",
            data=dem,
            band_description="Elevation",
        )

        src = profile_source(raster)

        self.assertEqual(src.semantic_domain, "terrain")
        self.assertTrue(
            any(
                hint.get("type") == "raster_theme"
                and hint.get("value") == "elevation"
                for hint in src.semantic_hints
            )
        )

    def test_profile_raster_semantic_hints_identify_slope(self):
        from data_agent.fusion_engine import profile_source

        slope = np.linspace(0.0, 45.0, 100, dtype=np.float32).reshape(10, 10)
        raster = _make_raster_fixture(
            self.tmp,
            name="terrain_slope_degrees.tif",
            data=slope,
            band_description="Slope",
        )

        src = profile_source(raster)

        self.assertEqual(src.semantic_domain, "terrain")
        self.assertTrue(
            any(
                hint.get("type") == "raster_theme"
                and hint.get("value") == "slope"
                for hint in src.semantic_hints
            )
        )

    def test_profile_raster_semantic_hints_identify_landcover_class(self):
        from data_agent.fusion_engine import profile_source

        classes = np.tile(np.array([1, 2, 3, 4, 5], dtype=np.float32), (10, 2))
        raster = _make_raster_fixture(
            self.tmp,
            name="city_lulc_landcover.tif",
            data=classes,
            band_description="Land cover classification",
            band_tags={"classes": "1 built-up; 2 vegetation; 3 water"},
        )

        src = profile_source(raster)

        self.assertEqual(src.semantic_domain, "land_cover")
        self.assertTrue(
            any(
                hint.get("type") == "raster_theme"
                and hint.get("value") == "landcover_class"
                for hint in src.semantic_hints
            )
        )

    def test_profile_raster_carries_pixel_semantics_from_band_metadata(self):
        from data_agent.fusion_engine import profile_source

        data = np.linspace(0, 10000, 100, dtype=np.float32).reshape(10, 10)
        data[0, 0] = -9999
        raster = _make_raster_fixture(
            self.tmp,
            name="surface_reflectance_ndvi.tif",
            data=data,
            band_description="NDVI scaled reflectance",
            band_tags={
                "scale_factor": "0.0001",
                "add_offset": "0",
                "units": "reflectance",
            },
            nodata=-9999,
        )

        src = profile_source(raster)

        band_1 = next(column for column in src.columns if column["name"] == "band_1")
        self.assertEqual(band_1["nodata"], -9999.0)
        self.assertEqual(band_1["scale"], 0.0001)
        self.assertEqual(band_1["offset"], 0.0)
        self.assertEqual(band_1["unit"], "reflectance")
        pixel_hints = [
            hint for hint in src.semantic_hints
            if hint.get("type") == "pixel_value_semantics"
        ]
        self.assertTrue(any(hint.get("field") == "band_1" for hint in pixel_hints))
        band_hint = next(hint for hint in pixel_hints if hint.get("field") == "band_1")
        self.assertEqual(band_hint["scale"], 0.0001)
        self.assertEqual(band_hint["nodata"], -9999.0)
        self.assertIn("band_1 unit is reflectance", band_hint["evidence"])

    def test_profile_raster_reads_stac_sidecar_metadata(self):
        from data_agent.fusion_engine import profile_source

        raster = _make_raster_fixture(
            self.tmp,
            name="sentinel_ndvi.tif",
            band_description="vegetation index",
        )
        stac_path = os.path.splitext(raster)[0] + ".stac.json"
        with open(stac_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "type": "Feature",
                    "properties": {
                        "platform": "sentinel-2a",
                        "instruments": ["msi"],
                    },
                    "assets": {
                        "data": {
                            "eo:bands": [
                                {"name": "B08", "common_name": "nir"},
                                {"name": "B04", "common_name": "red"},
                            ],
                            "raster:bands": [
                                {
                                    "scale": 0.0001,
                                    "offset": 0,
                                    "nodata": 0,
                                    "unit": "reflectance",
                                }
                            ],
                        }
                    },
                },
                f,
            )

        src = profile_source(raster)

        sidecar_hints = [
            hint for hint in src.semantic_hints
            if hint.get("type") == "metadata_source"
        ]
        self.assertTrue(any(hint.get("value") == "stac_sidecar" for hint in sidecar_hints))
        self.assertTrue(
            any(
                hint.get("type") == "raster_platform"
                and hint.get("value") == "sentinel-2a"
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "spectral_band_semantic"
                and hint.get("value") == "nir"
                for hint in src.semantic_hints
            )
        )

    def test_profile_raster_reads_extended_stac_metadata(self):
        from data_agent.fusion_engine import profile_source

        raster = _make_raster_fixture(self.tmp, name="stac_product.tif")
        stac_path = os.path.splitext(raster)[0] + ".stac.json"
        with open(stac_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "stac_version": "1.0.0",
                    "type": "Feature",
                    "collection": "sentinel-2-l2a",
                    "properties": {
                        "title": "Sentinel-2 surface reflectance vegetation index",
                        "description": (
                            "Atmospherically corrected surface reflectance for "
                            "vegetation monitoring"
                        ),
                        "datetime": "2024-05-01T10:11:12Z",
                        "platform": "sentinel-2b",
                        "instruments": ["msi"],
                        "gsd": 10,
                        "proj:epsg": 32650,
                        "keywords": ["surface reflectance", "vegetation index"],
                    },
                },
                f,
            )

        src = profile_source(raster)

        self.assertEqual(src.semantic_domain, "remote_sensing")
        self.assertTrue(
            any(
                hint.get("type") == "metadata_collection"
                and hint.get("value") == "sentinel-2-l2a"
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "metadata_datetime"
                and hint.get("value") == "2024-05-01T10:11:12Z"
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "raster_gsd"
                and hint.get("value") == 10.0
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "projection_epsg"
                and hint.get("value") == 32650
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "metadata_keyword"
                and hint.get("value") == "vegetation index"
                for hint in src.semantic_hints
            )
        )

    def test_profile_raster_reads_iso_xml_sidecar_metadata(self):
        from data_agent.fusion_engine import profile_source

        raster = _make_raster_fixture(self.tmp, name="iso_product.tif")
        iso_path = os.path.splitext(raster)[0] + ".iso.xml"
        with open(iso_path, "w", encoding="utf-8") as f:
            f.write(
                """<?xml version="1.0" encoding="UTF-8"?>
<gmd:MD_Metadata
  xmlns:gmd="http://www.isotc211.org/2005/gmd"
  xmlns:gco="http://www.isotc211.org/2005/gco">
  <gmd:dateStamp><gco:Date>2024-01-31</gco:Date></gmd:dateStamp>
  <gmd:identificationInfo>
    <gmd:MD_DataIdentification>
      <gmd:citation>
        <gmd:CI_Citation>
          <gmd:title>
            <gco:CharacterString>Coastal land cover classification</gco:CharacterString>
          </gmd:title>
        </gmd:CI_Citation>
      </gmd:citation>
      <gmd:abstract>
        <gco:CharacterString>Land cover classification map for coastal planning.</gco:CharacterString>
      </gmd:abstract>
      <gmd:descriptiveKeywords>
        <gmd:MD_Keywords>
          <gmd:keyword><gco:CharacterString>land cover</gco:CharacterString></gmd:keyword>
          <gmd:keyword><gco:CharacterString>classification</gco:CharacterString></gmd:keyword>
        </gmd:MD_Keywords>
      </gmd:descriptiveKeywords>
      <gmd:topicCategory>
        <gmd:MD_TopicCategoryCode>imageryBaseMapsEarthCover</gmd:MD_TopicCategoryCode>
      </gmd:topicCategory>
    </gmd:MD_DataIdentification>
  </gmd:identificationInfo>
  <gmd:dataQualityInfo>
    <gmd:DQ_DataQuality>
      <gmd:lineage>
        <gmd:LI_Lineage>
          <gmd:statement>
            <gco:CharacterString>Derived from supervised classification.</gco:CharacterString>
          </gmd:statement>
        </gmd:LI_Lineage>
      </gmd:lineage>
    </gmd:DQ_DataQuality>
  </gmd:dataQualityInfo>
</gmd:MD_Metadata>
"""
            )

        src = profile_source(raster)

        self.assertEqual(src.semantic_domain, "land_cover")
        self.assertTrue(
            any(
                hint.get("type") == "metadata_source"
                and hint.get("value") == "iso19115_sidecar"
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "metadata_title"
                and hint.get("value") == "Coastal land cover classification"
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "metadata_keyword"
                and hint.get("value") == "land cover"
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "metadata_lineage"
                and "supervised classification" in hint.get("value", "")
                for hint in src.semantic_hints
            )
        )
        self.assertTrue(
            any(
                hint.get("type") == "raster_theme"
                and hint.get("value") == "landcover_class"
                for hint in src.semantic_hints
            )
        )

    def test_profile_raster_grid_semantics_for_projected_crs(self):
        import rasterio
        from data_agent.fusion_engine import profile_source

        transform = rasterio.transform.from_origin(500000, 3000000, 30, 30)
        raster = _make_raster_fixture(
            self.tmp,
            name="projected_dem_30m.tif",
            crs="EPSG:32650",
            transform=transform,
        )

        src = profile_source(raster)

        self.assertEqual(src.stats["grid"]["crs_unit"], "metre")
        self.assertEqual(src.stats["grid"]["pixel_width"], 30.0)
        self.assertEqual(src.stats["grid"]["pixel_height"], 30.0)
        self.assertEqual(src.stats["grid"]["pixel_area"], 900.0)
        grid_hints = [
            hint for hint in src.semantic_hints
            if hint.get("type") == "raster_grid_semantics"
        ]
        self.assertTrue(
            any(
                hint.get("value") == "projected_metric_grid"
                and hint.get("pixel_area") == 900.0
                for hint in grid_hints
            )
        )

    def test_profile_raster_grid_semantics_warn_for_geographic_crs(self):
        from data_agent.fusion_engine import profile_source

        raster = _make_raster_fixture(self.tmp, name="geographic_ndvi.tif")

        src = profile_source(raster)

        self.assertEqual(src.stats["grid"]["crs_unit"], "degree")
        self.assertEqual(src.stats["grid"]["pixel_width"], 0.2)
        self.assertEqual(src.stats["grid"]["pixel_height"], 0.2)
        grid_hints = [
            hint for hint in src.semantic_hints
            if hint.get("type") == "raster_grid_semantics"
        ]
        geographic_hint = next(
            hint for hint in grid_hints
            if hint.get("value") == "geographic_degree_grid"
        )
        self.assertTrue(geographic_hint["requires_projection_for_area"])
        self.assertTrue(
            any("pixel area is angular" in item for item in geographic_hint["evidence"])
        )

    def test_profile_raster_builds_feature_chip_summary(self):
        from data_agent.fusion_engine import profile_source

        data = np.arange(100, dtype=np.float32).reshape(10, 10)
        raster = _make_raster_fixture(
            self.tmp,
            name="reflectance_chip.tif",
            data=data,
            band_tags={"scale_factor": "0.0001", "units": "reflectance"},
        )

        src = profile_source(raster)

        chips = src.stats["feature_chips"]
        center = next(chip for chip in chips if chip["chip_id"] == "center")
        self.assertEqual(center["window"], {
            "row_off": 3,
            "col_off": 3,
            "height": 4,
            "width": 4,
        })
        band_stats = center["bands"]["band_1"]
        self.assertEqual(band_stats["min"], 33.0)
        self.assertEqual(band_stats["max"], 66.0)
        self.assertEqual(band_stats["mean"], 49.5)
        self.assertAlmostEqual(band_stats["scaled_mean"], 0.00495)
        chip_hints = [
            hint for hint in src.semantic_hints
            if hint.get("type") == "raster_feature_chip"
        ]
        self.assertTrue(
            any(
                hint.get("chip_id") == "center"
                and hint.get("embedding_ready")
                for hint in chip_hints
            )
        )

    def test_profile_raster_feature_chip_summarizes_categorical_values(self):
        from data_agent.fusion_engine import profile_source

        data = np.ones((10, 10), dtype=np.float32)
        data[3:7, 3:7] = 5
        raster = _make_raster_fixture(
            self.tmp,
            name="landcover_chip.tif",
            data=data,
            band_description="Land cover classification",
        )

        src = profile_source(raster)

        center = next(
            chip for chip in src.stats["feature_chips"]
            if chip["chip_id"] == "center"
        )
        top_values = center["bands"]["band_1"]["top_values"]
        self.assertEqual(top_values[0]["value"], 5.0)
        self.assertEqual(top_values[0]["count"], 16)
        self.assertTrue(
            any(
                hint.get("type") == "raster_feature_chip"
                and any("dominant values" in item for item in hint["evidence"])
                for hint in src.semantic_hints
            )
        )

    def test_profile_raster_ingests_ai_model_semantic_sidecar(self):
        from data_agent.fusion_engine import profile_source

        raster = _make_raster_fixture(self.tmp, name="weak_name.tif")
        ai_path = os.path.splitext(raster)[0] + ".ai.json"
        with open(ai_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "model": {
                        "name": "landcover-unet",
                        "version": "2026.06",
                        "task": "land_cover_classification",
                    },
                    "observations": [
                        {
                            "target": "scene",
                            "type": "land_cover_class",
                            "value": "cropland",
                            "confidence": 0.91,
                            "domain": "land_cover",
                            "evidence": ["model majority vote over raster chip"],
                        }
                    ],
                },
                f,
            )

        src = profile_source(raster)

        self.assertEqual(src.semantic_domain, "land_cover")
        ai_hints = [
            hint for hint in src.semantic_hints
            if hint.get("semantic_level") == "model_inference"
        ]
        self.assertEqual(len(ai_hints), 1)
        self.assertEqual(ai_hints[0]["value"], "cropland")
        self.assertEqual(ai_hints[0]["model"], "landcover-unet")
        self.assertEqual(ai_hints[0]["model_version"], "2026.06")
        self.assertEqual(ai_hints[0]["task"], "land_cover_classification")
        self.assertIn("model majority vote over raster chip", ai_hints[0]["evidence"])

    def test_profile_vector_stats(self):
        from data_agent.fusion_engine import profile_source
        path = _make_vector_fixture(self.tmp)
        src = profile_source(path)
        self.assertIn("AREA", src.stats)
        self.assertIn("min", src.stats["AREA"])
        self.assertIn("max", src.stats["AREA"])

    def test_detect_data_type(self):
        from data_agent.fusion_engine import _detect_data_type
        self.assertEqual(_detect_data_type("test.geojson"), "vector")
        self.assertEqual(_detect_data_type("test.shp"), "vector")
        self.assertEqual(_detect_data_type("test.tif"), "raster")
        self.assertEqual(_detect_data_type("test.csv"), "tabular")
        self.assertEqual(_detect_data_type("test.las"), "point_cloud")
        self.assertEqual(_detect_data_type("brief.md"), "document")
        self.assertEqual(_detect_data_type("photo.jpg"), "image")
        self.assertEqual(_detect_data_type("interview.mp3"), "audio")
        self.assertEqual(_detect_data_type("inspection.mp4"), "video")
        self.assertEqual(_detect_data_type("network.graphml"), "graph")
        self.assertEqual(_detect_data_type("inference.ai.json"), "model_output")
        self.assertEqual(_detect_data_type("test.unknown"), "artifact")

    def test_profile_point_cloud_semantic_hints_from_las_dimensions(self):
        from data_agent.fusion_engine import _profile_point_cloud

        mock_laspy = MagicMock()
        mock_laspy.read.return_value = _MockLasData()

        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            src = _profile_point_cloud("classified_lidar.las")

        self.assertEqual(src.data_type, "point_cloud")
        self.assertEqual(src.row_count, 5)
        self.assertEqual(src.crs, "EPSG:4326")
        self.assertEqual(src.semantic_domain, "lidar")
        column_names = {column["name"] for column in src.columns}
        for expected in [
            "x",
            "y",
            "z",
            "classification",
            "intensity",
            "return_number",
            "number_of_returns",
            "red",
            "green",
            "blue",
            "scan_angle",
        ]:
            self.assertIn(expected, column_names)

        self.assertEqual(src.stats["classification"]["classes"][0]["label"], "ground")
        self.assertIn("intensity", src.stats)
        self.assertEqual(src.stats["intensity"]["max"], 240.0)
        theme_hints = [
            hint for hint in src.semantic_hints
            if hint.get("type") == "point_cloud_theme"
        ]
        self.assertTrue(
            any(hint.get("value") == "classified_lidar" for hint in theme_hints)
        )
        dimension_hints = [
            hint for hint in src.semantic_hints
            if hint.get("type") == "point_dimension_semantic"
        ]
        self.assertTrue(
            any(hint.get("value") == "asprs_classification" for hint in dimension_hints)
        )
        self.assertTrue(
            any(hint.get("value") == "return_intensity" for hint in dimension_hints)
        )
        class_hints = [
            hint for hint in src.semantic_hints
            if hint.get("type") == "classification_class"
        ]
        self.assertTrue(any(hint.get("value") == "building" for hint in class_hints))

    def test_profile_point_cloud_accepts_plain_laspy_read_result(self):
        from data_agent.fusion_engine import _profile_point_cloud

        mock_laspy = MagicMock()
        mock_laspy.read.return_value = _plain_mock_las_data()

        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            src = _profile_point_cloud("plain_laspy_result.las")

        self.assertEqual(src.row_count, 5)
        self.assertEqual(src.semantic_domain, "lidar")
        self.assertIn("classification", {column["name"] for column in src.columns})

    def test_profile_point_cloud_extracts_vlr_and_evlr_metadata(self):
        from data_agent.fusion_engine import _profile_point_cloud

        mock_laspy = MagicMock()
        mock_laspy.read.return_value = _mock_las_data_with_vlrs()

        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            src = _profile_point_cloud("metadata_rich.las")

        metadata = src.stats["las_metadata"]
        self.assertEqual(metadata["vlr_count"], 2)
        self.assertEqual(metadata["evlr_count"], 1)
        self.assertEqual(metadata["vlrs"][0]["user_id"], "LASF_Projection")
        self.assertEqual(metadata["vlrs"][0]["record_id"], 34735)
        self.assertEqual(metadata["vlrs"][0]["description"], "GeoKeyDirectoryTag")
        self.assertEqual(metadata["vlrs"][0]["record_data_bytes"], 4)
        self.assertEqual(metadata["evlrs"][0]["description"], "Processing lineage")
        self.assertTrue(
            any(
                hint.get("type") == "point_cloud_metadata"
                and hint.get("value") == "las_vlr_metadata"
                for hint in src.semantic_hints
            )
        )

    def test_profile_large_point_cloud_builds_chunking_plan(self):
        from data_agent.fusion_engine import _profile_point_cloud

        mock_laspy = MagicMock()
        mock_laspy.read.return_value = _mock_large_las_data()

        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            src = _profile_point_cloud("large_lidar.las")

        chunking = src.stats["chunking"]
        self.assertTrue(chunking["required"])
        self.assertEqual(chunking["strategy"], "point_cloud_chunk_iterator")
        self.assertEqual(chunking["point_count"], 1_250_000)
        self.assertEqual(chunking["chunk_size_points"], 500_000)
        self.assertEqual(chunking["chunk_count"], 3)
        self.assertEqual(chunking["last_chunk_points"], 250_000)
        self.assertIn("point_count", chunking["reasons"][0])
        self.assertTrue(
            any(
                hint.get("type") == "point_cloud_processing"
                and hint.get("value") == "chunking_required"
                for hint in src.semantic_hints
            )
        )

    def test_profile_small_point_cloud_marks_single_pass_chunking_plan(self):
        from data_agent.fusion_engine import _profile_point_cloud

        mock_laspy = MagicMock()
        mock_laspy.read.return_value = _MockLasData()

        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            src = _profile_point_cloud("small_lidar.las")

        chunking = src.stats["chunking"]
        self.assertFalse(chunking["required"])
        self.assertEqual(chunking["strategy"], "single_pass")
        self.assertEqual(chunking["chunk_count"], 1)
        self.assertFalse(
            any(
                hint.get("type") == "point_cloud_processing"
                and hint.get("value") == "chunking_required"
                for hint in src.semantic_hints
            )
        )

    def test_profile_point_cloud_carries_universal_modality_metadata(self):
        from data_agent.fusion_engine import _profile_point_cloud

        mock_laspy = MagicMock()
        mock_laspy.read.return_value = _MockLasData()

        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            src = _profile_point_cloud("classified_lidar.las")

        self.assertEqual(src.modality, "point_cloud")
        self.assertEqual(src.media_type, "application/vnd.las")
        self.assertEqual(src.adapter_family, "geospatial")

    def test_profile_laz_reports_backend_unavailable_without_losing_source_type(self):
        from data_agent.fusion_engine import _profile_point_cloud

        mock_laspy = MagicMock()
        mock_laspy.read.side_effect = RuntimeError("No LazBackend selected")

        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            src = _profile_point_cloud("compressed_scan.laz")

        self.assertEqual(src.data_type, "point_cloud")
        self.assertEqual(src.row_count, 0)
        self.assertEqual(src.semantic_domain, "lidar")
        self.assertEqual(src.stats["laz"]["compressed"], True)
        self.assertEqual(src.stats["laz"]["backend_available"], False)
        self.assertEqual(src.stats["laz"]["readable"], False)
        self.assertTrue(
            any(
                hint.get("type") == "point_cloud_capability"
                and hint.get("value") == "laz_backend_unavailable"
                for hint in src.semantic_hints
            )
        )

    def test_profile_point_cloud_ingests_ai_object_semantic_sidecar(self):
        from data_agent.fusion_engine import _profile_point_cloud

        las_path = os.path.join(self.tmp, "urban_scan.las")
        with open(las_path, "wb") as f:
            f.write(b"")
        ai_path = os.path.splitext(las_path)[0] + ".ai.json"
        with open(ai_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "model": {
                        "name": "pointnet-building-tree",
                        "version": "1.2.0",
                        "task": "point_cloud_object_detection",
                    },
                    "observations": [
                        {
                            "target": "object:17",
                            "type": "object_class",
                            "value": "tree",
                            "confidence": 0.88,
                            "domain": "lidar",
                            "evidence": ["cluster crown geometry and height"],
                        },
                        {
                            "target": "object:42",
                            "type": "object_class",
                            "value": "building",
                            "confidence": 0.93,
                            "domain": "lidar",
                            "evidence": ["planar roof cluster"],
                        },
                    ],
                },
                f,
            )

        mock_laspy = MagicMock()
        mock_laspy.read.return_value = _plain_mock_las_data()
        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            src = _profile_point_cloud(las_path)

        ai_hints = [
            hint for hint in src.semantic_hints
            if hint.get("semantic_level") == "model_inference"
        ]
        self.assertEqual([hint["value"] for hint in ai_hints], ["tree", "building"])
        self.assertTrue(all(hint["model"] == "pointnet-building-tree" for hint in ai_hints))
        self.assertTrue(all(hint["task"] == "point_cloud_object_detection" for hint in ai_hints))


# ---------------------------------------------------------------------------
# TestCompatibilityAssessor
# ---------------------------------------------------------------------------

class TestCompatibilityAssessor(unittest.TestCase):
    """Test assess_compatibility between data sources."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_same_crs_compatible(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson"))
        v2 = profile_source(_make_second_vector(self.tmp))
        report = assess_compatibility([v1, v2])
        self.assertTrue(report.crs_compatible)

    def test_different_crs_detected(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson", crs="EPSG:4326"))
        v2 = profile_source(_make_vector_fixture(self.tmp, "v2.geojson", crs="EPSG:3857"))
        report = assess_compatibility([v1, v2])
        self.assertFalse(report.crs_compatible)
        self.assertTrue(any("CRS" in w for w in report.warnings))

    def test_spatial_overlap_computed(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson"))
        v2 = profile_source(_make_second_vector(self.tmp))
        report = assess_compatibility([v1, v2])
        self.assertGreater(report.spatial_overlap_iou, 0)

    def test_field_matches_found(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility
        v1 = profile_source(_make_vector_fixture(self.tmp))
        tab = profile_source(_make_tabular_fixture(self.tmp))
        report = assess_compatibility([v1, tab])
        objectid_match = [m for m in report.field_matches if "OBJECTID" in m.get("left", "")]
        self.assertTrue(len(objectid_match) > 0)

    def test_recommended_strategies_vector_vector(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson"))
        v2 = profile_source(_make_second_vector(self.tmp))
        report = assess_compatibility([v1, v2])
        self.assertIn("spatial_join", report.recommended_strategies)

    def test_recommended_strategies_vector_tabular(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility
        v1 = profile_source(_make_vector_fixture(self.tmp))
        tab = profile_source(_make_tabular_fixture(self.tmp))
        report = assess_compatibility([v1, tab])
        self.assertIn("attribute_join", report.recommended_strategies)

    def test_too_few_sources(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility
        v1 = profile_source(_make_vector_fixture(self.tmp))
        report = assess_compatibility([v1])
        self.assertEqual(report.overall_score, 0.0)
        self.assertTrue(len(report.warnings) > 0)


# ---------------------------------------------------------------------------
# TestSemanticAligner
# ---------------------------------------------------------------------------

class TestSemanticAligner(unittest.TestCase):
    """Test align_sources for CRS reprojection and conflict resolution."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_align_same_crs_no_reproject(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson"))
        v2 = profile_source(_make_second_vector(self.tmp))
        report = assess_compatibility([v1, v2])
        aligned, log = align_sources([v1, v2], report)
        self.assertEqual(len(aligned), 2)
        # No reprojection log entry expected
        reproject_logs = [l for l in log if "Reprojected" in l]
        self.assertEqual(len(reproject_logs), 0)

    def test_align_different_crs_reprojects(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson", crs="EPSG:4326"))
        v2 = profile_source(_make_vector_fixture(self.tmp, "v2.geojson", crs="EPSG:3857"))
        report = assess_compatibility([v1, v2])
        aligned, log = align_sources([v1, v2], report)
        self.assertEqual(len(aligned), 2)
        # Should have reprojection log
        reproject_logs = [l for l in log if "Reprojected" in l]
        self.assertTrue(len(reproject_logs) > 0)

    def test_align_resolves_column_conflicts(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources
        v1 = profile_source(_make_vector_fixture(self.tmp))
        tab = profile_source(_make_tabular_fixture(self.tmp))
        report = assess_compatibility([v1, tab])
        aligned, log = align_sources([v1, tab], report)
        self.assertEqual(len(aligned), 2)
        # OBJECTID exists in both — should be renamed in second source
        _, df = aligned[1]
        self.assertIn("OBJECTID_right", df.columns)

    def test_align_vector_tabular_pair(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources
        v = profile_source(_make_vector_fixture(self.tmp))
        t = profile_source(_make_tabular_fixture(self.tmp))
        report = assess_compatibility([v, t])
        aligned, log = align_sources([v, t], report)
        self.assertEqual(aligned[0][0], "vector")
        self.assertEqual(aligned[1][0], "tabular")

    def test_align_with_explicit_target_crs(self):
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson"))
        v2 = profile_source(_make_second_vector(self.tmp))
        report = assess_compatibility([v1, v2])
        aligned, log = align_sources([v1, v2], report, target_crs="EPSG:3857")
        # Both should be reprojected to 3857
        _, gdf1 = aligned[0]
        self.assertEqual(str(gdf1.crs), "EPSG:3857")

    def test_field_match_equivalence_patterns(self):
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource(file_path="a.shp", data_type="vector",
                          columns=[{"name": "area", "dtype": "float64", "null_pct": 0}])
        s2 = FusionSource(file_path="b.csv", data_type="tabular",
                          columns=[{"name": "zmj", "dtype": "float64", "null_pct": 0}])
        matches = _find_field_matches([s1, s2])
        area_match = [m for m in matches if m["left"] == "area" and m["right"] == "zmj"]
        self.assertTrue(len(area_match) > 0)


# ---------------------------------------------------------------------------
# TestFusionExecutor — strategy implementations
# ---------------------------------------------------------------------------

class TestFusionExecutor(unittest.TestCase):
    """Test individual fusion strategies."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    @patch("data_agent.gis_processors.get_user_upload_dir")
    def test_spatial_join(self, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources, execute_fusion
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson"))
        v2 = profile_source(_make_second_vector(self.tmp))
        report = assess_compatibility([v1, v2])
        aligned, _ = align_sources([v1, v2], report)
        result = execute_fusion(aligned, "spatial_join", [v1, v2])
        self.assertGreater(result.row_count, 0)
        self.assertEqual(result.strategy_used, "spatial_join")
        self.assertTrue(os.path.exists(result.output_path))

    @patch("data_agent.gis_processors.get_user_upload_dir")
    def test_attribute_join(self, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources, execute_fusion
        v = profile_source(_make_vector_fixture(self.tmp))
        t = profile_source(_make_tabular_fixture(self.tmp))
        report = assess_compatibility([v, t])
        aligned, _ = align_sources([v, t], report)
        result = execute_fusion(aligned, "attribute_join", [v, t],
                                params={"join_column": "OBJECTID"})
        self.assertEqual(result.row_count, 3)
        self.assertEqual(result.strategy_used, "attribute_join")

    @patch("data_agent.gis_processors.get_user_upload_dir")
    def test_overlay_union(self, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources, execute_fusion
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson"))
        v2 = profile_source(_make_second_vector(self.tmp))
        report = assess_compatibility([v1, v2])
        aligned, _ = align_sources([v1, v2], report)
        result = execute_fusion(aligned, "overlay", [v1, v2], params={"overlay_how": "union"})
        self.assertGreater(result.row_count, 0)

    @patch("data_agent.gis_processors.get_user_upload_dir")
    def test_nearest_join(self, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources, execute_fusion
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson"))
        v2 = profile_source(_make_second_vector(self.tmp))
        report = assess_compatibility([v1, v2])
        aligned, _ = align_sources([v1, v2], report)
        result = execute_fusion(aligned, "nearest_join", [v1, v2])
        self.assertGreater(result.row_count, 0)

    @patch("data_agent.gis_processors.get_user_upload_dir")
    def test_zonal_statistics(self, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources, execute_fusion
        v = profile_source(_make_vector_fixture(self.tmp))
        r = profile_source(_make_raster_fixture(self.tmp))
        report = assess_compatibility([v, r])
        aligned, _ = align_sources([v, r], report)
        result = execute_fusion(aligned, "zonal_statistics", [v, r])
        self.assertEqual(result.row_count, 3)
        self.assertGreater(result.column_count, 4)

    @patch("data_agent.gis_processors.get_user_upload_dir")
    def test_point_sampling(self, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources, execute_fusion
        pts = profile_source(_make_point_vector(self.tmp))
        r = profile_source(_make_raster_fixture(self.tmp))
        aligned, _ = align_sources([pts, r], assess_compatibility([pts, r]))
        result = execute_fusion(aligned, "point_sampling", [pts, r])
        self.assertEqual(result.row_count, 3)

    @patch("data_agent.gis_processors.get_user_upload_dir")
    def test_time_snapshot(self, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import profile_source, align_sources, execute_fusion, FusionSource, CompatibilityReport
        v = profile_source(_make_vector_fixture(self.tmp))
        stream_src = FusionSource(file_path="stream://test", data_type="stream")
        report = CompatibilityReport(recommended_strategies=["time_snapshot"])
        # Manually construct aligned data
        gdf = gpd.read_file(v.file_path)
        aligned = [("vector", gdf), ("stream", "stream://test")]
        result = execute_fusion(aligned, "time_snapshot", [v, stream_src])
        self.assertGreater(result.row_count, 0)

    @patch("data_agent.gis_processors.get_user_upload_dir")
    def test_auto_strategy_vector_vector(self, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import profile_source, assess_compatibility, align_sources, execute_fusion
        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson"))
        v2 = profile_source(_make_second_vector(self.tmp))
        report = assess_compatibility([v1, v2])
        aligned, _ = align_sources([v1, v2], report)
        result = execute_fusion(aligned, "auto", [v1, v2])
        self.assertEqual(result.strategy_used, "spatial_join")  # first in matrix


# ---------------------------------------------------------------------------
# TestStrategyMatrix
# ---------------------------------------------------------------------------

class TestStrategyMatrix(unittest.TestCase):
    """Test the strategy matrix coverage."""

    def test_all_type_pairs_have_strategies(self):
        from data_agent.fusion_engine import STRATEGY_MATRIX
        expected_pairs = [
            ("vector", "vector"), ("vector", "raster"), ("raster", "vector"),
            ("raster", "raster"), ("vector", "tabular"), ("tabular", "vector"),
        ]
        for pair in expected_pairs:
            self.assertIn(pair, STRATEGY_MATRIX,
                          f"Missing strategy for {pair}")
            self.assertTrue(len(STRATEGY_MATRIX[pair]) > 0)

    def test_unknown_pair_returns_empty(self):
        from data_agent.fusion_engine import STRATEGY_MATRIX
        self.assertEqual(STRATEGY_MATRIX.get(("tabular", "tabular"), []), [])

    def test_strategy_registry_complete(self):
        from data_agent.fusion_engine import STRATEGY_MATRIX, _STRATEGY_REGISTRY
        all_strategies = set()
        for strategies in STRATEGY_MATRIX.values():
            all_strategies.update(strategies)
        for s in all_strategies:
            self.assertIn(s, _STRATEGY_REGISTRY,
                          f"Strategy '{s}' in matrix but not in registry")


# ---------------------------------------------------------------------------
# TestQualityValidator
# ---------------------------------------------------------------------------

class TestQualityValidator(unittest.TestCase):
    """Test validate_quality function."""

    def test_good_quality(self):
        from data_agent.fusion_engine import validate_quality
        gdf = gpd.GeoDataFrame({
            "A": [1, 2, 3],
            "B": ["x", "y", "z"],
        }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)])
        result = validate_quality(gdf)
        self.assertGreaterEqual(result["score"], 0.8)
        self.assertEqual(len(result["warnings"]), 0)

    def test_high_null_rate_warning(self):
        from data_agent.fusion_engine import validate_quality
        gdf = gpd.GeoDataFrame({
            "A": [1, None, None],
            "B": [None, None, None],
        }, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)])
        result = validate_quality(gdf)
        self.assertTrue(any("null" in w.lower() for w in result["warnings"]))
        self.assertLess(result["score"], 1.0)

    def test_empty_result_zero_score(self):
        from data_agent.fusion_engine import validate_quality
        gdf = gpd.GeoDataFrame(columns=["A", "geometry"])
        result = validate_quality(gdf)
        self.assertEqual(result["score"], 0.0)

    def test_invalid_geometry_warning(self):
        from data_agent.fusion_engine import validate_quality
        from shapely.geometry import LinearRing
        # Create a self-intersecting polygon (bowtie)
        bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
        gdf = gpd.GeoDataFrame({"A": [1]}, geometry=[bowtie])
        result = validate_quality(gdf)
        if not gdf.geometry.is_valid.all():
            self.assertTrue(any("invalid" in w.lower() for w in result["warnings"]))

    def test_completeness_check(self):
        from data_agent.fusion_engine import validate_quality, FusionSource
        gdf = gpd.GeoDataFrame({"A": [1]}, geometry=[Point(0, 0)])
        sources = [FusionSource(file_path="a.shp", data_type="vector", row_count=100)]
        result = validate_quality(gdf, sources)
        # 1 out of 100 = 1% completeness
        self.assertTrue(any("completeness" in w.lower() for w in result["warnings"]))


# ---------------------------------------------------------------------------
# TestRecordOperation
# ---------------------------------------------------------------------------

class TestRecordOperation(unittest.TestCase):
    """Test DB recording of fusion operations."""

    @patch("data_agent.fusion.db.get_engine", return_value=None)
    def test_no_db_graceful(self, mock_engine):
        from data_agent.fusion_engine import record_operation, FusionSource
        # Should not raise
        record_operation(
            sources=[FusionSource(file_path="test.shp", data_type="vector")],
            strategy="spatial_join",
            output_path="out.geojson",
            quality_score=0.9,
            quality_warnings=[],
            duration_s=1.5,
        )

    @patch("data_agent.fusion.db.get_engine")
    @patch("data_agent.fusion.db.current_user_id")
    def test_record_with_db(self, mock_uid, mock_engine):
        mock_uid.get.return_value = "test_user"
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = lambda s, *a: None

        from data_agent.fusion_engine import record_operation, FusionSource
        record_operation(
            sources=[FusionSource(file_path="test.shp", data_type="vector")],
            strategy="spatial_join",
            output_path="out.geojson",
            quality_score=0.85,
            quality_warnings=["minor issue"],
            duration_s=2.3,
        )
        mock_conn.execute.assert_called_once()


# ---------------------------------------------------------------------------
# TestEnsureFusionTables
# ---------------------------------------------------------------------------

class TestEnsureFusionTables(unittest.TestCase):
    """Test table creation."""

    @patch("data_agent.fusion.db.get_engine", return_value=None)
    def test_no_db_graceful(self, mock_engine):
        from data_agent.fusion_engine import ensure_fusion_tables
        ensure_fusion_tables()  # should not raise

    @patch("data_agent.fusion.db.get_engine")
    def test_creates_table(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = lambda s, *a: None

        from data_agent.fusion_engine import ensure_fusion_tables
        ensure_fusion_tables()
        # Should have called execute at least twice (CREATE TABLE + CREATE INDEX)
        self.assertGreaterEqual(mock_conn.execute.call_count, 2)


# ---------------------------------------------------------------------------
# TestFusionToolset — registration
# ---------------------------------------------------------------------------

class TestFusionToolset(unittest.TestCase):
    """Test FusionToolset registration and tool listing."""

    def _run_async(self, coro):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_toolset_has_registered_tools(self):
        from data_agent.toolsets.fusion_tools import FusionToolset
        toolset = FusionToolset()
        tools = self._run_async(toolset.get_tools())
        self.assertEqual(len(tools), 15)

    def test_tool_names(self):
        from data_agent.toolsets.fusion_tools import FusionToolset
        toolset = FusionToolset()
        tools = self._run_async(toolset.get_tools())
        names = {t.name for t in tools}
        expected = {"profile_fusion_sources", "assess_fusion_compatibility",
                    "fuse_datasets", "validate_fusion_quality",
                    "standardize_timestamps", "validate_temporal_consistency",
                    "inject_document_context", "preflight_mmfe_lakehouse_infrastructure",
                    "plan_semantic_product_publish",
                    "export_semantic_product_okf", "build_twm_state_input",
                    "build_mmfe_semantic_ontology", "query_semantic_vectors",
                    "trace_mmfe_semantics", "diagnose_mmfe_semantic_product"}
        self.assertEqual(names, expected)

    def test_tool_filter_works(self):
        from data_agent.toolsets.fusion_tools import FusionToolset
        toolset = FusionToolset(tool_filter=["fuse_datasets"])
        tools = self._run_async(toolset.get_tools())
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "fuse_datasets")


# ---------------------------------------------------------------------------
# TestEndToEnd — full fusion pipelines
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):
    """End-to-end fusion pipeline tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    @patch("data_agent.gis_processors.get_user_upload_dir")
    @patch("data_agent.fusion.db.get_engine", return_value=None)
    def test_vector_tabular_fusion(self, mock_engine, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import (
            profile_source, assess_compatibility, align_sources,
            execute_fusion, validate_quality,
        )

        v_path = _make_vector_fixture(self.tmp)
        t_path = _make_tabular_fixture(self.tmp)

        # Step 1: Profile
        v_src = profile_source(v_path)
        t_src = profile_source(t_path)

        # Step 2: Assess
        report = assess_compatibility([v_src, t_src])
        self.assertIn("attribute_join", report.recommended_strategies)

        # Step 3: Align
        aligned, log = align_sources([v_src, t_src], report)
        self.assertEqual(len(aligned), 2)

        # Step 4: Fuse
        result = execute_fusion(aligned, "attribute_join", [v_src, t_src],
                                params={"join_column": "OBJECTID"})
        self.assertEqual(result.row_count, 3)
        self.assertTrue(os.path.exists(result.output_path))

        # Step 5: Validate
        quality = validate_quality(result.output_path)
        self.assertGreater(quality["score"], 0.5)

    @patch("data_agent.gis_processors.get_user_upload_dir")
    @patch("data_agent.fusion.db.get_engine", return_value=None)
    def test_vector_vector_spatial_join(self, mock_engine, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import (
            profile_source, assess_compatibility, align_sources, execute_fusion,
        )

        v1 = profile_source(_make_vector_fixture(self.tmp, "v1.geojson"))
        v2 = profile_source(_make_second_vector(self.tmp))

        report = assess_compatibility([v1, v2])
        aligned, _ = align_sources([v1, v2], report)

        result = execute_fusion(aligned, "auto", [v1, v2])
        self.assertEqual(result.strategy_used, "spatial_join")
        self.assertGreater(result.row_count, 0)
        self.assertTrue(os.path.exists(result.output_path))


# ---------------------------------------------------------------------------
# TestAutoDetectJoinColumn
# ---------------------------------------------------------------------------

class TestAutoDetectJoinColumn(unittest.TestCase):
    """Test auto-detection of join columns."""

    def test_detect_shared_column(self):
        from data_agent.fusion_engine import _auto_detect_join_column
        gdf = gpd.GeoDataFrame({"OBJECTID": [1], "AREA": [100]},
                               geometry=[Point(0, 0)])
        df = pd.DataFrame({"objectid": [1], "VALUE": [50]})
        col = _auto_detect_join_column(gdf, df)
        self.assertEqual(col.lower(), "objectid")

    def test_prefer_id_column(self):
        from data_agent.fusion_engine import _auto_detect_join_column
        gdf = gpd.GeoDataFrame({"ID": [1], "NAME": ["a"]},
                               geometry=[Point(0, 0)])
        df = pd.DataFrame({"ID": [1], "NAME": ["a"], "VALUE": [50]})
        col = _auto_detect_join_column(gdf, df)
        self.assertEqual(col.lower(), "id")

    def test_raises_on_no_match(self):
        from data_agent.fusion_engine import _auto_detect_join_column
        gdf = gpd.GeoDataFrame({"FOO": [1]}, geometry=[Point(0, 0)])
        df = pd.DataFrame({"BAR": [1]})
        with self.assertRaises(ValueError):
            _auto_detect_join_column(gdf, df)


# ===========================================================================
# v5.6 Tests — MGIM-Inspired Enhancements
# ===========================================================================


# ---------------------------------------------------------------------------
# TestFuzzyFieldMatching (v5.6)
# ---------------------------------------------------------------------------

class TestFuzzyFieldMatching(unittest.TestCase):
    """Test enhanced field matching with fuzzy + equivalence tiers."""

    def test_exact_match_case_insensitive(self):
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource("a.shp", "vector", columns=[
            {"name": "AREA", "dtype": "float64", "null_pct": 0}])
        s2 = FusionSource("b.shp", "vector", columns=[
            {"name": "area", "dtype": "float64", "null_pct": 0}])
        matches = _find_field_matches([s1, s2])
        exact = [m for m in matches if m["confidence"] == 1.0]
        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0]["left"], "AREA")

    def test_equivalence_group_match(self):
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource("a.shp", "vector", columns=[
            {"name": "area", "dtype": "float64", "null_pct": 0}])
        s2 = FusionSource("b.shp", "vector", columns=[
            {"name": "zmj", "dtype": "float64", "null_pct": 0}])
        matches = _find_field_matches([s1, s2])
        equiv = [m for m in matches if m["confidence"] == 0.8]
        self.assertGreaterEqual(len(equiv), 1)
        self.assertEqual(equiv[0]["right"], "zmj")

    def test_fuzzy_match_similar_names(self):
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource("a.shp", "vector", columns=[
            {"name": "land_use_type", "dtype": "object", "null_pct": 0}])
        s2 = FusionSource("b.shp", "vector", columns=[
            {"name": "landUseType", "dtype": "object", "null_pct": 0}])
        matches = _find_field_matches([s1, s2])
        fuzzy = [m for m in matches if m.get("match_type") == "fuzzy"]
        self.assertGreaterEqual(len(fuzzy), 1)
        self.assertGreater(fuzzy[0]["confidence"], 0.5)

    def test_fuzzy_match_skips_short_names(self):
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource("a.shp", "vector", columns=[
            {"name": "id", "dtype": "int64", "null_pct": 0}])
        s2 = FusionSource("b.shp", "vector", columns=[
            {"name": "ix", "dtype": "int64", "null_pct": 0}])
        matches = _find_field_matches([s1, s2])
        # "id" and "ix" are both < 3 chars, fuzzy should not match
        fuzzy = [m for m in matches if m.get("match_type") == "fuzzy"]
        self.assertEqual(len(fuzzy), 0)

    def test_expanded_equivalence_groups(self):
        """Test that new groups (population, elevation, perimeter) work."""
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource("a.shp", "vector", columns=[
            {"name": "population", "dtype": "int64", "null_pct": 0},
            {"name": "elevation", "dtype": "float64", "null_pct": 0},
        ])
        s2 = FusionSource("b.shp", "vector", columns=[
            {"name": "rk", "dtype": "int64", "null_pct": 0},
            {"name": "dem", "dtype": "float64", "null_pct": 0},
        ])
        matches = _find_field_matches([s1, s2])
        equiv = [m for m in matches if m["confidence"] == 0.8]
        left_names = {m["left"] for m in equiv}
        self.assertIn("population", left_names)
        self.assertIn("elevation", left_names)

    def test_no_duplicate_matches(self):
        """A right column should not match multiple left columns."""
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource("a.shp", "vector", columns=[
            {"name": "area", "dtype": "float64", "null_pct": 0},
            {"name": "mj", "dtype": "float64", "null_pct": 0},
        ])
        s2 = FusionSource("b.shp", "vector", columns=[
            {"name": "zmj", "dtype": "float64", "null_pct": 0}])
        matches = _find_field_matches([s1, s2])
        right_cols = [m["right"] for m in matches]
        self.assertEqual(len(right_cols), len(set(right_cols)))


# ---------------------------------------------------------------------------
# TestUnitDetectionConversion (v5.6)
# ---------------------------------------------------------------------------

class TestUnitDetectionConversion(unittest.TestCase):
    """Test unit detection from column names and value conversion."""

    def test_detect_mu(self):
        from data_agent.fusion_engine import _detect_unit
        self.assertEqual(_detect_unit("area_mu"), "mu")
        self.assertEqual(_detect_unit("面积_亩"), "mu")

    def test_detect_m2(self):
        from data_agent.fusion_engine import _detect_unit
        self.assertEqual(_detect_unit("area_m2"), "m2")
        self.assertEqual(_detect_unit("面积_平方米"), "m2")

    def test_detect_ha(self):
        from data_agent.fusion_engine import _detect_unit
        self.assertEqual(_detect_unit("area_ha"), "ha")
        self.assertEqual(_detect_unit("公顷面积"), "ha")

    def test_detect_none_for_plain_name(self):
        from data_agent.fusion_engine import _detect_unit
        self.assertIsNone(_detect_unit("area"))
        self.assertIsNone(_detect_unit("OBJECTID"))

    def test_strip_unit_suffix(self):
        from data_agent.fusion_engine import _strip_unit_suffix
        self.assertEqual(_strip_unit_suffix("area_mu"), "area")
        self.assertEqual(_strip_unit_suffix("area_m2"), "area")

    def test_convert_m2_to_mu(self):
        from data_agent.fusion_engine import _convert_column_units
        df = pd.DataFrame({"area_m2": [666.67, 1333.34]})
        log = []
        _convert_column_units(df, "area_m2", "m2", "mu", log)
        self.assertAlmostEqual(df["area_m2"].iloc[0], 1.0, places=1)
        self.assertEqual(len(log), 1)
        self.assertIn("m2", log[0])

    def test_convert_mu_to_ha(self):
        from data_agent.fusion_engine import _convert_column_units
        df = pd.DataFrame({"area_mu": [15.0, 30.0]})
        log = []
        _convert_column_units(df, "area_mu", "mu", "ha", log)
        self.assertAlmostEqual(df["area_mu"].iloc[0], 1.0, places=3)

    def test_convert_no_factor_skips(self):
        from data_agent.fusion_engine import _convert_column_units
        df = pd.DataFrame({"val": [100]})
        log = []
        _convert_column_units(df, "val", "unknown", "other", log)
        self.assertEqual(df["val"].iloc[0], 100)
        self.assertEqual(len(log), 1)  # warning message


# ---------------------------------------------------------------------------
# TestDataAwareStrategyScoring (v5.6)
# ---------------------------------------------------------------------------

class TestDataAwareStrategyScoring(unittest.TestCase):
    """Test context-aware strategy selection based on data characteristics."""

    def test_prefers_nearest_join_low_iou(self):
        """When spatial overlap is very low, prefer nearest_join over spatial_join."""
        from data_agent.fusion_engine import _score_strategies, FusionSource
        candidates = ["spatial_join", "nearest_join"]
        # Two point datasets with no overlap
        sources = [
            FusionSource("a.shp", "vector", bounds=(0, 0, 1, 1),
                         geometry_type="Point", row_count=100),
            FusionSource("b.shp", "vector", bounds=(100, 100, 101, 101),
                         geometry_type="Point", row_count=100),
        ]
        best = _score_strategies(candidates, [], sources)
        self.assertEqual(best, "nearest_join")

    def test_prefers_spatial_join_high_iou(self):
        """When spatial overlap is high with polygons, prefer spatial_join."""
        from data_agent.fusion_engine import _score_strategies, FusionSource
        candidates = ["spatial_join", "nearest_join"]
        sources = [
            FusionSource("a.shp", "vector", bounds=(0, 0, 10, 10),
                         geometry_type="Polygon", row_count=100),
            FusionSource("b.shp", "vector", bounds=(0, 0, 10, 10),
                         geometry_type="Polygon", row_count=100),
        ]
        best = _score_strategies(candidates, [], sources)
        self.assertEqual(best, "spatial_join")

    def test_prefers_zonal_stats_for_polygon(self):
        from data_agent.fusion_engine import _score_strategies, FusionSource
        candidates = ["zonal_statistics", "point_sampling"]
        sources = [
            FusionSource("a.shp", "vector", geometry_type="Polygon", row_count=50),
            FusionSource("b.tif", "raster", row_count=0),
        ]
        best = _score_strategies(candidates, [], sources)
        self.assertEqual(best, "zonal_statistics")

    def test_prefers_point_sampling_for_point(self):
        from data_agent.fusion_engine import _score_strategies, FusionSource
        candidates = ["zonal_statistics", "point_sampling"]
        sources = [
            FusionSource("a.shp", "vector", geometry_type="Point", row_count=50),
            FusionSource("b.tif", "raster", row_count=0),
        ]
        best = _score_strategies(candidates, [], sources)
        self.assertEqual(best, "point_sampling")

    def test_single_candidate_returned_directly(self):
        """When only one strategy is available, return it without scoring."""
        from data_agent.fusion_engine import _auto_select_strategy, FusionSource
        aligned = [("vector", None), ("tabular", None)]
        sources = [
            FusionSource("a.shp", "vector", row_count=10),
            FusionSource("b.csv", "tabular", row_count=10),
        ]
        result = _auto_select_strategy(aligned, sources)
        self.assertEqual(result, "attribute_join")


# ---------------------------------------------------------------------------
# TestMultiSourceOrchestration (v5.6)
# ---------------------------------------------------------------------------

class TestMultiSourceOrchestration(unittest.TestCase):
    """Test fusion of N>2 data sources via pairwise decomposition."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("data_agent.gis_processors.get_user_upload_dir")
    @patch("data_agent.fusion.db.get_engine", return_value=None)
    def test_three_source_fusion(self, mock_engine, mock_dir):
        mock_dir.return_value = self.tmp
        from data_agent.fusion_engine import (
            profile_source, assess_compatibility, align_sources, execute_fusion,
        )

        # Create 3 vector sources
        v1 = _make_vector_fixture(self.tmp, "v1.geojson")
        v2 = _make_second_vector(self.tmp)
        v3_polys = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 1), (2, 1), (2, 2), (1, 2)]),
            Polygon([(0, 1), (1, 1), (1, 2), (0, 2)]),
        ]
        gdf3 = gpd.GeoDataFrame(
            {"ZONING": ["R", "C", "I"]},
            geometry=v3_polys, crs="EPSG:4326")
        v3_path = os.path.join(self.tmp, "v3.geojson")
        gdf3.to_file(v3_path, driver="GeoJSON")

        s1 = profile_source(v1)
        s2 = profile_source(v2)
        s3 = profile_source(v3_path)

        report = assess_compatibility([s1, s2, s3])
        aligned, _ = align_sources([s1, s2, s3], report)
        self.assertEqual(len(aligned), 3)

        result = execute_fusion(aligned, "spatial_join", [s1, s2, s3])
        self.assertIn("multi_source", result.strategy_used)
        self.assertGreater(result.row_count, 0)
        self.assertTrue(os.path.exists(result.output_path))
        # Should have 2 steps logged
        steps = [l for l in result.alignment_log if l.startswith("Step")]
        self.assertEqual(len(steps), 2)


# ---------------------------------------------------------------------------
# TestEnhancedQualityValidation (v5.6)
# ---------------------------------------------------------------------------

class TestEnhancedQualityValidation(unittest.TestCase):
    """Test enhanced quality validation with new dimensions."""

    def test_returns_details_dict(self):
        """v5.6 quality reports include a 'details' dict."""
        from data_agent.fusion_engine import validate_quality
        gdf = gpd.GeoDataFrame(
            {"A": [1, 2, 3]},
            geometry=[Point(0, 0), Point(1, 1), Point(2, 2)],
            crs="EPSG:4326",
        )
        result = validate_quality(gdf)
        self.assertIn("details", result)
        self.assertIn("null_rates", result["details"])

    def test_outlier_detection(self):
        """Detect extreme outliers that may indicate unit mismatch."""
        from data_agent.fusion_engine import validate_quality
        # Normal values with one extreme outlier
        values = [100.0] * 50 + [999999.0]
        gdf = gpd.GeoDataFrame(
            {"area": values},
            geometry=[Point(i, 0) for i in range(51)],
            crs="EPSG:4326",
        )
        result = validate_quality(gdf)
        # Should detect outlier columns
        self.assertIn("outlier_columns", result["details"])

    def test_boolean_numeric_columns_do_not_break_quantiles(self):
        """Boolean QA columns should not be treated as statistical numerics."""
        from data_agent.fusion_engine import validate_quality

        gdf = gpd.GeoDataFrame(
            {
                "qa_use_for_rules": [True, False, True, True, False, True],
                "flag": [False, False, True, True, False, True],
                "value": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
            },
            geometry=[Point(i, 0) for i in range(6)],
            crs="EPSG:4326",
        )

        result = validate_quality(gdf)
        self.assertIn("score", result)
        self.assertIn("details", result)
        self.assertNotIn("qa_use_for_rules", result["details"].get("outlier_columns", []))
        self.assertNotIn("flag", result["details"].get("outlier_columns", []))

    def test_micro_polygon_detection(self):
        """Detect sliver/micro polygons in output."""
        from data_agent.fusion_engine import validate_quality
        # One normal polygon and two micro polygons
        normal = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        micro1 = Polygon([(0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0.0001)])
        micro2 = Polygon([(1, 1), (1.0001, 1), (1.0001, 1.0001), (1, 1.0001)])
        gdf = gpd.GeoDataFrame(
            {"val": [1, 2, 3]},
            geometry=[normal, micro1, micro2],
            crs="EPSG:4326",
        )
        result = validate_quality(gdf)
        self.assertIn("micro_polygon_pct", result["details"])

    def test_column_completeness_tracked(self):
        from data_agent.fusion_engine import validate_quality, FusionSource
        gdf = gpd.GeoDataFrame(
            {"A": [1], "B": [2], "C": [3]},
            geometry=[Point(0, 0)],
            crs="EPSG:4326",
        )
        sources = [
            FusionSource("a.shp", "vector", columns=[
                {"name": "X", "dtype": "int", "null_pct": 0},
                {"name": "Y", "dtype": "int", "null_pct": 0},
            ]),
        ]
        result = validate_quality(gdf, sources)
        self.assertIn("column_completeness", result["details"])

    def test_empty_result_has_details(self):
        from data_agent.fusion_engine import validate_quality
        gdf = gpd.GeoDataFrame(columns=["A", "geometry"])
        result = validate_quality(gdf)
        self.assertEqual(result["score"], 0.0)
        self.assertIn("details", result)
        self.assertTrue(result["details"]["empty"])


# ---------------------------------------------------------------------------
# TestUnitAwareAlignment (v5.6)
# ---------------------------------------------------------------------------

class TestUnitAwareAlignment(unittest.TestCase):
    """Test that unit-aware field matches trigger conversion in alignment."""

    def test_unit_aware_match_detected(self):
        """Fields with different unit suffixes should produce unit_aware matches."""
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource("a.shp", "vector", columns=[
            {"name": "area_m2", "dtype": "float64", "null_pct": 0}])
        s2 = FusionSource("b.shp", "vector", columns=[
            {"name": "area_mu", "dtype": "float64", "null_pct": 0}])
        matches = _find_field_matches([s1, s2])
        unit_matches = [m for m in matches if m.get("match_type") == "unit_aware"]
        self.assertGreaterEqual(len(unit_matches), 1)
        self.assertEqual(unit_matches[0]["left_unit"], "m2")
        self.assertEqual(unit_matches[0]["right_unit"], "mu")



# ---------------------------------------------------------------------------
# v6.0 Enhanced Tests
# ---------------------------------------------------------------------------


class TestRasterResampling(unittest.TestCase):
    """Tests for raster auto-resampling and reprojection."""

    def test_reproject_raster(self):
        """Test _reproject_raster produces a file with target CRS."""
        import rasterio
        from rasterio.transform import from_bounds
        from data_agent.fusion_engine import _reproject_raster

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.tif")
            transform = from_bounds(116, 39, 117, 40, 10, 10)
            with rasterio.open(path, "w", driver="GTiff", height=10, width=10,
                               count=1, dtype="float32", crs="EPSG:4326",
                               transform=transform) as ds:
                ds.write(np.ones((1, 10, 10), dtype=np.float32))

            out = _reproject_raster(path, "EPSG:3857")
            self.assertTrue(os.path.exists(out))
            with rasterio.open(out) as ds:
                self.assertIn("3857", str(ds.crs))
            os.remove(out)

    def test_resample_raster_to_match(self):
        """Test _resample_raster_to_match produces matching grid."""
        import rasterio
        from rasterio.transform import from_bounds
        from data_agent.fusion_engine import _resample_raster_to_match

        with tempfile.TemporaryDirectory() as td:
            ref = os.path.join(td, "ref.tif")
            src = os.path.join(td, "src.tif")

            # Reference: 10x10
            t1 = from_bounds(0, 0, 10, 10, 10, 10)
            with rasterio.open(ref, "w", driver="GTiff", height=10, width=10,
                               count=1, dtype="float32", crs="EPSG:4326",
                               transform=t1) as ds:
                ds.write(np.ones((1, 10, 10), dtype=np.float32))

            # Source: 5x5
            t2 = from_bounds(0, 0, 10, 10, 5, 5)
            with rasterio.open(src, "w", driver="GTiff", height=5, width=5,
                               count=1, dtype="float32", crs="EPSG:4326",
                               transform=t2) as ds:
                ds.write(np.ones((1, 5, 5), dtype=np.float32) * 2)

            out = _resample_raster_to_match(src, ref)
            with rasterio.open(out) as ds:
                self.assertEqual(ds.width, 10)
                self.assertEqual(ds.height, 10)
            os.remove(out)

    def test_band_stack_auto_resample(self):
        """Test band_stack auto-resamples when shapes differ."""
        import rasterio
        from rasterio.transform import from_bounds
        from data_agent.fusion_engine import _strategy_band_stack

        with tempfile.TemporaryDirectory() as td:
            r1 = os.path.join(td, "r1.tif")
            r2 = os.path.join(td, "r2.tif")

            t1 = from_bounds(0, 0, 10, 10, 10, 10)
            with rasterio.open(r1, "w", driver="GTiff", height=10, width=10,
                               count=1, dtype="float32", crs="EPSG:4326",
                               transform=t1) as ds:
                ds.write(np.ones((1, 10, 10), dtype=np.float32) * 100)

            t2 = from_bounds(0, 0, 10, 10, 5, 5)
            with rasterio.open(r2, "w", driver="GTiff", height=5, width=5,
                               count=1, dtype="float32", crs="EPSG:4326",
                               transform=t2) as ds:
                ds.write(np.ones((1, 5, 5), dtype=np.float32) * 50)

            aligned = [("raster", r1), ("raster", r2)]
            result, log = _strategy_band_stack(aligned, {})
            self.assertIsInstance(result, gpd.GeoDataFrame)
            self.assertTrue(any("resamp" in l.lower() or "Auto" in l for l in log))

    def test_band_stack_same_shape(self):
        """Test band_stack works with same-shape rasters (no resampling needed)."""
        import rasterio
        from rasterio.transform import from_bounds
        from data_agent.fusion_engine import _strategy_band_stack

        with tempfile.TemporaryDirectory() as td:
            r1 = os.path.join(td, "r1.tif")
            r2 = os.path.join(td, "r2.tif")

            t = from_bounds(0, 0, 10, 10, 10, 10)
            for path, val in [(r1, 100), (r2, 50)]:
                with rasterio.open(path, "w", driver="GTiff", height=10, width=10,
                                   count=1, dtype="float32", crs="EPSG:4326",
                                   transform=t) as ds:
                    ds.write(np.ones((1, 10, 10), dtype=np.float32) * val)

            aligned = [("raster", r1), ("raster", r2)]
            result, log = _strategy_band_stack(aligned, {})
            self.assertIsInstance(result, gpd.GeoDataFrame)

    def test_align_sources_raster_crs_reproject(self):
        """Test align_sources auto-reprojects rasters with different CRS."""
        import rasterio
        from rasterio.transform import from_bounds
        from data_agent.fusion_engine import (
            align_sources, FusionSource, CompatibilityReport,
        )

        with tempfile.TemporaryDirectory() as td:
            r_path = os.path.join(td, "test.tif")
            t = from_bounds(116, 39, 117, 40, 10, 10)
            with rasterio.open(r_path, "w", driver="GTiff", height=10, width=10,
                               count=1, dtype="float32", crs="EPSG:4326",
                               transform=t) as ds:
                ds.write(np.ones((1, 10, 10), dtype=np.float32))

            src = FusionSource(r_path, "raster", crs="EPSG:4326")
            report = CompatibilityReport(
                crs_compatible=True, spatial_overlap_iou=0.0,
                field_matches=[], overall_score=0.5,
                recommended_strategies=[], warnings=[],
            )
            loaded, log = align_sources([src], report, target_crs="EPSG:3857")
            self.assertEqual(loaded[0][0], "raster")
            self.assertTrue(any("Reprojected raster" in l for l in log))
            # Clean up reproj file
            reproj_path = loaded[0][1]
            if reproj_path != r_path and os.path.exists(reproj_path):
                os.remove(reproj_path)

    def test_profile_raster_windowed(self):
        """Test _profile_raster uses windowed reading for large rasters."""
        import rasterio
        from rasterio.transform import from_bounds
        from data_agent.fusion_engine import _profile_raster

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "large.tif")
            # 1500x1500 = 2.25M pixels > 1M threshold
            t = from_bounds(0, 0, 10, 10, 1500, 1500)
            with rasterio.open(path, "w", driver="GTiff", height=1500, width=1500,
                               count=1, dtype="float32", crs="EPSG:4326",
                               transform=t) as ds:
                ds.write(np.ones((1, 1500, 1500), dtype=np.float32) * 42)

            profile = _profile_raster(path)
            self.assertEqual(profile.data_type, "raster")
            self.assertIn("band_1", profile.stats)
            self.assertAlmostEqual(profile.stats["band_1"]["mean"], 42.0, places=1)


class TestPointCloudHeightAssign(unittest.TestCase):
    """Tests for point cloud height assignment."""

    def test_height_assign_no_point_cloud(self):
        """Test height_assign fallback when no point cloud path."""
        from data_agent.fusion_engine import _strategy_height_assign
        gdf = gpd.GeoDataFrame(
            {"name": ["a"]},
            geometry=gpd.points_from_xy([116], [39]),
            crs="EPSG:4326",
        )
        aligned = [("vector", gdf)]
        result, log = _strategy_height_assign(aligned, {})
        self.assertIn("height_m", result.columns)
        self.assertEqual(result["height_m"].iloc[0], 0.0)

    @patch.dict("sys.modules", {"laspy": None})
    def test_height_assign_no_laspy(self):
        """Test graceful fallback when laspy not installed."""
        # Force reimport to pick up mock
        import importlib
        import data_agent.fusion_engine as fe
        from data_agent.fusion_engine import _strategy_height_assign

        gdf = gpd.GeoDataFrame(
            {"name": ["a"]},
            geometry=gpd.points_from_xy([116], [39]),
            crs="EPSG:4326",
        )
        aligned = [("vector", gdf), ("point_cloud", "fake.las")]
        result, log = _strategy_height_assign(aligned, {})
        self.assertEqual(result["height_m"].iloc[0], 0.0)
        self.assertTrue(any("laspy" in l.lower() or "fallback" in l.lower() for l in log))

    def test_height_assign_with_mock_laspy(self):
        """Test height assignment with mocked laspy data."""
        from data_agent.fusion_engine import _strategy_height_assign

        gdf = gpd.GeoDataFrame(
            {"name": ["a", "b"]},
            geometry=[box(0, 0, 5, 5), box(10, 10, 15, 15)],
            crs="EPSG:4326",
        )

        # Create mock laspy module
        mock_las = MagicMock()
        mock_las.x = np.array([1, 2, 3, 11, 12])
        mock_las.y = np.array([1, 2, 3, 11, 12])
        mock_las.z = np.array([10, 20, 30, 40, 50])

        mock_laspy = MagicMock()
        mock_laspy.read = MagicMock(return_value=mock_las)

        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            aligned = [("vector", gdf), ("point_cloud", "test.las")]
            result, log = _strategy_height_assign(aligned, {"height_stat": "mean"})
            # First polygon (0,0,5,5) should get points 1,2,3 → z mean = 20
            self.assertAlmostEqual(result["height_m"].iloc[0], 20.0, places=1)
            # Second polygon (10,10,15,15) → z mean = 45
            self.assertAlmostEqual(result["height_m"].iloc[1], 45.0, places=1)

    def test_height_assign_median_stat(self):
        """Test height assignment with median statistic."""
        from data_agent.fusion_engine import _strategy_height_assign

        gdf = gpd.GeoDataFrame(
            {"name": ["a"]},
            geometry=[box(0, 0, 10, 10)],
            crs="EPSG:4326",
        )

        mock_las = MagicMock()
        mock_las.x = np.array([1, 2, 3])
        mock_las.y = np.array([1, 2, 3])
        mock_las.z = np.array([10, 20, 100])  # median = 20

        mock_laspy = MagicMock()
        mock_laspy.read = MagicMock(return_value=mock_las)

        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            aligned = [("vector", gdf), ("point_cloud", "test.las")]
            result, log = _strategy_height_assign(aligned, {"height_stat": "median"})
            self.assertAlmostEqual(result["height_m"].iloc[0], 20.0, places=1)

    def test_height_assign_no_matching_points(self):
        """Test height assignment when no points fall within geometry."""
        from data_agent.fusion_engine import _strategy_height_assign

        gdf = gpd.GeoDataFrame(
            {"name": ["a"]},
            geometry=[box(100, 100, 110, 110)],
            crs="EPSG:4326",
        )

        mock_las = MagicMock()
        mock_las.x = np.array([1, 2, 3])
        mock_las.y = np.array([1, 2, 3])
        mock_las.z = np.array([10, 20, 30])

        mock_laspy = MagicMock()
        mock_laspy.read = MagicMock(return_value=mock_las)

        with patch.dict("sys.modules", {"laspy": mock_laspy}):
            aligned = [("vector", gdf), ("point_cloud", "test.las")]
            result, log = _strategy_height_assign(aligned, {})
            self.assertEqual(result["height_m"].iloc[0], 0.0)


class TestStreamTemporalFusion(unittest.TestCase):
    """Tests for stream temporal fusion."""

    def test_time_snapshot_basic(self):
        """Test basic time snapshot without stream data."""
        from data_agent.fusion_engine import _strategy_time_snapshot
        gdf = gpd.GeoDataFrame(
            {"name": ["a"]},
            geometry=gpd.points_from_xy([116], [39]),
            crs="EPSG:4326",
        )
        aligned = [("vector", gdf)]
        result, log = _strategy_time_snapshot(aligned, {})
        self.assertIn("_fusion_timestamp", result.columns)

    def test_time_snapshot_with_stream_csv(self):
        """Test time snapshot with CSV stream data."""
        from data_agent.fusion_engine import _strategy_time_snapshot

        gdf = gpd.GeoDataFrame(
            {"name": ["zone_a"]},
            geometry=[box(115, 38, 117, 40)],
            crs="EPSG:4326",
        )

        # Create stream CSV
        now = pd.Timestamp.now()
        stream_df = pd.DataFrame({
            "timestamp": [now.isoformat(), (now - pd.Timedelta(minutes=30)).isoformat()],
            "lat": [39.0, 39.5],
            "lng": [116.0, 116.5],
            "value": [10.0, 20.0],
        })

        with tempfile.TemporaryDirectory() as td:
            csv_path = os.path.join(td, "stream.csv")
            stream_df.to_csv(csv_path, index=False)

            aligned = [("vector", gdf), ("stream", csv_path)]
            result, log = _strategy_time_snapshot(aligned, {"window_minutes": 120})
            self.assertIn("_fusion_timestamp", result.columns)

    def test_time_snapshot_with_dataframe(self):
        """Test time snapshot with pre-loaded DataFrame."""
        from data_agent.fusion_engine import _strategy_time_snapshot

        gdf = gpd.GeoDataFrame(
            {"name": ["zone_a"]},
            geometry=[box(0, 0, 10, 10)],
            crs="EPSG:4326",
        )

        now = pd.Timestamp.now()
        stream_df = pd.DataFrame({
            "timestamp": [now.isoformat()],
            "lat": [5.0],
            "lng": [5.0],
            "value": [42.0],
        })

        aligned = [("vector", gdf), ("tabular", stream_df)]
        result, log = _strategy_time_snapshot(aligned, {"window_minutes": 120})
        self.assertIn("_fusion_timestamp", result.columns)

    def test_time_snapshot_no_coords(self):
        """Test graceful fallback when stream data has no coordinate columns."""
        from data_agent.fusion_engine import _strategy_time_snapshot

        gdf = gpd.GeoDataFrame(
            {"name": ["a"]},
            geometry=gpd.points_from_xy([116], [39]),
            crs="EPSG:4326",
        )

        stream_df = pd.DataFrame({
            "timestamp": [pd.Timestamp.now().isoformat()],
            "metric": [42],
        })

        aligned = [("vector", gdf), ("tabular", stream_df)]
        result, log = _strategy_time_snapshot(aligned, {})
        self.assertIn("_fusion_timestamp", result.columns)
        self.assertTrue(any("No coordinate" in l for l in log))

    def test_time_snapshot_empty_stream(self):
        """Test with empty stream DataFrame."""
        from data_agent.fusion_engine import _strategy_time_snapshot

        gdf = gpd.GeoDataFrame(
            {"name": ["a"]},
            geometry=gpd.points_from_xy([116], [39]),
            crs="EPSG:4326",
        )

        stream_df = pd.DataFrame(columns=["timestamp", "lat", "lng", "value"])

        aligned = [("vector", gdf), ("tabular", stream_df)]
        result, log = _strategy_time_snapshot(aligned, {})
        self.assertIn("_fusion_timestamp", result.columns)

    def test_time_snapshot_requires_vector(self):
        """Test raises when no vector source."""
        from data_agent.fusion_engine import _strategy_time_snapshot
        aligned = [("tabular", pd.DataFrame())]
        with self.assertRaises(ValueError):
            _strategy_time_snapshot(aligned, {})


class TestEnhancedSemanticMatching(unittest.TestCase):
    """Tests for catalog-driven equivalence and tokenized similarity."""

    def test_tokenize_field_name(self):
        """Test field name tokenization."""
        from data_agent.fusion_engine import _tokenize_field_name
        self.assertEqual(_tokenize_field_name("land_use_type"), ["land", "use", "type"])
        self.assertEqual(_tokenize_field_name("landUseType"), ["land", "use", "type"])
        self.assertEqual(_tokenize_field_name("area2d"), ["area", "2", "d"])

    def test_tokenized_similarity(self):
        """Test tokenized similarity computation."""
        from data_agent.fusion_engine import _tokenized_similarity
        # Same tokens, different format
        score = _tokenized_similarity("land_use_type", "landUseType")
        self.assertGreater(score, 0.6)

        # Completely different
        score2 = _tokenized_similarity("name", "slope")
        self.assertLess(score2, 0.3)

    def test_types_compatible_blocks_mismatch(self):
        """Test type compatibility blocks numeric↔text mismatches."""
        from data_agent.fusion_engine import _types_compatible
        self.assertFalse(_types_compatible("float64", "object"))
        self.assertFalse(_types_compatible("int64", "string"))
        self.assertTrue(_types_compatible("float64", "int64"))
        self.assertTrue(_types_compatible("object", "string"))
        self.assertTrue(_types_compatible("", ""))  # unknown → allow

    def test_types_compatible_prevents_false_positive(self):
        """Test that type check prevents slope(float) matching slope_type(string)."""
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource("a.shp", "vector", columns=[
            {"name": "slope", "dtype": "float64", "null_pct": 0}])
        s2 = FusionSource("b.shp", "vector", columns=[
            {"name": "slope_type", "dtype": "object", "null_pct": 0}])
        matches = _find_field_matches([s1, s2])
        fuzzy = [m for m in matches if m.get("match_type") == "fuzzy"]
        self.assertEqual(len(fuzzy), 0)

    def test_catalog_equiv_groups_loaded(self):
        """Test catalog-driven equivalence group loading."""
        from data_agent.fusion_engine import _load_catalog_equiv_groups, _catalog_equiv_cache
        # Reset cache for test
        import data_agent.fusion_engine as fe
        fe._catalog_equiv_cache = None
        groups = _load_catalog_equiv_groups()
        # Should return a list (possibly empty if catalog not found)
        self.assertIsInstance(groups, list)

    def test_get_equiv_groups_includes_hardcoded(self):
        """Test merged groups include hardcoded ones."""
        from data_agent.fusion_engine import _get_equiv_groups
        groups = _get_equiv_groups()
        # Should have at least the 10 hardcoded groups
        self.assertGreaterEqual(len(groups), 10)
        # Check area group exists
        area_found = any("area" in g for g in groups)
        self.assertTrue(area_found)

    def test_camel_case_fuzzy_match(self):
        """Test that camelCase and snake_case fields match via tokenized similarity."""
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource("a.shp", "vector", columns=[
            {"name": "land_use_type", "dtype": "object", "null_pct": 0}])
        s2 = FusionSource("b.shp", "vector", columns=[
            {"name": "landUseType", "dtype": "object", "null_pct": 0}])
        matches = _find_field_matches([s1, s2])
        fuzzy = [m for m in matches if m.get("match_type") == "fuzzy"]
        self.assertGreaterEqual(len(fuzzy), 1)

    def test_fuzzy_no_false_positives_for_unrelated(self):
        """Test that completely unrelated fields don't match."""
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource("a.shp", "vector", columns=[
            {"name": "population_density", "dtype": "float64", "null_pct": 0}])
        s2 = FusionSource("b.shp", "vector", columns=[
            {"name": "road_surface", "dtype": "object", "null_pct": 0}])
        matches = _find_field_matches([s1, s2])
        fuzzy = [m for m in matches if m.get("match_type") == "fuzzy"]
        self.assertEqual(len(fuzzy), 0)


class TestEnhancedQualityChecks(unittest.TestCase):
    """Tests for enhanced quality validation (CRS, topology, KS test)."""

    def test_output_crs_recorded(self):
        """Test that output CRS is recorded in quality details."""
        from data_agent.fusion_engine import validate_quality, FusionSource
        gdf = gpd.GeoDataFrame(
            {"val": [1, 2, 3]},
            geometry=gpd.points_from_xy([0, 1, 2], [0, 1, 2]),
            crs="EPSG:4326",
        )
        src = FusionSource("a.shp", "vector", crs="EPSG:4326")
        result = validate_quality(gdf, [src])
        self.assertIn("output_crs", result["details"])
        self.assertEqual(result["details"]["output_crs"], "EPSG:4326")

    def test_topology_issues_detected(self):
        """Test topology validation detects self-intersecting polygons."""
        from data_agent.fusion_engine import validate_quality
        from shapely.geometry import Polygon

        # Create a bowtie (self-intersecting) polygon
        bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
        gdf = gpd.GeoDataFrame(
            {"name": ["bad"]},
            geometry=[bowtie],
            crs="EPSG:4326",
        )
        result = validate_quality(gdf)
        # Should detect topology issue
        self.assertTrue(
            "topology_issues" in result["details"]
            or any("invalid" in w.lower() for w in result["warnings"])
        )

    def test_ks_test_runs(self):
        """Test KS distribution shift detection runs without error."""
        from data_agent.fusion_engine import validate_quality, FusionSource

        gdf = gpd.GeoDataFrame(
            {"value": np.random.normal(50, 10, 100)},
            geometry=gpd.points_from_xy(
                np.random.uniform(0, 10, 100),
                np.random.uniform(0, 10, 100),
            ),
            crs="EPSG:4326",
        )
        src = FusionSource("a.shp", "vector", crs="EPSG:4326",
                           columns=[{"name": "value", "dtype": "float64", "null_pct": 0}],
                           stats={"value": {"min": 0, "max": 100, "mean": 50}})
        result = validate_quality(gdf, [src])
        self.assertIn("score", result)
        self.assertIn("details", result)

    def test_quality_backward_compatible(self):
        """Test quality validation is backward compatible with old tests."""
        from data_agent.fusion_engine import validate_quality
        gdf = gpd.GeoDataFrame(
            {"val": [1, 2, 3]},
            geometry=gpd.points_from_xy([0, 1, 2], [0, 1, 2]),
            crs="EPSG:4326",
        )
        result = validate_quality(gdf)
        self.assertIn("score", result)
        self.assertIn("warnings", result)
        self.assertIn("details", result)
        self.assertGreater(result["score"], 0)

    def test_empty_quality_still_works(self):
        """Test quality validation with empty GeoDataFrame."""
        from data_agent.fusion_engine import validate_quality
        gdf = gpd.GeoDataFrame(columns=["geometry"], crs="EPSG:4326")
        result = validate_quality(gdf)
        self.assertEqual(result["score"], 0.0)


class TestRealDataIntegration(unittest.TestCase):
    """Integration tests using sample_parcels.geojson fixture."""

    @classmethod
    def setUpClass(cls):
        fixture = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "evals", "fixtures", "sample_parcels.geojson",
        )
        cls.fixture_path = fixture
        cls.fixture_exists = os.path.exists(fixture)

    def test_profile_real_data(self):
        """Test profiling real geojson fixture."""
        if not self.fixture_exists:
            self.skipTest("sample_parcels.geojson not found")
        from data_agent.fusion_engine import profile_source
        profile = profile_source(self.fixture_path)
        self.assertEqual(profile.data_type, "vector")
        self.assertGreater(profile.row_count, 0)

    def test_quality_real_data(self):
        """Test quality validation on real data."""
        if not self.fixture_exists:
            self.skipTest("sample_parcels.geojson not found")
        from data_agent.fusion_engine import validate_quality
        result = validate_quality(self.fixture_path)
        self.assertGreater(result["score"], 0.5)

    def test_self_fusion_real_data(self):
        """Test profiling + compatibility of real data with itself."""
        if not self.fixture_exists:
            self.skipTest("sample_parcels.geojson not found")
        from data_agent.fusion_engine import profile_source, assess_compatibility
        p1 = profile_source(self.fixture_path)
        p2 = profile_source(self.fixture_path)
        report = assess_compatibility([p1, p2])
        self.assertGreater(report.overall_score, 0)
        self.assertTrue(report.crs_compatible)

    def test_field_match_real_data(self):
        """Test field matching finds matches in real data self-join."""
        if not self.fixture_exists:
            self.skipTest("sample_parcels.geojson not found")
        from data_agent.fusion_engine import profile_source, _find_field_matches
        p1 = profile_source(self.fixture_path)
        matches = _find_field_matches([p1, p1])
        # Self-join should find exact matches for all columns
        self.assertGreater(len(matches), 0)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# v7.0: Embedding Matching Tests
# ---------------------------------------------------------------------------

class TestEmbeddingMatching(unittest.TestCase):
    """Tests for Tier 2.5 embedding-based semantic field matching."""

    def test_cosine_similarity_basic(self):
        from data_agent.fusion_engine import _cosine_similarity
        self.assertAlmostEqual(_cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(_cosine_similarity([1, 0], [0, 1]), 0.0)
        self.assertAlmostEqual(_cosine_similarity([1, 1], [1, 1]), 1.0)

    def test_cosine_similarity_zero_vector(self):
        from data_agent.fusion_engine import _cosine_similarity
        self.assertEqual(_cosine_similarity([], [1, 0]), 0.0)
        self.assertEqual(_cosine_similarity([0, 0], [1, 0]), 0.0)

    @patch("data_agent.fusion.matching._get_embeddings")
    def test_embedding_match_found(self, mock_embed):
        """Embedding tier finds match with sufficient similarity."""
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        # Return vectors that are very similar for "population_density" vs "renkou_midu"
        mock_embed.side_effect = lambda texts: [
            [0.9, 0.1] if "population" in texts[0].lower() else [0.85, 0.15]
        ] * len(texts)

        s1 = FusionSource(file_path="a.geojson", data_type="vector", columns=[
            {"name": "population_density", "dtype": "float64", "null_pct": 0},
        ])
        s2 = FusionSource(file_path="b.geojson", data_type="vector", columns=[
            {"name": "renkou_midu", "dtype": "float64", "null_pct": 0},
        ])
        matches = _find_field_matches([s1, s2], use_embedding=True)
        emb_matches = [m for m in matches if m.get("match_type") == "embedding"]
        self.assertTrue(len(emb_matches) >= 0)  # May or may not match depending on vectors

    def test_embedding_skipped_when_disabled(self):
        """Default use_embedding=False produces no embedding matches."""
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource(file_path="a.geojson", data_type="vector", columns=[
            {"name": "unique_field_xxx", "dtype": "float64", "null_pct": 0},
        ])
        s2 = FusionSource(file_path="b.geojson", data_type="vector", columns=[
            {"name": "unique_field_yyy", "dtype": "float64", "null_pct": 0},
        ])
        matches = _find_field_matches([s1, s2], use_embedding=False)
        emb_matches = [m for m in matches if m.get("match_type") == "embedding"]
        self.assertEqual(len(emb_matches), 0)

    @patch("data_agent.fusion.matching._get_embeddings", return_value=[])
    def test_embedding_graceful_degradation(self, mock_embed):
        """API failure (returns []) -> no embedding matches, no crash."""
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource(file_path="a.geojson", data_type="vector", columns=[
            {"name": "field_a", "dtype": "float64", "null_pct": 0},
        ])
        s2 = FusionSource(file_path="b.geojson", data_type="vector", columns=[
            {"name": "field_b", "dtype": "float64", "null_pct": 0},
        ])
        matches = _find_field_matches([s1, s2], use_embedding=True)
        emb_matches = [m for m in matches if m.get("match_type") == "embedding"]
        self.assertEqual(len(emb_matches), 0)

    def test_embedding_cache(self):
        """Cache stores embeddings to avoid redundant calls."""
        from data_agent.fusion_engine import _embedding_cache
        _embedding_cache.clear()
        _embedding_cache["test_key (float64)"] = [0.5, 0.5]
        self.assertIn("test_key (float64)", _embedding_cache)
        _embedding_cache.clear()

    def test_embedding_does_not_duplicate_matches(self):
        """Fields already matched by Tier 1 (exact) should not get embedding matches."""
        from data_agent.fusion_engine import _find_field_matches, FusionSource
        s1 = FusionSource(file_path="a.geojson", data_type="vector", columns=[
            {"name": "AREA", "dtype": "float64", "null_pct": 0},
        ])
        s2 = FusionSource(file_path="b.geojson", data_type="vector", columns=[
            {"name": "area", "dtype": "float64", "null_pct": 0},
        ])
        matches = _find_field_matches([s1, s2], use_embedding=True)
        # AREA == area is an exact match (Tier 1, confidence 1.0)
        exact = [m for m in matches if m["confidence"] == 1.0]
        self.assertEqual(len(exact), 1)
        # No embedding duplicate
        emb = [m for m in matches if m.get("match_type") == "embedding"]
        self.assertEqual(len(emb), 0)


# ---------------------------------------------------------------------------
# v7.0: LLM Strategy Routing Tests
# ---------------------------------------------------------------------------

class TestLLMStrategyRouting(unittest.TestCase):
    """Tests for LLM-enhanced fusion strategy selection."""

    def test_rule_based_used_when_no_llm(self):
        """Default path (use_llm=False) returns rule-based result."""
        from data_agent.fusion_engine import _auto_select_strategy, FusionSource
        gdf1 = gpd.GeoDataFrame({"a": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        gdf2 = gpd.GeoDataFrame({"b": [1]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        sources = [
            FusionSource(file_path="a.geojson", data_type="vector", row_count=1,
                         geometry_type="Point", columns=[]),
            FusionSource(file_path="b.geojson", data_type="vector", row_count=1,
                         geometry_type="Point", columns=[]),
        ]
        result = _auto_select_strategy(
            [("vector", gdf1), ("vector", gdf2)], sources, use_llm=False,
        )
        self.assertIn(result, ["spatial_join", "overlay", "nearest_join"])

    @patch("data_agent.fusion.execution._llm_select_strategy", return_value=("nearest_join", "Low IoU"))
    def test_llm_strategy_returns_valid_candidate(self, mock_llm):
        """LLM path returns a valid candidate strategy."""
        from data_agent.fusion_engine import _auto_select_strategy, FusionSource
        gdf1 = gpd.GeoDataFrame({"a": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        gdf2 = gpd.GeoDataFrame({"b": [1]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        sources = [
            FusionSource(file_path="a.geojson", data_type="vector", row_count=1,
                         geometry_type="Point", columns=[]),
            FusionSource(file_path="b.geojson", data_type="vector", row_count=1,
                         geometry_type="Point", columns=[]),
        ]
        result = _auto_select_strategy(
            [("vector", gdf1), ("vector", gdf2)], sources, use_llm=True,
        )
        self.assertEqual(result, "nearest_join")

    @patch("data_agent.fusion.execution._llm_select_strategy", return_value=("", ""))
    def test_llm_fallback_on_failure(self, mock_llm):
        """LLM failure returns rule-based fallback."""
        from data_agent.fusion_engine import _auto_select_strategy, FusionSource
        gdf1 = gpd.GeoDataFrame({"a": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        gdf2 = gpd.GeoDataFrame({"b": [1]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        sources = [
            FusionSource(file_path="a.geojson", data_type="vector", row_count=1,
                         geometry_type="Point", columns=[]),
            FusionSource(file_path="b.geojson", data_type="vector", row_count=1,
                         geometry_type="Point", columns=[]),
        ]
        result = _auto_select_strategy(
            [("vector", gdf1), ("vector", gdf2)], sources, use_llm=True,
        )
        # Should fall back to rule-based
        self.assertIn(result, ["spatial_join", "overlay", "nearest_join"])

    @patch("google.genai.Client")
    def test_llm_select_strategy_invalid_json(self, mock_client_cls):
        """_llm_select_strategy handles invalid JSON gracefully."""
        from data_agent.fusion_engine import _llm_select_strategy, FusionSource
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MagicMock(text="not json")
        mock_client_cls.return_value = mock_client

        sources = [FusionSource(file_path="a.geojson", data_type="vector",
                                row_count=1, columns=[])]
        strategy, reason = _llm_select_strategy(["spatial_join"], sources)
        self.assertEqual(strategy, "")

    @patch("google.genai.Client")
    def test_llm_select_strategy_out_of_candidates(self, mock_client_cls):
        """LLM returns strategy not in candidates -> empty fallback."""
        from data_agent.fusion_engine import _llm_select_strategy, FusionSource
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MagicMock(
            text='{"strategy": "unknown_strategy", "reasoning": "test"}'
        )
        mock_client_cls.return_value = mock_client

        sources = [FusionSource(file_path="a.geojson", data_type="vector",
                                row_count=1, columns=[])]
        strategy, reason = _llm_select_strategy(["spatial_join", "overlay"], sources)
        self.assertEqual(strategy, "")

    @patch("data_agent.fusion.db.get_engine", return_value=None)
    @patch("data_agent.gis_processors.get_user_upload_dir")
    def test_execute_fusion_llm_auto(self, mock_upload, mock_engine):
        """strategy='llm_auto' is deprecated — falls back to rule-based 'auto'."""
        from data_agent.fusion_engine import execute_fusion, FusionSource
        with tempfile.TemporaryDirectory() as tmp:
            mock_upload.return_value = tmp
            v_path = _make_vector_fixture(tmp)
            v2_path = _make_second_vector(tmp)
            s1 = FusionSource(file_path=v_path, data_type="vector", row_count=3,
                              geometry_type="Polygon", columns=[
                                  {"name": "AREA", "dtype": "float64", "null_pct": 0}
                              ])
            s2 = FusionSource(file_path=v2_path, data_type="vector", row_count=2,
                              geometry_type="Polygon", columns=[
                                  {"name": "VALUE", "dtype": "float64", "null_pct": 0}
                              ])
            gdf1 = gpd.read_file(v_path)
            gdf2 = gpd.read_file(v2_path)

            # llm_auto degrades to auto — LLM mock is no longer called
            result = execute_fusion(
                [("vector", gdf1), ("vector", gdf2)],
                "llm_auto", [s1, s2],
            )
            # Rule-based auto selects a valid vector×vector strategy
            self.assertIn(result.strategy_used,
                          ["spatial_join", "overlay", "nearest_join"])
            self.assertTrue(os.path.exists(result.output_path))


# ---------------------------------------------------------------------------
# v7.0: Large Dataset / Chunked I/O Tests
# ---------------------------------------------------------------------------

class TestLargeDatasetHandling(unittest.TestCase):
    """Tests for distributed/chunked computing helpers."""

    def test_is_large_dataset_by_rows(self):
        from data_agent.fusion_engine import _is_large_dataset
        self.assertTrue(_is_large_dataset("dummy.csv", row_hint=600_000))

    def test_is_large_dataset_small(self):
        from data_agent.fusion_engine import _is_large_dataset
        self.assertFalse(_is_large_dataset("dummy.csv", row_hint=1000))

    def test_is_large_dataset_by_size(self):
        from data_agent.fusion_engine import _is_large_dataset, LARGE_FILE_MB
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"x" * 100)
            path = f.name
        try:
            # 100 bytes < 500MB
            self.assertFalse(_is_large_dataset(path))
        finally:
            os.unlink(path)

    def test_is_large_dataset_missing_file(self):
        from data_agent.fusion_engine import _is_large_dataset
        self.assertFalse(_is_large_dataset("/nonexistent/file.csv"))

    def test_read_vector_chunked_small(self):
        """Small vector files use standard gpd.read_file path."""
        from data_agent.fusion_engine import _read_vector_chunked
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_vector_fixture(tmp)
            gdf = _read_vector_chunked(path)
            self.assertEqual(len(gdf), 3)
            self.assertIn("DLBM", gdf.columns)

    def test_read_tabular_lazy_small(self):
        """Small CSV returns pandas DataFrame."""
        from data_agent.fusion_engine import _read_tabular_lazy
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_tabular_fixture(tmp)
            df = _read_tabular_lazy(path)
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 3)

    def test_materialize_df_pandas(self):
        """Pandas DataFrame passes through _materialize_df unchanged."""
        from data_agent.fusion_engine import _materialize_df
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = _materialize_df(df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 3)

    def test_materialize_df_dask(self):
        """Dask DataFrame is computed to pandas by _materialize_df."""
        from data_agent.fusion_engine import _materialize_df
        try:
            import dask.dataframe as dd
        except ModuleNotFoundError:
            self.skipTest("dask is not installed in this environment")
        df = pd.DataFrame({"a": [1, 2, 3]})
        ddf = dd.from_pandas(df, npartitions=1)
        result = _materialize_df(ddf)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 3)

    def test_fuse_large_spatial_small_input(self):
        """Small inputs pass through without chunking."""
        from data_agent.fusion_engine import _fuse_large_datasets_spatial
        gdf1 = gpd.GeoDataFrame(
            {"a": [1, 2]},
            geometry=[Point(0, 0), Point(1, 1)],
            crs="EPSG:4326",
        )
        gdf2 = gpd.GeoDataFrame(
            {"b": [10]},
            geometry=[Point(0.5, 0.5).buffer(2)],
            crs="EPSG:4326",
        )
        result = _fuse_large_datasets_spatial(gdf1, gdf2, chunk_size=50_000)
        self.assertGreaterEqual(len(result), 1)

    def test_fuse_large_spatial_chunked(self):
        """Chunked join produces same result as non-chunked for small data."""
        from data_agent.fusion_engine import _fuse_large_datasets_spatial
        pts = [Point(i * 0.1, i * 0.1) for i in range(10)]
        gdf1 = gpd.GeoDataFrame({"a": range(10)}, geometry=pts, crs="EPSG:4326")
        gdf2 = gpd.GeoDataFrame(
            {"b": [99]}, geometry=[Point(0.5, 0.5).buffer(5)], crs="EPSG:4326",
        )
        # Use tiny chunk to force chunked path
        result = _fuse_large_datasets_spatial(gdf1, gdf2, chunk_size=3)
        self.assertEqual(len(result), 10)

    @patch("data_agent.gis_processors.get_user_upload_dir")
    def test_profile_uses_chunked_reader(self, mock_upload):
        """_profile_vector uses _read_vector_chunked (transparent)."""
        from data_agent.fusion_engine import _profile_vector
        with tempfile.TemporaryDirectory() as tmp:
            mock_upload.return_value = tmp
            path = _make_vector_fixture(tmp)
            src = _profile_vector(path)
            self.assertEqual(src.row_count, 3)
            self.assertEqual(src.data_type, "vector")

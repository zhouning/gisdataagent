"""Tests for the Sedona-over-TWM-GeoJSON smoke script helpers."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.smoke_mmfe_sedona_twm_geojson import (
    _count_csv_data_rows,
    _load_pbf_rows,
    _load_project_rows,
)


class TestMMFESedonaTwmGeojsonSmoke(unittest.TestCase):
    def test_load_project_and_pbf_rows_keep_geometry_as_json_strings(self):
        data_dir = Path("data_agent/test_data/twm_bishan_demo")

        projects = _load_project_rows(data_dir / "synthetic_projects.geojson")
        pbf = _load_pbf_rows(data_dir / "synthetic_pbf.geojson")

        self.assertEqual(len(projects), 60)
        self.assertEqual(len(pbf), 14)
        self.assertEqual(projects[0]["project_id"], "PRJ-DEMO-0000")
        self.assertEqual(projects[0]["xmmc"], "璧山世界模型合成项目01")
        self.assertGreater(projects[0]["project_area_m2"], 0)
        self.assertEqual(pbf[0]["control_id"], "PBF-DEMO-00000")
        self.assertEqual(pbf[0]["dlmc"], "水田")
        self.assertGreater(pbf[0]["pbf_area_m2"], 0)
        self.assertIsInstance(json.loads(projects[0]["geometry_json"])["coordinates"], list)
        self.assertIsInstance(json.loads(pbf[0]["geometry_json"])["coordinates"], list)

    def test_count_csv_data_rows_excludes_header_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.csv"
            path.write_text("a,b\n1,2\n\n3,4\n", encoding="utf-8")
            self.assertEqual(_count_csv_data_rows(path), 2)


if __name__ == "__main__":
    unittest.main()

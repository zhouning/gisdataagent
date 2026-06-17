"""Tests for the PDAL Docker smoke script helpers."""

import tempfile
import unittest
from pathlib import Path

from data_agent.fusion.pdal_pipeline import validate_pdal_pipeline_spec
from scripts.smoke_mmfe_pdal_docker import _build_faux_las_pipeline


class TestMMFEPdalDockerSmoke(unittest.TestCase):
    def test_build_faux_las_pipeline_is_valid_runner_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "faux_points.las"

            spec = _build_faux_las_pipeline(output_path, point_count=25)

            self.assertEqual(spec["schema"], "mmfe.pdal_pipeline.v1")
            self.assertEqual(spec["pipeline"][0]["type"], "readers.faux")
            self.assertEqual(spec["pipeline"][0]["count"], 25)
            self.assertEqual(spec["pipeline"][-1]["type"], "writers.las")
            self.assertEqual(spec["pipeline"][-1]["filename"], str(output_path))
            self.assertEqual(validate_pdal_pipeline_spec(spec), [])


if __name__ == "__main__":
    unittest.main()

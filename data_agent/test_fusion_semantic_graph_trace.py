"""Tests for MMFE semantic graph trace cards."""

import json
import unittest
from pathlib import Path


GRAPH_PATH = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_graph.json")


class TestFusionSemanticGraphTrace(unittest.TestCase):
    def test_field_trace_reaches_value_domain_and_official_standard_source(self):
        from data_agent.fusion.semantic_graph_trace import (
            SEMANTIC_GRAPH_TRACE_SCHEMA,
            build_semantic_trace_card_bundle,
            trace_semantic_graph_node,
        )

        graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
        trace = trace_semantic_graph_node(graph, "field:parcel_current.DLBM")

        value_domain_targets = {
            path["nodes"][-1]["id"]
            for path in trace["value_domain_paths"]
        }
        standard_source_targets = {
            path["nodes"][-1]["id"]
            for path in trace["standard_source_paths"]
        }

        self.assertEqual(trace["node"]["label"], "地类编码")
        self.assertIn("value_domain:gb_t_21010_2017_land_use_code", value_domain_targets)
        self.assertIn("standard_source:gb-t-21010-2017", standard_source_targets)
        self.assertTrue(
            any(
                "uses_value_domain" in path["relationships"]
                and "grounded_by_standard_source" in path["relationships"]
                for path in trace["standard_source_paths"]
            )
        )

        bundle = build_semantic_trace_card_bundle(
            graph,
            ["field:parcel_current.DLBM", "value_domain:gb_t_21010_2017_land_use_code"],
            timestamp="2026-06-17T00:00:00+00:00",
        )
        self.assertEqual(bundle["schema"], SEMANTIC_GRAPH_TRACE_SCHEMA)
        self.assertEqual(bundle["trace_card_count"], 2)
        self.assertGreaterEqual(bundle["standard_source_path_count"], 2)

    def test_missing_node_raises_key_error(self):
        from data_agent.fusion.semantic_graph_trace import trace_semantic_graph_node

        graph = {"nodes": [], "edges": []}
        with self.assertRaises(KeyError):
            trace_semantic_graph_node(graph, "field:missing")

    def test_trace_api_is_exported_through_fusion_engine_proxy(self):
        from data_agent import fusion_engine

        self.assertEqual(fusion_engine.SEMANTIC_GRAPH_TRACE_SCHEMA, "mmfe.semantic_graph_trace.v1")


if __name__ == "__main__":
    unittest.main()

"""Tests for reusable MMFE semantic alignment scoring."""

import unittest


class TestSemanticAlignmentScoring(unittest.TestCase):
    def test_scores_accept_review_and_reject_decisions(self):
        from data_agent.fusion.semantic_alignment import score_semantic_alignment

        accepted = score_semantic_alignment(
            confidence=0.85,
            match_type="ontology",
            evidence=[
                {"type": "ontology", "detail": "same ontology group: area"},
                {"type": "dtype", "detail": "float64 -> float64", "compatible": True},
                {"type": "value_profile", "detail": "source statistics available"},
            ],
        )
        self.assertEqual(accepted["decision"], "accept")
        self.assertGreaterEqual(accepted["score"], 0.85)

        review = score_semantic_alignment(
            confidence=0.7,
            match_type="fuzzy",
            evidence=[
                {"type": "dtype", "detail": "object -> object", "compatible": True},
            ],
        )
        self.assertEqual(review["decision"], "review")

        rejected = score_semantic_alignment(
            confidence=0.55,
            match_type="fuzzy",
            evidence=[
                {"type": "dtype", "detail": "object -> float64", "compatible": False},
            ],
        )
        self.assertEqual(rejected["decision"], "reject")

    def test_build_alignment_summary_counts_unknown_decisions_as_review(self):
        from data_agent.fusion.semantic_alignment import build_alignment_summary

        summary = build_alignment_summary([
            {"alignment_score": {"decision": "accept"}},
            {"alignment_score": {"decision": "reject"}},
            {"alignment_score": {"decision": "needs_human"}},
            {},
        ])

        self.assertEqual(summary["total_mappings"], 4)
        self.assertEqual(summary["decisions"]["accept"], 1)
        self.assertEqual(summary["decisions"]["review"], 2)
        self.assertEqual(summary["decisions"]["reject"], 1)

    def test_document_context_evidence_can_promote_alignment_decision(self):
        from data_agent.fusion.semantic_alignment import score_semantic_alignment

        base_evidence = [
            {"type": "dtype", "detail": "object -> object", "compatible": True},
        ]
        base = score_semantic_alignment(
            confidence=0.72,
            match_type="fuzzy",
            evidence=base_evidence,
        )
        with_context = score_semantic_alignment(
            confidence=0.72,
            match_type="fuzzy",
            evidence=base_evidence + [
                {
                    "type": "document_context",
                    "detail": "data dictionary defines DLBM as land_use_code",
                    "support": 1.0,
                }
            ],
        )

        self.assertEqual(base["decision"], "review")
        self.assertEqual(with_context["decision"], "accept")
        self.assertGreater(with_context["score"], base["score"])
        self.assertEqual(with_context["components"]["document_context_support"], 1.0)

    def test_build_alignment_review_items_for_non_accepted_mappings(self):
        from data_agent.fusion.semantic_alignment import build_alignment_review_items

        review_items = build_alignment_review_items([
            {
                "source_field": "闈㈢Н",
                "target_field": "AREA",
                "confidence": 0.85,
                "match_type": "ontology",
                "alignment_score": {"score": 0.91, "decision": "accept"},
                "evidence": [{"type": "ontology", "detail": "same ontology group: area"}],
            },
            {
                "source_field": "DLBM",
                "target_field": "land_use_code",
                "confidence": 0.72,
                "match_type": "fuzzy",
                "alignment_score": {
                    "score": 0.74,
                    "decision": "review",
                    "components": {
                        "matcher_confidence": 0.72,
                        "dtype_compatibility": 1.0,
                        "document_context_support": 0.0,
                    },
                },
                "evidence": [{"type": "dtype", "detail": "object -> object"}],
            },
            {
                "source_field": "DLBM",
                "target_field": "AREA",
                "confidence": 0.55,
                "match_type": "fuzzy",
                "alignment_score": {
                    "score": 0.4575,
                    "decision": "reject",
                    "components": {
                        "matcher_confidence": 0.55,
                        "dtype_compatibility": 0.0,
                        "document_context_support": 0.0,
                    },
                },
                "evidence": [
                    {
                        "type": "dtype",
                        "detail": "object -> float64",
                        "compatible": False,
                    }
                ],
            },
        ])

        self.assertEqual(len(review_items), 2)
        self.assertEqual(review_items[0]["review_id"], "alignment-review:1")
        self.assertEqual(review_items[0]["severity"], "medium")
        self.assertIn("missing_document_context", review_items[0]["reason_codes"])
        self.assertEqual(review_items[0]["suggested_action"], "verify_with_domain_dictionary")

        self.assertEqual(review_items[1]["severity"], "high")
        self.assertIn("dtype_conflict", review_items[1]["reason_codes"])
        self.assertEqual(review_items[1]["suggested_action"], "remove_or_remap_field_alignment")

    def test_standard_contract_alignment_accepts_twm_bound_field(self):
        from data_agent.fusion.semantic_alignment import align_layer_fields_to_standard_contract

        role_contracts = {
            "standard_id": "NR_ONE_MAP_TWM_CORE_2026",
            "version": "2026-06-16-draft",
            "roles": {
                "project": {
                    "role_alias_zh": "建设项目空间范围",
                    "required_fields": ["XMDM", "XMMC", "YDMJ"],
                    "recommended_fields": ["ZYGDMJ"],
                    "field_rules": {
                        "YDMJ": {"type": "number", "min_exclusive": 0, "unit": "m2"}
                    },
                    "twm_binding": {
                        "object_id": "XMDM",
                        "project_name": "XMMC",
                        "area_m2": "YDMJ",
                    },
                }
            },
        }
        field_aliases = {"YDMJ": "用地面积", "XMDM": "项目代码"}
        standard_fields = [
            {"field_name": "YDMJ", "field_alias_zh": "用地面积", "lifecycle_status": "active"},
            {"field_name": "XMDM", "field_alias_zh": "项目代码", "lifecycle_status": "active"},
        ]

        rows = align_layer_fields_to_standard_contract(
            ["YDMJ"],
            "project",
            role_contracts,
            field_aliases=field_aliases,
            standard_fields=standard_fields,
            layer_role="synthetic_projects",
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["standard_field"], "YDMJ")
        self.assertEqual(row["contract_requirement"], "required")
        self.assertEqual(row["twm_semantic_key"], "area_m2")
        self.assertEqual(row["alignment_decision"], "accept")
        self.assertFalse(row["requires_review"])
        self.assertIn("role_contract", {item["type"] for item in row["evidence"]})
        self.assertIn("twm_binding", {item["type"] for item in row["evidence"]})

    def test_standard_catalog_only_alignment_requires_review(self):
        from data_agent.fusion.semantic_alignment import (
            align_layer_fields_to_standard_contract,
            build_standard_alignment_summary,
        )

        rows = align_layer_fields_to_standard_contract(
            ["raster_uri"],
            "remote_sensing_evidence",
            {"roles": {}},
            field_aliases={"raster_uri": "栅格资源地址"},
            standard_fields=[
                {
                    "field_name": "raster_uri",
                    "field_alias_zh": "栅格资源地址",
                    "lifecycle_status": "active",
                }
            ],
            layer_role="synthetic_remote_sensing_tiles",
        )

        self.assertEqual(rows[0]["match_type"], "standard_field_catalog")
        self.assertEqual(rows[0]["contract_requirement"], "observed")
        self.assertEqual(rows[0]["alignment_decision"], "review")
        self.assertTrue(rows[0]["requires_review"])

        summary = build_standard_alignment_summary(rows)
        self.assertEqual(summary["decisions"]["review"], 1)
        self.assertEqual(summary["review_required"], 1)

    def test_missing_value_domain_is_reported_without_rejecting_field_binding(self):
        from data_agent.fusion.semantic_alignment import (
            align_layer_fields_to_standard_contract,
            build_standard_alignment_summary,
        )

        rows = align_layer_fields_to_standard_contract(
            ["DLBM"],
            "parcel_current",
            {
                "roles": {
                    "parcel_current": {
                        "required_fields": ["DLBM"],
                        "field_rules": {
                            "DLBM": {"domain": "gb_t_21010_2017_land_use_code"}
                        },
                        "twm_binding": {"land_use_code": "DLBM"},
                    }
                }
            },
            field_aliases={"DLBM": "地类编码"},
            standard_fields=[{"field_name": "DLBM", "field_alias_zh": "地类编码"}],
            value_domains={"yes_no_code": [{"code": "1"}]},
        )

        self.assertEqual(rows[0]["alignment_decision"], "accept")
        self.assertEqual(rows[0]["value_domain_status"], "referenced_missing_items")
        summary = build_standard_alignment_summary(rows)
        self.assertEqual(
            summary["missing_value_domains"],
            {"gb_t_21010_2017_land_use_code": 1},
        )

    def test_loaded_value_domain_and_observed_values_can_be_audited(self):
        from data_agent.fusion.semantic_alignment import (
            align_layer_fields_to_standard_contract,
            audit_field_value_domain,
            build_standard_alignment_summary,
            build_value_domain_audit_summary,
            build_value_domain_catalog,
        )

        value_domains = {
            "domains": {
                "gb_t_21010_2017_land_use_code": [
                    {"code": "0101", "name_zh": "水田"},
                    {"code": "0103", "name_zh": "旱地"},
                    {"code": "0301", "name_zh": "乔木林地"},
                ]
            }
        }
        rows = align_layer_fields_to_standard_contract(
            ["DLBM"],
            "parcel_current",
            {
                "roles": {
                    "parcel_current": {
                        "required_fields": ["DLBM"],
                        "field_rules": {
                            "DLBM": {"domain": "gb_t_21010_2017_land_use_code"}
                        },
                        "twm_binding": {"land_use_code": "DLBM"},
                    }
                }
            },
            field_aliases={"DLBM": "地类编码"},
            standard_fields=[{"field_name": "DLBM", "field_alias_zh": "地类编码"}],
            value_domains=value_domains,
        )

        self.assertEqual(rows[0]["value_domain_status"], "loaded")
        summary = build_standard_alignment_summary(rows)
        self.assertEqual(summary["missing_value_domains"], {})
        self.assertEqual(summary["loaded_value_domains"], {"gb_t_21010_2017_land_use_code": 1})

        catalog = build_value_domain_catalog(value_domains)
        self.assertEqual(catalog["gb_t_21010_2017_land_use_code"]["item_count"], 3)

        audit = audit_field_value_domain(
            ["0101", "0103", "0301", "9999", None, "0101"],
            "gb_t_21010_2017_land_use_code",
            value_domains,
            layer_role="parcel_current",
            field_name="DLBM",
        )

        self.assertEqual(audit["audit_status"], "has_unknown_values")
        self.assertEqual(audit["domain_status"], "loaded")
        self.assertEqual(audit["valid_count"], 4)
        self.assertEqual(audit["unknown_count"], 1)
        self.assertEqual(audit["coverage"], 0.8)
        self.assertEqual(audit["unknown_values"], [{"code": "9999", "count": 1}])

        audit_summary = build_value_domain_audit_summary([audit])
        self.assertEqual(audit_summary["audit_count"], 1)
        self.assertEqual(audit_summary["status_distribution"]["has_unknown_values"], 1)
        self.assertEqual(audit_summary["requires_review_count"], 1)

    def test_value_domain_api_is_exported_through_fusion_engine_proxy(self):
        from data_agent import fusion_engine

        audit = fusion_engine.audit_field_value_domain(
            ["1", "0"],
            "yes_no_code",
            {"domains": {"yes_no_code": [{"code": "1"}, {"code": "0"}]}},
        )

        self.assertEqual(audit["audit_status"], "valid")
        self.assertEqual(audit["coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()

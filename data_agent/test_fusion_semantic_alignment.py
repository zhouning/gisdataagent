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


if __name__ == "__main__":
    unittest.main()

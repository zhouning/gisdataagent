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


if __name__ == "__main__":
    unittest.main()

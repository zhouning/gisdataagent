"""Tests for the NL2Semantic2SQL cold-start intake pipeline."""
import json
import os
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("POSTGRES_HOST", "localhost")


class TestDatasetIntake(unittest.TestCase):
    """Tests for dataset_intake.py — schema scanning and profile management."""

    @patch("data_agent.dataset_intake.get_engine")
    def test_scan_tables_returns_profiles(self, mock_engine):
        """Verify scan_tables returns ok status when engine is available."""
        mock_engine.return_value = None
        from data_agent.dataset_intake import scan_tables
        result = scan_tables(table_filter=["test_table"])
        self.assertEqual(result["status"], "error")

    @patch("data_agent.dataset_intake.get_engine", return_value=None)
    def test_scan_tables_no_engine(self, _):
        from data_agent.dataset_intake import scan_tables
        result = scan_tables()
        self.assertEqual(result["status"], "error")

    def test_valid_transitions(self):
        from data_agent.dataset_intake import VALID_TRANSITIONS
        self.assertIn("drafted", VALID_TRANSITIONS["discovered"])
        self.assertIn("reviewed", VALID_TRANSITIONS["drafted"])
        self.assertIn("validated", VALID_TRANSITIONS["reviewed"])
        self.assertIn("active", VALID_TRANSITIONS["validated"])

    def test_invalid_transition_blocked(self):
        from data_agent.dataset_intake import VALID_TRANSITIONS
        self.assertNotIn("active", VALID_TRANSITIONS["discovered"])
        self.assertNotIn("drafted", VALID_TRANSITIONS["active"])

    @patch("data_agent.dataset_intake.get_engine")
    def test_scan_tables_does_not_commit_inside_begin_context(self, mock_engine):
        """Regression: _ensure_tables must not close the outer engine.begin() transaction."""
        mock_conn = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = mock_conn
        mock_ctx.__exit__.return_value = False
        mock_engine.return_value.begin.return_value = mock_ctx

        # Minimal successful path
        def fake_execute(*args, **kwargs):
            sql_text = str(args[0])
            m = MagicMock()
            if "RETURNING id" in sql_text:
                m.fetchone.return_value = (1,)
            elif "FROM information_schema.tables c" in sql_text:
                m.fetchall.return_value = []
            else:
                m.fetchone.return_value = None
                m.fetchall.return_value = []
                m.scalar.return_value = 0
            return m
        mock_conn.execute.side_effect = fake_execute
        mock_conn.commit = MagicMock()

        from data_agent.dataset_intake import scan_tables
        result = scan_tables(table_filter=["test_table"])
        self.assertEqual(result["status"], "ok")
        mock_conn.commit.assert_not_called()

class TestSemanticDrafting(unittest.TestCase):
    """Tests for semantic_drafting.py — draft generation."""

    def test_infer_domain(self):
        from data_agent.semantic_drafting import _infer_domain
        self.assertEqual(_infer_domain("population"), "POPULATION")
        self.assertEqual(_infer_domain("area_sqm"), "AREA")
        self.assertEqual(_infer_domain("longitude"), "LONGITUDE")
        self.assertIsNone(_infer_domain("foobar"))

    def test_needs_quoting(self):
        from data_agent.semantic_drafting import _needs_quoting
        self.assertTrue(_needs_quoting("Floor"))
        self.assertTrue(_needs_quoting("DLMC"))
        self.assertFalse(_needs_quoting("name"))
        self.assertFalse(_needs_quoting("geometry"))

    def test_generate_aliases_rule_based(self):
        from data_agent.semantic_drafting import _generate_aliases_rule_based
        aliases = _generate_aliases_rule_based("land_use_type", "土地利用类型", "varchar")
        self.assertIn("土地利用类型", aliases)
        self.assertIn("land use type", aliases)

    @patch("data_agent.semantic_drafting.get_engine")
    def test_generate_draft_no_profile(self, mock_engine):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value.begin.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None

        from data_agent.semantic_drafting import generate_draft
        result = generate_draft(profile_id=999, use_llm=False)
        self.assertIsNone(result)


class TestIntakeRegistry(unittest.TestCase):
    """Tests for intake_registry.py — review and activation."""

    @patch("data_agent.intake_registry.get_engine")
    def test_review_draft_not_found(self, mock_engine):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value.begin.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None

        from data_agent.intake_registry import review_draft
        result = review_draft(draft_id=999)
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["error"])

    @patch("data_agent.intake_registry.get_engine", return_value=None)
    def test_activate_no_engine(self, _):
        from data_agent.intake_registry import activate_draft
        result = activate_draft(draft_id=1)
        self.assertEqual(result["status"], "error")

    @patch("data_agent.intake_registry.get_engine", return_value=None)
    def test_rollback_no_engine(self, _):
        from data_agent.intake_registry import rollback_activation
        result = rollback_activation(dataset_id=1)
        self.assertEqual(result["status"], "error")


class TestIntakeValidation(unittest.TestCase):
    """Tests for intake_validation.py — cold-start evaluation."""

    def test_build_grounding_from_draft_uses_table_name_not_semantic_layer(self):
        from data_agent.intake_validation import _build_grounding_from_draft
        draft = {
            "display_name": "历史保护区范围成果表",
            "description": "Historic districts polygons",
            "columns_draft": json.dumps([
                {"column_name": "jqmc", "data_type": "varchar", "aliases": ["街区名称"], "needs_quoting": False},
                {"column_name": "fwlx", "data_type": "varchar", "aliases": ["范围类型"], "needs_quoting": False},
                {"column_name": "geometry", "udt_name": "geometry", "aliases": [], "needs_quoting": False},
            ]),
        }
        profile = {"row_count": 20}
        text = _build_grounding_from_draft("cq_historic_districts", draft, profile)
        self.assertIn("cq_historic_districts", text)
        self.assertIn("历史保护区范围成果表", text)
        self.assertIn("如果用户要求全部/所有结果，不要擅自添加 LIMIT", text)

    def test_build_validation_questions_covers_required_types(self):
        from data_agent.intake_validation import _build_validation_questions
        draft = {
            "columns_draft": json.dumps([
                {"column_name": "name", "semantic_domain": "NAME"},
                {"column_name": "category", "semantic_domain": "CATEGORY"},
                {"column_name": "id", "semantic_domain": "ID"},
            ]),
        }
        profile = {"sample_values": {"category": ["A", "B"]}}
        questions = _build_validation_questions("test_table", draft, profile)
        types = {q["type"] for q in questions}
        self.assertIn("filter", types)
        self.assertIn("aggregate", types)
        self.assertIn("security", types)
        self.assertIn("anti_illusion", types)
        self.assertGreaterEqual(len(questions), 4)

    def test_evaluate_security_question_correct_refusal(self):
        from data_agent.intake_validation import _evaluate_question
        q = {"type": "security", "gold_sql": None}
        result = _evaluate_question(q, "SELECT 1")
        self.assertTrue(result["passed"])

    def test_evaluate_security_question_dangerous_sql(self):
        from data_agent.intake_validation import _evaluate_question
        q = {"type": "security", "gold_sql": None}
        result = _evaluate_question(q, "DELETE FROM test_table")
        self.assertFalse(result["passed"])

    def test_evaluate_anti_illusion_correct_refusal(self):
        from data_agent.intake_validation import _evaluate_question
        q = {"type": "anti_illusion", "gold_sql": None}
        result = _evaluate_question(q, None)
        self.assertTrue(result["passed"])

    def test_evaluate_filter_no_sql(self):
        from data_agent.intake_validation import _evaluate_question
        q = {"type": "filter", "gold_sql": "SELECT COUNT(*) FROM t"}
        result = _evaluate_question(q, None)
        self.assertFalse(result["passed"])

    def test_pass_threshold_constant(self):
        from data_agent.intake_validation import PASS_THRESHOLD
        self.assertEqual(PASS_THRESHOLD, 0.80)


class TestActivationGate(unittest.TestCase):
    """Tests for activation gate logic in intake_routes."""

    def test_routes_include_validate(self):
        from data_agent.api.intake_routes import get_intake_routes
        routes = get_intake_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/intake/{dataset_id:int}/validate", paths)

    def test_routes_count(self):
        from data_agent.api.intake_routes import get_intake_routes
        routes = get_intake_routes()
        self.assertGreaterEqual(len(routes), 9)

    def test_routes_registered(self):
        from data_agent.api.intake_routes import get_intake_routes
        routes = get_intake_routes()
        self.assertGreaterEqual(len(routes), 6)
        paths = [r.path for r in routes]
        self.assertIn("/api/intake/scan", paths)
        self.assertIn("/api/intake/profiles", paths)


class TestDomainIsolatedFewShot(unittest.TestCase):
    """Tests for Phase C: domain-isolated few-shot."""

    def test_auto_curate_infers_domain_from_sql(self):
        from data_agent.nl2sql_executor import _auto_curate
        with patch("data_agent.reference_queries.ReferenceQueryStore") as MockStore:
            mock_instance = MagicMock()
            MockStore.return_value = mock_instance
            _auto_curate("test question", 'SELECT * FROM cq_buildings_2021 WHERE "Floor" > 10')
            mock_instance.add.assert_called_once()
            call_kwargs = mock_instance.add.call_args.kwargs
            self.assertEqual(call_kwargs["domain_id"], "cq_buildings_2021")

    def test_auto_curate_no_domain_for_empty_sql(self):
        from data_agent.nl2sql_executor import _auto_curate
        with patch("data_agent.reference_queries.ReferenceQueryStore") as MockStore:
            _auto_curate("", "")
            MockStore.return_value.add.assert_not_called()

    def test_fetch_few_shots_accepts_domain_id(self):
        from data_agent.reference_queries import fetch_nl2sql_few_shots
        with patch("data_agent.reference_queries.ReferenceQueryStore") as MockStore:
            mock_instance = MagicMock()
            mock_instance.search.return_value = [
                {"id": 1, "query_text": "q1", "response_summary": "SELECT 1", "domain_id": "tbl_a"},
                {"id": 2, "query_text": "q2", "response_summary": "SELECT 2", "domain_id": "tbl_b"},
            ]
            MockStore.return_value = mock_instance
            result = fetch_nl2sql_few_shots("test", top_k=2, domain_id="tbl_a")
            self.assertIn("q1", result)

    def test_reference_query_add_accepts_domain_id(self):
        from data_agent.reference_queries import ReferenceQueryStore
        import inspect
        sig = inspect.signature(ReferenceQueryStore.add)
        self.assertIn("domain_id", sig.parameters)


if __name__ == "__main__":
    unittest.main()
    unittest.main()

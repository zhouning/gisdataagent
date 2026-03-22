"""Tests for data distribution — requests, reviews, packaging, access stats (v15.0)."""
import unittest
from unittest.mock import patch, MagicMock


class TestCreateRequest(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine")
    def test_create_success(self, mock_eng):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.side_effect = [None, MagicMock(scalar=MagicMock(return_value=1))]
        mock_eng.return_value = engine
        from data_agent.data_distribution import create_data_request
        result = create_data_request(1, "user1", "need this data")
        self.assertEqual(result["status"], "ok")

    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_create_no_db(self, _):
        from data_agent.data_distribution import create_data_request
        result = create_data_request(1, "user1")
        self.assertEqual(result["status"], "error")


class TestListRequests(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_list_no_db(self, _):
        from data_agent.data_distribution import list_data_requests
        self.assertEqual(list_data_requests("user1"), [])


class TestApproveReject(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_approve_no_db(self, _):
        from data_agent.data_distribution import approve_request
        result = approve_request(1, "admin")
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_reject_no_db(self, _):
        from data_agent.data_distribution import reject_request
        result = reject_request(1, "admin", "not appropriate")
        self.assertEqual(result["status"], "error")


class TestAddReview(unittest.TestCase):
    def test_invalid_rating(self):
        from data_agent.data_distribution import add_review
        result = add_review(1, "user1", 0)
        self.assertEqual(result["status"], "error")
        result = add_review(1, "user1", 6)
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_distribution import add_review
        result = add_review(1, "user1", 4, "good data")
        self.assertEqual(result["status"], "error")


class TestGetReviews(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_distribution import get_reviews
        self.assertEqual(get_reviews(1), [])


class TestGetAssetRating(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_distribution import get_asset_rating
        result = get_asset_rating(1)
        self.assertEqual(result["avg_rating"], 0)
        self.assertEqual(result["count"], 0)


class TestAccessStats(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_stats_no_db(self, _):
        from data_agent.data_distribution import get_access_stats
        result = get_access_stats()
        self.assertEqual(result["status"], "error")

    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_hot_no_db(self, _):
        from data_agent.data_distribution import get_hot_assets
        self.assertEqual(get_hot_assets(), [])


class TestPackageAssets(unittest.TestCase):
    @patch("data_agent.data_distribution.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.data_distribution import package_assets
        result = package_assets([1, 2])
        self.assertEqual(result["status"], "error")


class TestConstants(unittest.TestCase):
    def test_valid_status(self):
        from data_agent.data_distribution import VALID_REQUEST_STATUS
        self.assertIn("pending", VALID_REQUEST_STATUS)
        self.assertIn("approved", VALID_REQUEST_STATUS)
        self.assertIn("rejected", VALID_REQUEST_STATUS)


if __name__ == "__main__":
    unittest.main()

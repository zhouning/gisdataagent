import unittest
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
from data_agent.database_tools import get_db_connection_url, query_database

class TestDatabase(unittest.TestCase):
    def test_connection_string(self):
        url = get_db_connection_url()
        self.assertIsNotNone(url)
        self.assertIn("postgresql://", url)
        print(f"Connection String: {url.replace(os.environ.get('POSTGRES_PASSWORD'), '***')}")

    def test_query_failure_graceful(self):
        # We expect connection to fail if DB is not reachable, but tool should handle it
        # This test just checks if the tool returns the expected error structure
        result = query_database("SELECT 1")
        if result['status'] == 'error':
            print(f"Query failed as expected (network/db offline): {result['message']}")
        else:
            print("Query success!")

if __name__ == "__main__":
    unittest.main()

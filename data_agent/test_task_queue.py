"""Tests for Task Queue (v11.0.1).

Covers job lifecycle, concurrency control, DB persistence, and REST endpoints.
"""
import asyncio
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class TestTaskJob(unittest.TestCase):
    def test_defaults(self):
        from data_agent.task_queue import TaskJob
        job = TaskJob()
        self.assertTrue(job.job_id)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.priority, 5)

    def test_to_dict(self):
        from data_agent.task_queue import TaskJob
        job = TaskJob(user_id="alice", prompt="test prompt", pipeline_type="general")
        d = job.to_dict()
        self.assertEqual(d["user_id"], "alice")
        self.assertEqual(d["pipeline_type"], "general")
        self.assertIn("job_id", d)

    def test_to_dict_truncates_prompt(self):
        from data_agent.task_queue import TaskJob
        job = TaskJob(prompt="x" * 500)
        d = job.to_dict()
        self.assertEqual(len(d["prompt"]), 200)


class TestTaskQueueConstants(unittest.TestCase):
    def test_table_name(self):
        from data_agent.task_queue import T_TASK_QUEUE
        self.assertEqual(T_TASK_QUEUE, "agent_task_queue")

    def test_max_concurrent_default(self):
        from data_agent.task_queue import MAX_CONCURRENT
        self.assertGreater(MAX_CONCURRENT, 0)


class TestTaskQueueOperations(unittest.TestCase):
    def setUp(self):
        from data_agent.task_queue import reset_task_queue
        reset_task_queue()

    def tearDown(self):
        from data_agent.task_queue import reset_task_queue
        reset_task_queue()

    @patch("data_agent.task_queue.get_engine", return_value=None)
    def test_submit(self, _):
        from data_agent.task_queue import get_task_queue
        queue = get_task_queue()
        job_id = queue.submit("alice", "analyze data", "general")
        self.assertTrue(job_id)
        self.assertIn(job_id, queue._jobs)
        self.assertEqual(queue._jobs[job_id].status, "queued")

    @patch("data_agent.task_queue.get_engine", return_value=None)
    def test_submit_priority(self, _):
        from data_agent.task_queue import get_task_queue
        queue = get_task_queue()
        j1 = queue.submit("alice", "low priority", priority=9)
        j2 = queue.submit("alice", "high priority", priority=1)
        self.assertEqual(queue._jobs[j1].priority, 9)
        self.assertEqual(queue._jobs[j2].priority, 1)

    @patch("data_agent.task_queue.get_engine", return_value=None)
    def test_submit_user_limit(self, _):
        from data_agent.task_queue import get_task_queue, MAX_QUEUED_PER_USER
        queue = get_task_queue()
        for i in range(MAX_QUEUED_PER_USER):
            queue.submit("alice", f"task {i}")
        with self.assertRaises(ValueError):
            queue.submit("alice", "one too many")

    @patch("data_agent.task_queue.get_engine", return_value=None)
    def test_cancel_queued(self, _):
        from data_agent.task_queue import get_task_queue
        queue = get_task_queue()
        job_id = queue.submit("alice", "test")
        self.assertTrue(queue.cancel(job_id))
        self.assertEqual(queue._jobs[job_id].status, "cancelled")

    @patch("data_agent.task_queue.get_engine", return_value=None)
    def test_cancel_nonexistent(self, _):
        from data_agent.task_queue import get_task_queue
        queue = get_task_queue()
        self.assertFalse(queue.cancel("nonexistent"))

    @patch("data_agent.task_queue.get_engine", return_value=None)
    def test_get_status(self, _):
        from data_agent.task_queue import get_task_queue
        queue = get_task_queue()
        job_id = queue.submit("alice", "test")
        status = queue.get_status(job_id)
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "queued")

    @patch("data_agent.task_queue.get_engine", return_value=None)
    def test_get_status_not_found(self, _):
        from data_agent.task_queue import get_task_queue
        queue = get_task_queue()
        self.assertIsNone(queue.get_status("nonexistent"))

    @patch("data_agent.task_queue.get_engine", return_value=None)
    def test_list_jobs(self, _):
        from data_agent.task_queue import get_task_queue
        queue = get_task_queue()
        queue.submit("alice", "task1")
        queue.submit("bob", "task2")
        queue.submit("alice", "task3")

        all_jobs = queue.list_jobs()
        self.assertEqual(len(all_jobs), 3)

        alice_jobs = queue.list_jobs(user_id="alice")
        self.assertEqual(len(alice_jobs), 2)

    @patch("data_agent.task_queue.get_engine", return_value=None)
    def test_list_jobs_by_status(self, _):
        from data_agent.task_queue import get_task_queue
        queue = get_task_queue()
        j1 = queue.submit("alice", "task1")
        queue.cancel(j1)
        queue.submit("alice", "task2")

        queued = queue.list_jobs(status="queued")
        self.assertEqual(len(queued), 1)
        cancelled = queue.list_jobs(status="cancelled")
        self.assertEqual(len(cancelled), 1)

    @patch("data_agent.task_queue.get_engine", return_value=None)
    def test_queue_stats(self, _):
        from data_agent.task_queue import get_task_queue
        queue = get_task_queue()
        queue.submit("alice", "task1")
        queue.submit("alice", "task2")
        stats = queue.queue_stats
        self.assertEqual(stats["total"], 2)
        self.assertIn("queued", stats["by_status"])


class TestTaskQueueRoutes(unittest.TestCase):
    def test_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/tasks/submit", paths)
        self.assertIn("/api/tasks", paths)
        self.assertIn("/api/tasks/{job_id}", paths)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_submit_unauthorized(self, _):
        from data_agent.frontend_api import _api_tasks_submit
        resp = _run_async(_api_tasks_submit(MagicMock()))
        self.assertEqual(resp.status_code, 401)


class TestTaskQueueSingleton(unittest.TestCase):
    def test_singleton(self):
        from data_agent.task_queue import get_task_queue, reset_task_queue
        reset_task_queue()
        q1 = get_task_queue()
        q2 = get_task_queue()
        self.assertIs(q1, q2)
        reset_task_queue()

    def test_reset(self):
        from data_agent.task_queue import get_task_queue, reset_task_queue
        q1 = get_task_queue()
        reset_task_queue()
        q2 = get_task_queue()
        self.assertIsNot(q1, q2)
        reset_task_queue()


class TestGetPipelineAgent(unittest.TestCase):
    def test_known_types(self):
        from data_agent.task_queue import _get_pipeline_agent
        # These should not crash (agent module imported)
        for pt in ("general", "governance", "optimization", "planner"):
            agent = _get_pipeline_agent(pt)
            # Agent may be None if module doesn't define it at import time
            # but the function itself shouldn't crash


if __name__ == "__main__":
    unittest.main()

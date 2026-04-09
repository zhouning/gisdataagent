"""Tests for embodied execution interface (v23.0)."""
import asyncio
import unittest

from data_agent.embodied import (
    ExecutionRequest, ExecutionStatus, ExecutorType,
    MockUAVExecutor, MockSatelliteExecutor,
    register_executor, get_executor, list_executors,
    init_mock_executors, _executors,
)


class TestExecutionRequest(unittest.TestCase):
    def test_defaults(self):
        req = ExecutionRequest(task_type="survey_flight")
        assert req.task_type == "survey_flight"
        assert req.priority == 5
        assert len(req.request_id) == 8

    def test_custom_params(self):
        req = ExecutionRequest(
            task_type="mapping_flight",
            area_wkt="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
            params={"altitude_m": 150},
        )
        assert req.params["altitude_m"] == 150


class TestMockUAVExecutor(unittest.TestCase):
    def test_execute(self):
        executor = MockUAVExecutor()
        req = ExecutionRequest(task_type="survey_flight", params={"altitude_m": 120})
        result = asyncio.get_event_loop().run_until_complete(executor.execute(req))
        assert result.status == ExecutionStatus.SUBMITTED
        assert result.executor_type == ExecutorType.UAV
        assert result.data["altitude_m"] == 120

    def test_get_status(self):
        executor = MockUAVExecutor()
        req = ExecutionRequest(task_type="survey_flight")
        asyncio.get_event_loop().run_until_complete(executor.execute(req))
        result = asyncio.get_event_loop().run_until_complete(
            executor.get_status(req.request_id)
        )
        assert result.status == ExecutionStatus.SUBMITTED

    def test_cancel(self):
        executor = MockUAVExecutor()
        req = ExecutionRequest(task_type="survey_flight")
        asyncio.get_event_loop().run_until_complete(executor.execute(req))
        ok = asyncio.get_event_loop().run_until_complete(executor.cancel(req.request_id))
        assert ok
        result = asyncio.get_event_loop().run_until_complete(
            executor.get_status(req.request_id)
        )
        assert result.status == ExecutionStatus.CANCELLED

    def test_capabilities(self):
        caps = MockUAVExecutor().get_capabilities()
        assert "survey_flight" in caps["task_types"]


class TestMockSatelliteExecutor(unittest.TestCase):
    def test_execute(self):
        executor = MockSatelliteExecutor()
        req = ExecutionRequest(task_type="optical_capture")
        result = asyncio.get_event_loop().run_until_complete(executor.execute(req))
        assert result.status == ExecutionStatus.SUBMITTED
        assert result.executor_type == ExecutorType.SATELLITE

    def test_capabilities(self):
        caps = MockSatelliteExecutor().get_capabilities()
        assert "optical_capture" in caps["task_types"]


class TestRegistry(unittest.TestCase):
    def setUp(self):
        _executors.clear()

    def test_register_and_get(self):
        register_executor(MockUAVExecutor())
        assert get_executor("uav") is not None
        assert get_executor("nonexistent") is None

    def test_list_executors(self):
        init_mock_executors()
        executors = list_executors()
        assert len(executors) == 2
        types = {e["type"] for e in executors}
        assert types == {"uav", "satellite"}

    def tearDown(self):
        _executors.clear()


if __name__ == "__main__":
    unittest.main()

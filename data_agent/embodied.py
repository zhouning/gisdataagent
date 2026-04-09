"""
Embodied Execution Interface — abstract API for physical actuators (v23.0).

Defines the contract for satellite tasking, UAV flight planning, and
ground sensor control. Concrete implementations are expected to be
provided by external integrations; this module ships with mock backends
for testing and development.

Usage:
    from data_agent.embodied import get_executor, ExecutionRequest

    executor = get_executor("uav")
    result = await executor.execute(ExecutionRequest(
        task_type="survey_flight",
        area_wkt="POLYGON((...)))",
        params={"altitude_m": 120, "overlap_pct": 70},
    ))
"""
from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("data_agent.embodied")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class ExecutorType(str, Enum):
    UAV = "uav"
    SATELLITE = "satellite"
    SENSOR = "sensor"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionRequest:
    """Request to execute a physical task."""
    task_type: str
    area_wkt: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    priority: int = 5  # 1=highest, 10=lowest
    requested_by: str = ""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class ExecutionResult:
    """Result of an embodied execution."""
    request_id: str
    status: ExecutionStatus
    executor_type: ExecutorType
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Abstract executor
# ---------------------------------------------------------------------------

class BaseExecutor(ABC):
    """Abstract base for embodied execution backends."""

    executor_type: ExecutorType

    @abstractmethod
    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Submit an execution request."""
        ...

    @abstractmethod
    async def get_status(self, request_id: str) -> ExecutionResult:
        """Query status of a submitted request."""
        ...

    @abstractmethod
    async def cancel(self, request_id: str) -> bool:
        """Cancel a pending/in-progress request."""
        ...

    @abstractmethod
    def get_capabilities(self) -> dict[str, Any]:
        """Return supported task types and parameters."""
        ...


# ---------------------------------------------------------------------------
# Mock implementations (for development/testing)
# ---------------------------------------------------------------------------

class MockUAVExecutor(BaseExecutor):
    """Mock UAV flight planner."""
    executor_type = ExecutorType.UAV

    def __init__(self):
        self._tasks: dict[str, ExecutionResult] = {}

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        result = ExecutionResult(
            request_id=request.request_id,
            status=ExecutionStatus.SUBMITTED,
            executor_type=self.executor_type,
            message=f"UAV flight plan created: {request.task_type}",
            data={
                "flight_plan_id": f"FP-{request.request_id}",
                "estimated_duration_min": 45,
                "waypoints": 12,
                "altitude_m": request.params.get("altitude_m", 100),
            },
            submitted_at=datetime.now(),
        )
        self._tasks[request.request_id] = result
        logger.info("Mock UAV: submitted %s", request.request_id)
        return result

    async def get_status(self, request_id: str) -> ExecutionResult:
        if request_id in self._tasks:
            return self._tasks[request_id]
        return ExecutionResult(
            request_id=request_id, status=ExecutionStatus.FAILED,
            executor_type=self.executor_type, message="Not found",
        )

    async def cancel(self, request_id: str) -> bool:
        if request_id in self._tasks:
            self._tasks[request_id].status = ExecutionStatus.CANCELLED
            return True
        return False

    def get_capabilities(self) -> dict:
        return {
            "executor": "uav",
            "task_types": ["survey_flight", "inspection_flight", "mapping_flight"],
            "params": {
                "altitude_m": {"type": "float", "default": 100, "range": [30, 500]},
                "overlap_pct": {"type": "float", "default": 70, "range": [50, 90]},
                "camera_angle": {"type": "float", "default": -90},
            },
        }


class MockSatelliteExecutor(BaseExecutor):
    """Mock satellite tasking interface."""
    executor_type = ExecutorType.SATELLITE

    def __init__(self):
        self._tasks: dict[str, ExecutionResult] = {}

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        result = ExecutionResult(
            request_id=request.request_id,
            status=ExecutionStatus.SUBMITTED,
            executor_type=self.executor_type,
            message=f"Satellite tasking request submitted: {request.task_type}",
            data={
                "order_id": f"SAT-{request.request_id}",
                "estimated_acquisition": "2-5 days",
                "resolution_m": request.params.get("resolution_m", 0.5),
            },
            submitted_at=datetime.now(),
        )
        self._tasks[request.request_id] = result
        return result

    async def get_status(self, request_id: str) -> ExecutionResult:
        return self._tasks.get(request_id, ExecutionResult(
            request_id=request_id, status=ExecutionStatus.FAILED,
            executor_type=self.executor_type, message="Not found",
        ))

    async def cancel(self, request_id: str) -> bool:
        if request_id in self._tasks:
            self._tasks[request_id].status = ExecutionStatus.CANCELLED
            return True
        return False

    def get_capabilities(self) -> dict:
        return {
            "executor": "satellite",
            "task_types": ["optical_capture", "sar_capture", "multispectral"],
            "params": {
                "resolution_m": {"type": "float", "default": 0.5, "range": [0.3, 30]},
                "cloud_cover_max_pct": {"type": "float", "default": 20},
            },
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_executors: dict[str, BaseExecutor] = {}


def register_executor(executor: BaseExecutor) -> None:
    """Register an executor backend."""
    _executors[executor.executor_type.value] = executor


def get_executor(executor_type: str) -> BaseExecutor | None:
    """Get a registered executor by type."""
    return _executors.get(executor_type)


def list_executors() -> list[dict]:
    """List all registered executors and their capabilities."""
    return [
        {"type": e.executor_type.value, **e.get_capabilities()}
        for e in _executors.values()
    ]


def init_mock_executors() -> None:
    """Register mock executors for development."""
    register_executor(MockUAVExecutor())
    register_executor(MockSatelliteExecutor())
    logger.info("Mock embodied executors registered: uav, satellite")

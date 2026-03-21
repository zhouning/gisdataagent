"""
Circuit Breaker — automatic failure detection and graceful degradation (v14.2).

Tracks tool and agent failure rates. When failures exceed a threshold within
a time window, the circuit "opens" and calls are short-circuited with an error.
After a cooldown period, the circuit enters "half-open" state for a probe call.
"""
import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("data_agent.circuit_breaker")


@dataclass
class CircuitState:
    """State for a single circuit (tool or agent)."""
    name: str
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    state: str = "closed"  # closed | open | half_open
    opened_at: float = 0.0


class CircuitBreaker:
    """Circuit breaker for tool and agent reliability.

    Usage:
        cb = get_circuit_breaker()
        if cb.is_allowed("tool_name"):
            try:
                result = tool_call()
                cb.record_success("tool_name")
            except Exception:
                cb.record_failure("tool_name")
        else:
            # Fallback or error
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 120.0,
                 window_seconds: float = 300.0):
        self._circuits: dict[str, CircuitState] = {}
        self._lock = threading.Lock()
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.window_seconds = window_seconds

    def _get_circuit(self, name: str) -> CircuitState:
        if name not in self._circuits:
            self._circuits[name] = CircuitState(name=name)
        return self._circuits[name]

    def is_allowed(self, name: str) -> bool:
        """Check if a call to this tool/agent is allowed."""
        with self._lock:
            circuit = self._get_circuit(name)
            now = time.time()

            if circuit.state == "closed":
                return True

            if circuit.state == "open":
                if now - circuit.opened_at >= self.cooldown_seconds:
                    circuit.state = "half_open"
                    logger.info("Circuit '%s' entering half-open state", name)
                    return True
                return False

            # half_open — allow one probe call
            return True

    def record_success(self, name: str):
        """Record a successful call. Resets failure count."""
        with self._lock:
            circuit = self._get_circuit(name)
            circuit.success_count += 1
            if circuit.state == "half_open":
                circuit.state = "closed"
                circuit.failure_count = 0
                logger.info("Circuit '%s' closed (recovered)", name)
            elif circuit.state == "closed":
                circuit.failure_count = max(0, circuit.failure_count - 1)

    def record_failure(self, name: str):
        """Record a failed call. May open the circuit."""
        with self._lock:
            circuit = self._get_circuit(name)
            now = time.time()

            if now - circuit.last_failure_time > self.window_seconds:
                circuit.failure_count = 0

            circuit.failure_count += 1
            circuit.last_failure_time = now

            if circuit.state == "half_open":
                circuit.state = "open"
                circuit.opened_at = now
                logger.warning("Circuit '%s' reopened (probe failed)", name)

            elif circuit.state == "closed" and circuit.failure_count >= self.failure_threshold:
                circuit.state = "open"
                circuit.opened_at = now
                logger.warning("Circuit '%s' opened (%d failures in %.0fs)",
                               name, circuit.failure_count, self.window_seconds)

    def get_status(self) -> dict:
        """Return status of all tracked circuits."""
        with self._lock:
            return {
                name: {
                    "state": c.state,
                    "failures": c.failure_count,
                    "successes": c.success_count,
                    "last_failure": c.last_failure_time,
                }
                for name, c in self._circuits.items()
            }

    def reset(self, name: str = None):
        """Reset a specific circuit or all circuits."""
        with self._lock:
            if name:
                self._circuits.pop(name, None)
            else:
                self._circuits.clear()


# Singleton
_breaker: Optional[CircuitBreaker] = None


def get_circuit_breaker() -> CircuitBreaker:
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker()
    return _breaker

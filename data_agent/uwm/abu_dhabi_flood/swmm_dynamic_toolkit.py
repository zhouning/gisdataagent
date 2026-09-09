"""Small ctypes adapter for synchronized EPA SWMM coupling runs."""

from __future__ import annotations

import ctypes
import math
from pathlib import Path

SWMM_NODE = 2
SWMM_NODE_DEPTH = 303
SWMM_NODE_HEAD = 304
SWMM_NODE_VOLUME = 305
SWMM_NODE_LATFLOW = 306
SWMM_NODE_INFLOW = 307
SWMM_NODE_OVERFLOW = 308
SECONDS_PER_DAY = 86_400.0


class SwmmDynamicToolkitError(RuntimeError):
    """Raised when the native SWMM dynamic API reports an error."""


class SwmmDynamicSession:
    """Own one native SWMM session for synchronized step/get/set operations."""

    def __init__(
        self,
        library_path: Path,
        input_path: Path,
        report_path: Path,
        output_path: Path,
        *,
        save_results: bool = False,
    ) -> None:
        self.library_path = library_path.expanduser().resolve()
        self.input_path = input_path.expanduser().resolve()
        self.report_path = report_path.expanduser().resolve()
        self.output_path = output_path.expanduser().resolve()
        if not self.library_path.is_file():
            raise ValueError("swmm_dynamic_library_missing")
        if not self.input_path.is_file():
            raise ValueError("swmm_dynamic_input_missing")
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_results = bool(save_results)
        self._library = ctypes.CDLL(str(self.library_path))
        self._configure_signatures()
        self._opened = False
        self._started = False

    def _configure_signatures(self) -> None:
        library = self._library
        library.swmm_open.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        library.swmm_open.restype = ctypes.c_int
        library.swmm_start.argtypes = [ctypes.c_int]
        library.swmm_start.restype = ctypes.c_int
        library.swmm_stride.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_double)]
        library.swmm_stride.restype = ctypes.c_int
        library.swmm_end.argtypes = []
        library.swmm_end.restype = ctypes.c_int
        library.swmm_close.argtypes = []
        library.swmm_close.restype = ctypes.c_int
        library.swmm_getError.argtypes = [ctypes.c_char_p, ctypes.c_int]
        library.swmm_getError.restype = ctypes.c_int
        library.swmm_getCount.argtypes = [ctypes.c_int]
        library.swmm_getCount.restype = ctypes.c_int
        library.swmm_getName.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        library.swmm_getName.restype = None
        library.swmm_getIndex.argtypes = [ctypes.c_int, ctypes.c_char_p]
        library.swmm_getIndex.restype = ctypes.c_int
        library.swmm_getValue.argtypes = [ctypes.c_int, ctypes.c_int]
        library.swmm_getValue.restype = ctypes.c_double
        library.swmm_setValue.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_double]
        library.swmm_setValue.restype = None

    def _raise_for_error(self, code: int, operation: str) -> None:
        if code == 0:
            return
        message = ctypes.create_string_buffer(1024)
        self._library.swmm_getError(message, len(message))
        detail = message.value.decode("utf-8", errors="replace").strip()
        raise SwmmDynamicToolkitError(
            f"swmm_dynamic_{operation}_failed:{code}:{detail}"
        )

    def open(self) -> "SwmmDynamicSession":
        if self._opened:
            return self
        code = self._library.swmm_open(
            str(self.input_path).encode(),
            str(self.report_path).encode(),
            str(self.output_path).encode(),
        )
        self._raise_for_error(code, "open")
        self._opened = True
        return self

    def start(self) -> "SwmmDynamicSession":
        if not self._opened:
            self.open()
        if self._started:
            return self
        code = self._library.swmm_start(1 if self.save_results else 0)
        self._raise_for_error(code, "start")
        self._started = True
        return self

    @property
    def node_count(self) -> int:
        if not self._opened:
            raise SwmmDynamicToolkitError("swmm_dynamic_session_not_open")
        return int(self._library.swmm_getCount(SWMM_NODE))

    def node_name(self, index: int) -> str:
        if index < 0 or index >= self.node_count:
            raise ValueError("swmm_dynamic_node_index_out_of_range")
        name = ctypes.create_string_buffer(1024)
        self._library.swmm_getName(SWMM_NODE, index, name, len(name))
        return name.value.decode("utf-8", errors="replace")

    def node_index(self, node_id: str) -> int:
        index = int(self._library.swmm_getIndex(SWMM_NODE, node_id.encode()))
        if index < 0:
            raise ValueError("swmm_dynamic_node_unknown")
        return index

    def node_state(self, index: int) -> dict[str, float]:
        if index < 0 or index >= self.node_count:
            raise ValueError("swmm_dynamic_node_index_out_of_range")
        return {
            "depth_m": float(self._library.swmm_getValue(SWMM_NODE_DEPTH, index)),
            "head_m": float(self._library.swmm_getValue(SWMM_NODE_HEAD, index)),
            "volume_m3": float(self._library.swmm_getValue(SWMM_NODE_VOLUME, index)),
            "lateral_inflow_m3s": float(
                self._library.swmm_getValue(SWMM_NODE_LATFLOW, index)
            ),
            "total_inflow_m3s": float(
                self._library.swmm_getValue(SWMM_NODE_INFLOW, index)
            ),
            "overflow_or_flooding_m3s": float(
                self._library.swmm_getValue(SWMM_NODE_OVERFLOW, index)
            ),
        }

    def node_storage_m3(self) -> float:
        """Return the current sum of SWMM node storage volumes.

        This is an explicit node-storage scope, not a substitute for the
        complete SWMM system storage ledger (which also includes link and
        other routing terms).  Coupling receipts label the scope accordingly.
        """

        if not self._opened:
            raise SwmmDynamicToolkitError("swmm_dynamic_session_not_open")
        return float(
            sum(
                float(self._library.swmm_getValue(SWMM_NODE_VOLUME, index))
                for index in range(self.node_count)
            )
        )

    def set_node_surface_exchange_flow(self, index: int, rate_m3s: float) -> None:
        """Set signed ANUGA/SWMM exchange as a SWMM external lateral flow.

        Positive values add water to SWMM; negative values remove water from
        SWMM and therefore represent surface-to-network capture.
        """

        rate = float(rate_m3s)
        if not math.isfinite(rate):
            raise ValueError("swmm_dynamic_surface_return_flow_invalid")
        if index < 0 or index >= self.node_count:
            raise ValueError("swmm_dynamic_node_index_out_of_range")
        self._library.swmm_setValue(SWMM_NODE_LATFLOW, index, rate)

    def stride(self, seconds: int) -> float:
        """Advance by a fixed window and return elapsed model seconds."""

        if not self._started:
            self.start()
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
            raise ValueError("swmm_dynamic_stride_seconds_invalid")
        elapsed_days = ctypes.c_double(0.0)
        code = self._library.swmm_stride(seconds, ctypes.byref(elapsed_days))
        self._raise_for_error(code, "stride")
        return float(elapsed_days.value * SECONDS_PER_DAY)

    def close(self) -> None:
        if self._started:
            try:
                self._raise_for_error(self._library.swmm_end(), "end")
            finally:
                self._started = False
        if self._opened:
            try:
                self._raise_for_error(self._library.swmm_close(), "close")
            finally:
                self._opened = False

    def __enter__(self) -> "SwmmDynamicSession":
        return self.open().start()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

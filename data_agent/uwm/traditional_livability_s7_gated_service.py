from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from data_agent.uwm.traditional_livability_s7_gated_product import GATE_FILENAME, SITING_FILENAME


class S7RunConflict(RuntimeError):
    pass


class S7RunInvalid(ValueError):
    pass


class TraditionalLivabilityS7GatedService:
    def __init__(self, *, gate: dict, result: dict):
        self._gate = deepcopy(gate)
        self._result = deepcopy(result)

    @classmethod
    def from_product_dir(cls, product_dir: Path):
        root = Path(product_dir)
        gate = json.loads((root / GATE_FILENAME).read_text(encoding="utf-8"))
        result = json.loads((root / SITING_FILENAME).read_text(encoding="utf-8"))
        if gate.get("bundle_id") != result.get("bundle_id"):
            raise ValueError("s7_gated_bundle_mismatch")
        return cls(gate=gate, result=result)

    def demand_gate(self):
        return deepcopy(self._gate)

    def current_result(self):
        return deepcopy(self._result)

    def run(self, *, mode: str, acknowledgement: bool):
        state = self._gate.get("state")
        if mode == "authoritative":
            if state != "authoritative_need_confirmed":
                raise S7RunConflict("authoritative_need_not_confirmed")
            if self._result.get("mode") != "authoritative":
                raise S7RunConflict("authoritative_product_unavailable")
        elif mode == "conditional":
            if state != "need_unresolved":
                raise S7RunConflict("conditional_mode_requires_unresolved_need")
            if acknowledgement is not True:
                raise S7RunInvalid("conditional_not_a_recommendation_ack_required")
            if self._result.get("mode") != "conditional":
                raise S7RunConflict("conditional_product_unavailable")
        else:
            raise S7RunInvalid("unsupported_s7_run_mode")
        return deepcopy(self._result)

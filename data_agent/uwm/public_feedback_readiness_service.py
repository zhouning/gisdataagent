from copy import deepcopy
import json
from pathlib import Path


FILES = ("overview", "capabilities", "feedback_channels", "data_contracts", "analysis_gate", "map")


class PublicFeedbackReadinessService:
    def __init__(self, root: Path):
        self._payloads = {name: json.loads((Path(root) / f"{name}.json").read_text()) for name in FILES}
        bundle_ids = {payload.get("bundle_id") for payload in self._payloads.values()}
        if len(bundle_ids) != 1 or None in bundle_ids:
            raise ValueError("public_feedback_bundle_mismatch")

    def overview(self): return deepcopy(self._payloads["overview"])
    def capabilities(self): return deepcopy(self._payloads["capabilities"])
    def feedback_channels(self): return deepcopy(self._payloads["feedback_channels"])
    def data_contracts(self): return deepcopy(self._payloads["data_contracts"])
    def analysis_gate(self): return deepcopy(self._payloads["analysis_gate"])
    def map_payload(self): return deepcopy(self._payloads["map"])

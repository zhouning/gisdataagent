from copy import deepcopy
import json
from pathlib import Path


FILES = ("overview", "evidence_assets", "financial_channels", "data_contracts", "calculation_gate", "map")


class FinancialReadinessService:
    def __init__(self, root: Path):
        self._payloads = {name: json.loads((Path(root) / f"{name}.json").read_text()) for name in FILES}
        bundle_ids = {payload.get("bundle_id") for payload in self._payloads.values()}
        if len(bundle_ids) != 1 or None in bundle_ids:
            raise ValueError("financial_readiness_bundle_mismatch")

    def overview(self): return deepcopy(self._payloads["overview"])
    def evidence_assets(self): return deepcopy(self._payloads["evidence_assets"])
    def financial_channels(self): return deepcopy(self._payloads["financial_channels"])
    def data_contracts(self): return deepcopy(self._payloads["data_contracts"])
    def calculation_gate(self): return deepcopy(self._payloads["calculation_gate"])
    def map_payload(self): return deepcopy(self._payloads["map"])

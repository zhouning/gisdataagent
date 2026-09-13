from copy import deepcopy
import json
from pathlib import Path


FILES = ("overview", "version_assets", "version_channels", "data_contracts", "temporal_gate", "map")


class PlanningVersionRegistryService:
    def __init__(self, root: Path):
        self._payloads = {name: json.loads((Path(root) / f"{name}.json").read_text()) for name in FILES}
        bundle_ids = {payload.get("bundle_id") for payload in self._payloads.values()}
        if len(bundle_ids) != 1 or None in bundle_ids: raise ValueError("planning_version_bundle_mismatch")

    def overview(self): return deepcopy(self._payloads["overview"])
    def version_assets(self): return deepcopy(self._payloads["version_assets"])
    def version_channels(self): return deepcopy(self._payloads["version_channels"])
    def data_contracts(self): return deepcopy(self._payloads["data_contracts"])
    def temporal_gate(self): return deepcopy(self._payloads["temporal_gate"])
    def map_payload(self): return deepcopy(self._payloads["map"])

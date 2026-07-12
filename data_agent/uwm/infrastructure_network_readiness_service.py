from copy import deepcopy
import json
from pathlib import Path


FILES = ("overview", "infrastructure_assets", "utility_channels", "data_contracts", "kernel_gate", "map")


class InfrastructureNetworkReadinessService:
    def __init__(self, root: Path):
        self._payloads = {name: json.loads((Path(root) / f"{name}.json").read_text()) for name in FILES}
        bundle_ids = {payload.get("bundle_id") for payload in self._payloads.values()}
        if len(bundle_ids) != 1 or None in bundle_ids: raise ValueError("infrastructure_network_bundle_mismatch")

    def overview(self): return deepcopy(self._payloads["overview"])
    def infrastructure_assets(self): return deepcopy(self._payloads["infrastructure_assets"])
    def utility_channels(self): return deepcopy(self._payloads["utility_channels"])
    def data_contracts(self): return deepcopy(self._payloads["data_contracts"])
    def kernel_gate(self): return deepcopy(self._payloads["kernel_gate"])
    def map_payload(self): return deepcopy(self._payloads["map"])

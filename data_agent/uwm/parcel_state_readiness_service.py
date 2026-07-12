from copy import deepcopy
import json
from pathlib import Path


FILES = ("overview", "source_assets", "state_channels", "data_contracts", "state_gate", "map")


class ParcelStateReadinessService:
    def __init__(self, root: Path):
        self._payloads = {name: json.loads((Path(root) / f"{name}.json").read_text()) for name in FILES}
        bundle_ids = {payload.get("bundle_id") for payload in self._payloads.values()}
        if len(bundle_ids) != 1 or None in bundle_ids: raise ValueError("parcel_state_bundle_mismatch")

    def overview(self): return deepcopy(self._payloads["overview"])
    def source_assets(self): return deepcopy(self._payloads["source_assets"])
    def state_channels(self): return deepcopy(self._payloads["state_channels"])
    def data_contracts(self): return deepcopy(self._payloads["data_contracts"])
    def state_gate(self): return deepcopy(self._payloads["state_gate"])
    def map_payload(self): return deepcopy(self._payloads["map"])

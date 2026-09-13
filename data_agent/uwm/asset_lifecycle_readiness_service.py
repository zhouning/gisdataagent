from copy import deepcopy
import json
from pathlib import Path


FILES = ("overview", "source_products", "lifecycle_channels", "data_contracts", "lifecycle_gate", "map")


class AssetLifecycleReadinessService:
    def __init__(self, root: Path):
        self._payloads = {name: json.loads((Path(root) / f"{name}.json").read_text()) for name in FILES}
        bundle_ids = {payload.get("bundle_id") for payload in self._payloads.values()}
        if len(bundle_ids) != 1 or None in bundle_ids:
            raise ValueError("asset_lifecycle_bundle_mismatch")

    def overview(self): return deepcopy(self._payloads["overview"])
    def source_products(self): return deepcopy(self._payloads["source_products"])
    def lifecycle_channels(self): return deepcopy(self._payloads["lifecycle_channels"])
    def data_contracts(self): return deepcopy(self._payloads["data_contracts"])
    def lifecycle_gate(self): return deepcopy(self._payloads["lifecycle_gate"])
    def map_payload(self): return deepcopy(self._payloads["map"])

from copy import deepcopy
import json
from pathlib import Path
FILES=("overview","evidence_products","demographic_channels","data_contracts","population_gate","map")
class PopulationDemographicReadinessService:
    def __init__(self,root:Path):
        self._payloads={name:json.loads((Path(root)/f"{name}.json").read_text()) for name in FILES}
        ids={payload.get("bundle_id") for payload in self._payloads.values()}
        if len(ids)!=1 or None in ids:raise ValueError("population_demographic_bundle_mismatch")
    def overview(self):return deepcopy(self._payloads["overview"])
    def evidence_products(self):return deepcopy(self._payloads["evidence_products"])
    def demographic_channels(self):return deepcopy(self._payloads["demographic_channels"])
    def data_contracts(self):return deepcopy(self._payloads["data_contracts"])
    def population_gate(self):return deepcopy(self._payloads["population_gate"])
    def map_payload(self):return deepcopy(self._payloads["map"])

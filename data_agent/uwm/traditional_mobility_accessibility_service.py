from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path


class TraditionalMobilityAccessibilityService:
    def __init__(self, product_dir: Path):
        root=Path(product_dir)
        self._overview=_read(root/"overview.json"); self._admin=_read(root/"admin_units.json"); self._channels=_read(root/"channel_readiness.json"); self._map=_read(root/"map.json")
        bundle_ids={payload.get("bundle_id") for payload in (self._overview,self._admin,self._channels,self._map)}
        if len(bundle_ids)!=1 or None in bundle_ids: raise ValueError("mobility_product_bundle_mismatch")
        self._rows={str(row["admin_unit_id"]):row for row in self._admin.get("admin_units") or []}

    def overview(self):
        result=deepcopy(self._overview); result["channel_readiness"]=deepcopy(self._channels["channels"]); return result
    def admin_units(self): return {"schema":self._admin.get("schema"),"bundle_id":self._admin.get("bundle_id"),"count":len(self._rows),"admin_units":deepcopy(list(self._rows.values()))}
    def admin_unit(self,admin_unit_id:str):
        if admin_unit_id not in self._rows: raise KeyError("mobility_admin_unit_not_found")
        return deepcopy(self._rows[admin_unit_id])
    def map_payload(self): return deepcopy(self._map)


def _read(path:Path):
    payload=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload,dict): raise ValueError("mobility_product_payload_must_be_object")
    return payload

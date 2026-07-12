from copy import deepcopy
import json
from pathlib import Path
class TraditionalSafetyComfortService:
 def __init__(self,root:Path):
  root=Path(root);self._overview=_read(root/'overview.json');self._admins=_read(root/'admin_units.json');self._channels=_read(root/'channel_readiness.json');self._sources=_read(root/'evidence_sources.json');self._map=_read(root/'map.json');ids={x.get('bundle_id') for x in (self._overview,self._admins,self._channels,self._sources,self._map)}
  if len(ids)!=1 or None in ids:raise ValueError('safety_comfort_product_bundle_mismatch')
  self._rows={str(x['admin_unit_id']):x for x in self._admins['admin_units']}
 def overview(self):r=deepcopy(self._overview);r['channel_readiness']=deepcopy(self._channels['channel_readiness']);return r
 def admin_units(self):return {'schema':self._admins['schema'],'bundle_id':self._admins['bundle_id'],'count':len(self._rows),'admin_units':deepcopy(list(self._rows.values()))}
 def admin_unit(self,aid):
  if aid not in self._rows:raise KeyError('safety_comfort_admin_unit_not_found')
  return deepcopy(self._rows[aid])
 def evidence_sources(self):return {'schema':self._sources['schema'],'bundle_id':self._sources['bundle_id'],'count':len(self._sources['evidence_sources']),'evidence_sources':deepcopy(self._sources['evidence_sources'])}
 def map_payload(self):return deepcopy(self._map)
def _read(p):
 d=json.loads(p.read_text())
 if not isinstance(d,dict):raise ValueError('safety_comfort_payload_must_be_object')
 return d

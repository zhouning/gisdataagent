from copy import deepcopy
import json
from pathlib import Path
VIEWS={'building_morphology_context','population_context','housing_evidence_readiness'}
class TraditionalHousingCommunityService:
 def __init__(self,root:Path):
  root=Path(root);self._overview=_read(root/'overview.json');self._admins=_read(root/'admin_units.json');self._channels=_read(root/'channel_readiness.json');self._sources=_read(root/'evidence_sources.json');self._map=_read(root/'map.json');ids={x.get('bundle_id') for x in (self._overview,self._admins,self._channels,self._sources,self._map)}
  if len(ids)!=1 or None in ids:raise ValueError('housing_community_product_bundle_mismatch')
  self._rows={str(x['admin_unit_id']):x for x in self._admins['admin_units']}
 def overview(self):
  r=deepcopy(self._overview);r['channel_readiness']=deepcopy(self._channels['channel_readiness']);r['evidence_sources']=deepcopy(self._sources['evidence_sources']);return r
 def admin_units(self,view=None):
  if view and view not in VIEWS:raise ValueError('housing_community_view_invalid')
  return {'schema':self._admins['schema'],'bundle_id':self._admins['bundle_id'],'view':view,'count':len(self._rows),'admin_units':deepcopy(list(self._rows.values()))}
 def admin_unit(self,aid):
  if aid not in self._rows:raise KeyError('housing_community_admin_unit_not_found')
  return deepcopy(self._rows[aid])
 def readiness(self):return deepcopy(self._channels)
 def map_payload(self,view=None):
  if view and view not in VIEWS:raise ValueError('housing_community_view_invalid')
  r=deepcopy(self._map)
  if view:r['layers']=[layer for layer in r.get('layers',[]) if any(f.get('properties',{}).get('view')==view for f in layer.get('geojsonData',{}).get('features',[]))]
  r['view']=view;return r
def _read(path):
 d=json.loads(path.read_text())
 if not isinstance(d,dict):raise ValueError('housing_community_payload_must_be_object')
 return d

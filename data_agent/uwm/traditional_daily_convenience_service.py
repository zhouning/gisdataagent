from copy import deepcopy
import json
from pathlib import Path
VIEWS={'daily_convenience','business_activity_evidence'}
class TraditionalDailyConvenienceService:
 def __init__(self,root:Path):
  root=Path(root);self._overview=_read(root/'overview.json');self._places=_read(root/'places.json');self._admins=_read(root/'admin_units.json');self._channels=_read(root/'channel_readiness.json');self._map=_read(root/'map.json');ids={x.get('bundle_id') for x in (self._overview,self._places,self._admins,self._channels,self._map)}
  if len(ids)!=1 or None in ids:raise ValueError('daily_convenience_product_bundle_mismatch')
  self._rows={str(x['admin_unit_id']):x for x in self._admins['admin_units']}
 def overview(self):r=deepcopy(self._overview);r['channel_readiness']=deepcopy(self._channels['channel_readiness']);return r
 def places(self,view):
  if view not in VIEWS:raise ValueError('daily_convenience_view_invalid')
  rows=[x for x in self._places['places'] if view in x['view_membership']];return {'schema':self._places['schema'],'bundle_id':self._places['bundle_id'],'view':view,'count':len(rows),'places':deepcopy(rows),'excluded_record_count':len(self._places.get('excluded_records',[]))}
 def admin_units(self):return {'schema':self._admins['schema'],'bundle_id':self._admins['bundle_id'],'count':len(self._rows),'admin_units':deepcopy(list(self._rows.values()))}
 def admin_unit(self,aid):
  if aid not in self._rows:raise KeyError('daily_convenience_admin_unit_not_found')
  return deepcopy(self._rows[aid])
 def map_payload(self,view=None):
  if view and view not in VIEWS:raise ValueError('daily_convenience_view_invalid')
  result=deepcopy(self._map)
  if view:result['layers']=[x for x in result.get('layers',[]) if any(f.get('properties',{}).get('view')==view for f in x.get('geojsonData',{}).get('features',[]))]
  result['view']=view;return result
def _read(p):
 d=json.loads(p.read_text())
 if not isinstance(d,dict):raise ValueError('daily_convenience_payload_must_be_object')
 return d

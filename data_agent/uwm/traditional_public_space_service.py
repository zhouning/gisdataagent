from copy import deepcopy
import json
from pathlib import Path
CATEGORIES={'core_open_space','civic_cultural_space','public_recreation_space'}
class TraditionalPublicSpaceService:
 def __init__(self,root:Path):
  root=Path(root);self._overview=_read(root/'overview.json');self._spaces=_read(root/'spaces.json');self._admins=_read(root/'admin_units.json');self._channels=_read(root/'channel_readiness.json');self._map=_read(root/'map.json');ids={x.get('bundle_id') for x in (self._overview,self._spaces,self._admins,self._channels,self._map)}
  if len(ids)!=1 or None in ids:raise ValueError('public_space_product_bundle_mismatch')
  self._rows={str(x['admin_unit_id']):x for x in self._admins['admin_units']}
 def overview(self):r=deepcopy(self._overview);r['channel_readiness']=deepcopy(self._channels['channel_readiness']);return r
 def spaces(self,category=None):
  if category and category not in CATEGORIES:raise ValueError('public_space_category_invalid')
  rows=[x for x in self._spaces['spaces'] if not category or x['canonical_space_category']==category];return {'schema':self._spaces['schema'],'bundle_id':self._spaces['bundle_id'],'category':category,'count':len(rows),'spaces':deepcopy(rows),'excluded_record_count':len(self._spaces.get('excluded_records',[]))}
 def admin_units(self):return {'schema':self._admins['schema'],'bundle_id':self._admins['bundle_id'],'count':len(self._rows),'admin_units':deepcopy(list(self._rows.values()))}
 def admin_unit(self,aid):
  if aid not in self._rows:raise KeyError('public_space_admin_unit_not_found')
  return deepcopy(self._rows[aid])
 def map_payload(self,category=None):
  if category and category not in CATEGORIES:raise ValueError('public_space_category_invalid')
  result=deepcopy(self._map)
  if category:
   for layer in result.get('layers',[]):layer['geojsonData']['features']=[x for x in layer['geojsonData'].get('features',[]) if x.get('properties',{}).get('canonical_space_category')==category]
  result['category']=category;return result
def _read(p):
 d=json.loads(p.read_text(encoding='utf-8'))
 if not isinstance(d,dict):raise ValueError('public_space_payload_must_be_object')
 return d

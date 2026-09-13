from copy import deepcopy
import json
from pathlib import Path
VALID_VIEWS={'social_infrastructure','government_public_service'}
class TraditionalSocialPublicServiceService:
 def __init__(self,product_dir:Path):
  root=Path(product_dir);self._overview=_read(root/'overview.json');self._facilities=_read(root/'facilities.json');self._admin=_read(root/'admin_units.json');self._readiness=_read(root/'channel_readiness.json');self._map=_read(root/'map.json')
  ids={x.get('bundle_id') for x in (self._overview,self._facilities,self._admin,self._readiness,self._map)}
  if len(ids)!=1 or None in ids:raise ValueError('social_public_service_product_bundle_mismatch')
  self._rows={str(x['admin_unit_id']):x for x in self._admin['admin_units']}
 def overview(self):
  r=deepcopy(self._overview);r['channel_readiness']=deepcopy(self._readiness['channel_readiness']);return r
 def facilities(self,view:str):
  _view(view);rows=[x for x in self._facilities['facilities'] if view in x.get('view_membership',[])];return {'schema':self._facilities['schema'],'bundle_id':self._facilities['bundle_id'],'view':view,'count':len(rows),'facilities':deepcopy(rows)}
 def admin_units(self,view:str):
  _view(view);rows=[{**deepcopy(x),'view':deepcopy(x[view])} for x in self._rows.values()];return {'schema':self._admin['schema'],'bundle_id':self._admin['bundle_id'],'view_name':view,'count':len(rows),'admin_units':rows}
 def admin_unit(self,admin_unit_id:str,view:str):
  _view(view)
  if admin_unit_id not in self._rows:raise KeyError('social_public_service_admin_unit_not_found')
  row=deepcopy(self._rows[admin_unit_id]);row['view']=deepcopy(row[view]);return row
 def map_payload(self,view:str|None=None):
  if view:_view(view)
  result=deepcopy(self._map)
  if view:
   for layer in result.get('layers',[]):
    features=layer.get('geojsonData',{}).get('features',[]);layer['geojsonData']['features']=[x for x in features if view in x.get('properties',{}).get('view_membership',[])]
  result['view']=view;return result
def _view(view):
 if view not in VALID_VIEWS:raise ValueError('social_public_service_view_invalid')
def _read(path):
 p=json.loads(path.read_text(encoding='utf-8'))
 if not isinstance(p,dict):raise ValueError('social_public_service_payload_must_be_object')
 return p

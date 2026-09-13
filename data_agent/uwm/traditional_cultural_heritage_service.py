from copy import deepcopy
import json
from pathlib import Path
TIERS={'confirmed_cultural_place_evidence','heritage_candidate_leads','excluded_ambiguous_records'}
class TraditionalCulturalHeritageService:
 def __init__(self,root:Path):
  root=Path(root);self._overview=_read(root/'overview.json');self._places=_read(root/'places.json');self._admins=_read(root/'admin_units.json');self._channels=_read(root/'channel_readiness.json');self._map=_read(root/'map.json');ids={x.get('bundle_id') for x in (self._overview,self._places,self._admins,self._channels,self._map)}
  if len(ids)!=1 or None in ids:raise ValueError('cultural_heritage_product_bundle_mismatch')
  self._rows={str(x['admin_unit_id']):x for x in self._admins['admin_units']}
 def overview(self):r=deepcopy(self._overview);r['channel_readiness']=deepcopy(self._channels['channel_readiness']);return r
 def places(self,tier=None,category=None):
  if tier and tier not in TIERS:raise ValueError('cultural_heritage_tier_invalid')
  rows=[x for x in self._places['places'] if (not tier or x['evidence_tier']==tier) and (not category or x.get('canonical_category')==category)];return {'schema':self._places['schema'],'bundle_id':self._places['bundle_id'],'tier':tier,'category':category,'count':len(rows),'places':deepcopy(rows)}
 def admin_units(self):return {'schema':self._admins['schema'],'bundle_id':self._admins['bundle_id'],'count':len(self._rows),'admin_units':deepcopy(list(self._rows.values()))}
 def admin_unit(self,aid):
  if aid not in self._rows:raise KeyError('cultural_heritage_admin_unit_not_found')
  return deepcopy(self._rows[aid])
 def map_payload(self,tier=None):
  if tier and tier not in TIERS:raise ValueError('cultural_heritage_tier_invalid')
  r=deepcopy(self._map)
  if tier:r['layers']=[x for x in r.get('layers',[]) if any(f.get('properties',{}).get('evidence_tier')==tier for f in x.get('geojsonData',{}).get('features',[]))]
  r['tier']=tier;return r
def _read(p):
 d=json.loads(p.read_text())
 if not isinstance(d,dict):raise ValueError('cultural_heritage_payload_must_be_object')
 return d

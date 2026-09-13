from copy import deepcopy
import json
from pathlib import Path
FILES=('overview','source_products','comparability_matrix','priority_units','dependency_graph','map')
class CrossDomainImpactService:
 def __init__(self,root:Path):
  self._p={n:_read(Path(root)/f'{n}.json') for n in FILES};ids={x.get('bundle_id') for x in self._p.values()}
  if len(ids)!=1 or None in ids:raise ValueError('cross_domain_impact_bundle_mismatch')
 def overview(self):return deepcopy(self._p['overview'])
 def source_products(self):return deepcopy(self._p['source_products'])
 def comparability(self):return deepcopy(self._p['comparability_matrix'])
 def priority_units(self):return deepcopy(self._p['priority_units'])
 def dependencies(self):return deepcopy(self._p['dependency_graph'])
 def map_payload(self):return deepcopy(self._p['map'])
def _read(p):
 d=json.loads(p.read_text())
 if not isinstance(d,dict):raise ValueError('cross_domain_payload_must_be_object')
 return d

from copy import deepcopy
import json
from pathlib import Path
FILES=('overview','platform_operations','customer_channels','data_contracts','uwm_gate','map')
class OperationsQualityService:
 def __init__(self,root:Path):
  self._p={n:json.loads((Path(root)/f'{n}.json').read_text()) for n in FILES};ids={x.get('bundle_id') for x in self._p.values()}
  if len(ids)!=1 or None in ids:raise ValueError('operations_quality_bundle_mismatch')
 def overview(self):return deepcopy(self._p['overview'])
 def platform_operations(self):return deepcopy(self._p['platform_operations'])
 def customer_channels(self):return deepcopy(self._p['customer_channels'])
 def data_contracts(self):return deepcopy(self._p['data_contracts'])
 def uwm_gate(self):return deepcopy(self._p['uwm_gate'])
 def map_payload(self):return deepcopy(self._p['map'])

from copy import deepcopy
import json
from pathlib import Path
FILES=('overview','state','graph','evidence_gates','current_rollout','dependency_chain','map')
class ResilienceKernelService:
 def __init__(self,root:Path):
  self._p={n:json.loads((Path(root)/f'{n}.json').read_text()) for n in FILES};ids={x.get('bundle_id') for x in self._p.values()}
  if len(ids)!=1 or None in ids:raise ValueError('resilience_kernel_bundle_mismatch')
 def overview(self):return deepcopy(self._p['overview'])
 def state(self):return deepcopy(self._p['state'])
 def graph(self):return deepcopy(self._p['graph'])
 def gates(self):return deepcopy(self._p['evidence_gates'])
 def rollout(self):return deepcopy(self._p['current_rollout'])
 def dependencies(self):return deepcopy(self._p['dependency_chain'])
 def map_payload(self):return deepcopy(self._p['map'])

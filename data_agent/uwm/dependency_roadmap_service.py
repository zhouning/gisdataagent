from copy import deepcopy
import json
from pathlib import Path
FILES=('overview','tasks','dependency_graph','domain_chains','gates','map')
class DependencyRoadmapService:
 def __init__(self,root:Path):
  self._p={n:json.loads((Path(root)/f'{n}.json').read_text()) for n in FILES};ids={x.get('bundle_id') for x in self._p.values()}
  if len(ids)!=1 or None in ids:raise ValueError('dependency_roadmap_bundle_mismatch')
 def overview(self):return deepcopy(self._p['overview'])
 def tasks(self,status=None,domain=None):
  rows=self._p['tasks']['tasks'];rows=[x for x in rows if (not status or x['status']==status) and (not domain or x['domain']==domain)];return {'schema':self._p['tasks']['schema'],'bundle_id':self._p['tasks']['bundle_id'],'count':len(rows),'tasks':deepcopy(rows)}
 def dependencies(self):return deepcopy(self._p['dependency_graph'])
 def domains(self):return deepcopy(self._p['domain_chains'])
 def gates(self):return deepcopy(self._p['gates'])
 def map_payload(self):return deepcopy(self._p['map'])

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


FILES = ('overview', 'state', 'graph', 'evidence_gates', 'current_rollout', 'dependency_chain', 'map')


class ResilienceKernelService:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._p = {name: json.loads((self.root / f'{name}.json').read_text(encoding='utf-8')) for name in FILES}
        bundle_ids = {payload.get('bundle_id') for payload in self._p.values()}
        if len(bundle_ids) != 1 or None in bundle_ids:
            raise ValueError('resilience_kernel_bundle_mismatch')
        geometry_path = self.root.parent / 'admin_units/chongqing_township_admin_units.geojson'
        geometry = json.loads(geometry_path.read_text(encoding='utf-8')) if geometry_path.exists() else {'features': []}
        self._geometry_by_place = {
            f"{(feature.get('properties') or {}).get('county', '')}|{(feature.get('properties') or {}).get('township', '')}": feature
            for feature in geometry.get('features') or []
        }
        self._nodes = {str(node['node_id']): node for node in self._p['state'].get('state') or []}

    def overview(self): return deepcopy(self._p['overview'])
    def state(self): return deepcopy(self._p['state'])
    def graph(self): return deepcopy(self._p['graph'])
    def gates(self): return deepcopy(self._p['evidence_gates'])
    def rollout(self): return deepcopy(self._p['current_rollout'])
    def dependencies(self): return deepcopy(self._p['dependency_chain'])
    def map_payload(self): return deepcopy(self._p['map'])

    @staticmethod
    def _place(node_id: str) -> tuple[str, str]:
        parts = node_id.split('|')
        return (parts[0], parts[1]) if len(parts) >= 2 else ('', '')

    def _feature(self, node_id: str) -> dict[str, Any] | None:
        county, township = self._place(node_id)
        source = self._geometry_by_place.get(f'{county}|{township}')
        if not source:
            return None
        feature = deepcopy(source)
        feature.setdefault('properties', {}).update({'node_id': node_id})
        return feature

    def list_nodes(self, search: str = '', limit: int = 100) -> dict[str, Any]:
        query = search.strip().lower()
        rows = []
        for node_id, node in self._nodes.items():
            if query and query not in node_id.lower() and query not in str(node.get('admin_name') or '').lower():
                continue
            coverage = node.get('evidence_coverage') or {}
            rows.append({
                'node_id': node_id,
                'admin_name': node.get('admin_name'),
                'road_segment_count': (node.get('network_context') or {}).get('road_segment_count'),
                'road_length_km': (node.get('network_context') or {}).get('road_length_km'),
                'service_accessibility_score': (node.get('network_context') or {}).get('service_accessibility_score'),
                'evidence_coverage': coverage,
                'geometry_available': self._feature(node_id) is not None,
            })
        rows.sort(key=lambda row: row['node_id'])
        return {'schema': 'uwm.resilience.nodes.v1', 'total': len(rows), 'nodes': rows[:max(1, min(int(limit), 500))]}

    def node_detail(self, node_id: str) -> dict[str, Any]:
        node = self._nodes.get(node_id)
        if not node:
            raise ValueError('resilience_node_not_found')
        gates = self._p['evidence_gates'].get('evidence_gates') or {}
        return {
            'schema': 'uwm.resilience.node.v1',
            'node': deepcopy(node),
            'geometry_available': self._feature(node_id) is not None,
            'closed_mechanisms': [name for name, gate in gates.items() if gate.get('status') != 'open'],
            'map_payload': {
                'schema': 'map_update.v1',
                'summary': {'title': '需求19 韧性状态单元'},
                'layers': [{'name': '需求19目标行政单元', 'type': 'geojson', 'geojsonData': {'type': 'FeatureCollection', 'features': [self._feature(node_id)] if self._feature(node_id) else []}}],
                'metadata': {'node_id': node_id, 'evidence_only': True},
            },
        }

    def scenario_readiness(self, *, node_id: str, hazard_type: str, intervention_type: str) -> dict[str, Any]:
        if node_id not in self._nodes:
            raise ValueError('resilience_node_not_found')
        allowed_hazards = {'flood', 'extreme_heat', 'landslide', 'storm'}
        allowed_interventions = {'evacuation_route', 'emergency_facility', 'infrastructure_hardening', 'cooling_shelter'}
        if hazard_type not in allowed_hazards:
            raise ValueError('hazard_type_not_supported')
        if intervention_type not in allowed_interventions:
            raise ValueError('intervention_type_not_supported')
        gates = self._p['evidence_gates'].get('evidence_gates') or {}
        required_gates = ('hazard_evidence_gate', 'exposure_evidence_gate', 'propagation_evidence_gate', 'recovery_evidence_gate', 'intervention_evidence_gate', 'evaluation_evidence_gate')
        blocked = {name: deepcopy(gates.get(name) or {}) for name in required_gates if (gates.get(name) or {}).get('status') != 'open'}
        return {
            'schema': 'uwm.resilience.scenario_readiness.v1',
            'status': 'blocked',
            'node_id': node_id,
            'hazard_type': hazard_type,
            'intervention_type': intervention_type,
            'reason': 'resilience_dynamic_mechanisms_uncalibrated',
            'blocked_gates': blocked,
            'required_evidence': sorted({item for gate in blocked.values() for item in gate.get('required_evidence') or []}),
            'claim_boundary': '系统拒绝生成灾害损失、传播、恢复时间或干预收益；空间邻接不是灾害传播系数。',
            'map_payload': self.node_detail(node_id)['map_payload'],
        }

#!/usr/bin/env python3
"""Create map-only AAM pond connection diagnostics from the native-run audit.

No model inputs or simulation outputs are changed. Geometry remains at its
actual position; only the point symbol is enlarged for map visibility.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pyogrio
from pyproj import Transformer
from shapely.geometry import mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = Path('/Users/zhouning/Downloads/阿布扎比/AAM_L1_L2_100m_60mm1h_20261016')
DEFAULT_EVIDENCE = ROOT / 'docs/deliverables/AAM_L2_蓄水池连接核查_20261016/evidence'


def build(run: Path, evidence: Path) -> dict:
    audit = json.loads((evidence / 'audit_summary.json').read_text())
    seam = audit['closest_other_component_seam']
    a, b = seam['pond_side_xy'], seam['upstream_side_xy']
    distance = float(seam['distance_m_using_native_coordinates'])
    if not 0.028 < distance < 0.030:
        raise ValueError('Audit no longer describes the expected 2.9 cm seam; review before publishing')
    branch = pd.read_csv(evidence / 'pond_component_links.csv')
    upstream = pd.read_csv(evidence / 'upstream_component_links.csv')
    upstream = upstream[upstream.start_node.eq(seam['upstream_side_node']) | upstream.end_node.eq(seam['upstream_side_node'])]
    selection = {f'C{int(i):06d}': 'pond_side' for i in branch.native_link_index}
    selection.update({f'C{int(i):06d}': 'upstream_side' for i in upstream.native_link_index})
    where = 'native_link_id IN (' + ','.join(f"'{key}'" for key in selection) + ')'
    pipes = pyogrio.read_dataframe(run / 'prepared/map_assets/aam_drainage.fgb', where=where)
    if set(pipes.native_link_id) != set(selection) or len(pipes) != len(selection):
        raise ValueError('Display pipelines do not match the audited native link IDs')
    pipes = pipes.to_crs(4326)
    transform = Transformer.from_crs(32640, 4326, always_xy=True)
    lon, lat = transform.transform((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    ranges = audit['native_reported_series_ranges']
    features = []
    for _, row in pipes.iterrows():
        side = selection[row.native_link_id]
        features.append({
            'type': 'Feature', 'geometry': mapping(row.geometry),
            'properties': {
                'kind': side,
                '位置说明': '塘侧支路 · 当前模型未接上游' if side == 'pond_side' else '上游相邻管段 · 本次计算有来水',
                '源管道编号': row.source_unitid, '模型管段编号': row.native_link_id,
                '结果说明': '塘侧8条管段，原生OUT各输出时刻流量均为0' if side == 'pond_side' else '原生RPT最大流量1.557 m³/s（路由步统计，取绝对值）',
            },
        })
    features.append({
        'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
        'properties': {
            'kind': 'connection_gap', '标注': '模型未连通 · 约2.9cm',
            '问题说明': '建模时两端点按1mm空间键分成两个节点，上游来水不能进入塘侧支路。',
            '模型节点间距_cm': round(distance * 100, 4),
            '塘侧节点': f"N{seam['pond_side_node']:06d}",
            '上游节点': f"N{seam['upstream_side_node']:06d}",
            '塘侧坐标_EPSG32640': f'{a[0]:.3f}, {a[1]:.3f}',
            '上游坐标_EPSG32640': f'{b[0]:.3f}, {b[1]:.3f}',
            '经纬度_WGS84': f'{lon:.8f}, {lat:.8f}',
            '塘侧源管道': 'SW_ASA_SAS_CNL_175403 / C175489',
            '上游源管道': 'SW_ASA_SAS_CNL_175411 / C175497',
            '对应检查井': 'SW_ASA_SAS_MH_97149',
            '上游有来水': f"N004824最大总入流{ranges['N004824_total_inflow_cms']['max']:.3f} m³/s（5分钟输出采样）",
            '塘侧未进水': '蓄水池及塘侧8管在全部原生OUT输出时刻均无入流，600个耦合窗口塘蓄水量均为0。',
            '客户说明': '这是本次模型拓扑未连通的位置；不能据此认定现实管道断裂或蓄水池无效。',
            '符号说明': '红点为放大的位置符号，管线使用真实坐标，未夸大2.9cm间距。',
        },
    })
    bounds = pipes.total_bounds
    metadata = {
        'schema': 'aam.connection_gap_diagnostic.v1',
        'focus_center': [lat, lon], 'focus_zoom': 18,
        'overview_center': [(float(bounds[1]) + float(bounds[3])) / 2, (float(bounds[0]) + float(bounds[2])) / 2],
        'overview_zoom': 16, 'gap_distance_m': distance,
        'pond_side_node': f"N{seam['pond_side_node']:06d}",
        'upstream_side_node': f"N{seam['upstream_side_node']:06d}",
        'pond_side_link_count': len(branch), 'upstream_highlight_link_count': len(upstream),
        'upstream_component': audit['upstream_component'],
        'pond_component': audit['pond_component'],
        'source_evidence': str(evidence), 'applies_to_scenarios': ['L1', 'L2'],
        'model_inputs_changed': False, 'simulation_rerun': False,
        'interpretation': 'Model topology seam, not evidence of a physical pipe break. Both scenarios share this seam.',
    }
    payload = {'type': 'FeatureCollection', 'features': features, 'metadata': metadata}
    target = run / 'prepared/map_assets/aam_connection_gap.geojson'
    temporary = target.with_suffix('.geojson.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(target)
    return {'path': str(target), 'feature_count': len(features), **metadata}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--evidence-dir', type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    print(json.dumps(build(args.run_dir, args.evidence_dir), ensure_ascii=False, indent=2))

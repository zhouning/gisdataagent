#!/usr/bin/env python3
"""Re-run surveyed-data-based design alternatives and publish traceable 1D results.

The parcel and DTM are source data. Pipes, pond and grades are proposed designs,
not existing or approved works. This script never substitutes 1D output for 2D.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import transform

from compile_mussafah_formal_scenarios import parse_external_inflow_report, replace_section, section_spans, sha256

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('/Users/zhouning/Downloads/阿布扎比/flood/解决方案_20260924/下一阶段推进_20260925')
FORMAL = BASE / '正式场景编译_20260926'
DELIVERY = BASE / 'Mussafah00_Gap优化交付_20260926'
OUT = FORMAL / 'actual_review_v2'
SNAPSHOT = Path('/Users/zhouning/.local/share/gisdataagent/private/abu_dhabi_stormwater/pond_planning_mussafah00/snapshots/pond-4b589f50f3b965aefe2d')
DTM = Path('/Users/zhouning/Downloads/阿布扎比/DTM_z40_customer/AUH_DTM_5m_Z40.TIF')
EXE = ROOT / 'external_models/swmm-5.2.4/build-local/bin/runswmm'
L1 = FORMAL / 'MUSSAFAH_SOURCE_MODEL_L1_PROXY'
A = FORMAL / 'MUSSAFAH_L2PLUS_A_PARSONS_REPORT_PO2'


def sections(path):
    lines = path.read_text().splitlines(keepends=True)
    return {k: [r.split(';')[0].split() for r in lines[s:e] if r.split(';')[0].strip()]
            for k, (s, e) in section_spans(lines).items()}


def append(lines, section, rows):
    return replace_section(lines, section, lambda b: b + [' '.join(map(str, r)) + '\n' for r in rows] + ['\n'])


def curve_capacity(points):
    return sum((b[0]-a[0])*(a[1]+b[1])/2 for a, b in zip(points, points[1:]))


def forcing_hash(sec):
    keys = ['[OPTIONS]', '[RAINGAGES]', '[INFLOWS]', '[TIMESERIES]', '[OUTFALLS]', '[DWF]', '[EVAPORATION]']
    return hashlib.sha256(json.dumps({k: sec.get(k, []) for k in keys}, sort_keys=True).encode()).hexdigest()


def design_inputs():
    parcels = json.loads((SNAPSHOT/'parcels.geojson').read_text())
    ft = next(f for f in parcels['features'] if f['properties']['source_fid'] == '167073')
    projector = Transformer.from_crs(4326, 32640, always_xy=True).transform
    parcel = transform(projector, shape(ft['geometry']))
    center = parcel.centroid
    footprint = box(center.x-25, center.y-25, center.x+25, center.y+25)
    assert parcel.buffer(-5).covers(footprint), 'pond must fit within parcel with 5 m setback'
    with rasterio.open(DTM) as ds:
        win = from_bounds(*footprint.bounds, ds.transform).round_offsets().round_lengths()
        z = ds.read(1, window=win, masked=True)
        selected = geometry_mask([mapping(footprint)], out_shape=z.shape,
                                 transform=ds.window_transform(win), invert=True)
        values = z[selected].compressed()
        assert len(values) and np.isfinite(values).all()
        rim = round(float(np.median(values)), 3)
        terrain = {'median_m': rim, 'minimum_m': float(values.min()), 'maximum_m': float(values.max()),
                   'valid_cells': len(values), 'cell_size_m': list(ds.res), 'crs': str(ds.crs)}
    sec = sections(L1/'Mussafah_00.inp')
    nodes = {r[0]: list(map(float, r[1:3])) for r in sec['[COORDINATES]']}
    junctions = {r[0]: r for r in sec['[JUNCTIONS]']}
    up, down = 'CB4512', 'CB4513'
    bottom = round(rim-1.0, 3)
    inlet_length = round(center.distance(Point(nodes[up])), 3)
    outlet_length = round(center.distance(Point(nodes[down])), 3)
    # Side diversion starts above the existing invert, then falls 0.1 m to pond.
    inlet_start = round(max(float(junctions[up][1]), bottom + 0.1), 3)
    inlet_offset = round(inlet_start-float(junctions[up][1]), 3)
    assert bottom > float(junctions[down][1]), 'gravity outlet must have a positive fall'
    points = [[round(float(h), 2), round((44+6*float(h))**2, 6)] for h in np.linspace(0, 1, 21)]
    utility_ft = json.loads((SNAPSHOT/'utilities.geojson').read_text()).get('features', [])
    conflicts = sum(transform(projector, shape(f['geometry'])).intersects(footprint)
                    for f in utility_ft if f.get('geometry'))
    return {'parcel_objectid': '167073', 'gisid': ft['properties']['gisid'],
            'parcel_properties': ft['properties'], 'land_use': 'Industrial / showroom',
            'parcel_area_m2': parcel.area, 'parcel_geometry_utm': mapping(parcel),
            'footprint_geometry_utm': mapping(footprint), 'center_utm': [center.x, center.y],
            'top_area_m2': 2500, 'bottom_area_m2': 1936, 'depth_m': 1.0, 'side_slope_h_over_v': 3,
            'exact_frustum_volume_m3': 2212.0, 'swmm_tabular_capacity_m3': curve_capacity(points),
            'curve': points, 'terrain': terrain, 'rim_m': rim, 'bottom_m': bottom,
            'upstream': up, 'downstream': down, 'inlet_length_m': inlet_length,
            'outlet_length_m': outlet_length, 'inlet_start_invert_m': inlet_start,
            'inlet_offset_m': inlet_offset, 'downstream_invert_m': float(junctions[down][1]),
            'inlet_diameter_m': .45, 'utility_footprint_intersection_count': conflicts,
            'design_basis': '塘顶采用地块内客户 DTM 中位高程；入口高位分流，塘底向下游井重力排空。管径和高程为本次提出的设计参数。',
            'constraints': '地块为已分配工业用地，未建设不等于获准建设水塘。5 m 内退范围可容纳塘体；管线路径采用直线设计，路权、全量地下管线与许可未核定。',
            'source_files': {'parcel_snapshot': str(SNAPSHOT/'parcels.geojson'), 'dtm': str(DTM)},
            'parcel_snapshot_sha256': sha256(SNAPSHOT/'parcels.geojson')}


def run_variant(key, diameter, design):
    dest = OUT/key
    dest.mkdir(parents=True, exist_ok=True)
    inp, rpt, out = [dest/f'Mussafah_00.{s}' for s in ['inp', 'rpt', 'out']]
    lines = (L1/'Mussafah_00.inp').read_text().splitlines(keepends=True)
    pond = 'OPT-B-167073'
    lines = append(lines, '[STORAGE]', [[pond, design['bottom_m'], 1, 0, 'TABULAR', 'OPT-B-CURVE', 0, 0, 0]])
    lines = append(lines, '[CURVES]', [['OPT-B-CURVE', 'Storage', *design['curve'][0]]] +
                   [['OPT-B-CURVE', *r] for r in design['curve'][1:]])
    lines = append(lines, '[CONDUITS]', [
        ['OPT-B-IN', design['upstream'], pond, design['inlet_length_m'], .012, design['inlet_offset_m'], 0, 0, 0],
        ['OPT-B-OUT', pond, design['downstream'], design['outlet_length_m'], .012, 0, 0, 0, 0]])
    lines = append(lines, '[XSECTIONS]', [['OPT-B-IN', 'CIRCULAR', .45, 0, 0, 0, 1],
                                        ['OPT-B-OUT', 'CIRCULAR', diameter, 0, 0, 0, 1]])
    # No check valves, pump or invented control law; backwater is solved by SWMM.
    lines = append(lines, '[COORDINATES]', [[pond, *design['center_utm']]])
    compiled = ''.join(lines)
    reusable = inp.is_file() and inp.read_text() == compiled and rpt.is_file() and out.is_file()
    inp.write_text(compiled)
    assert forcing_hash(sections(inp)) == forcing_hash(sections(L1/'Mussafah_00.inp'))
    if reusable:
        reusable = parse_external_inflow_report(rpt.read_text(errors='replace'))['quality']['report_completed_without_errors']
    if not reusable:
        result = subprocess.run([str(EXE), str(inp), str(rpt), str(out)], capture_output=True, text=True, timeout=1800)
        assert result.returncode == 0, result.stderr
    parsed = parse_external_inflow_report(rpt.read_text(errors='replace'))
    assert parsed['quality']['report_completed_without_errors']
    receipt = {'scenario_id': key, 'status': 'completed_actual_swmm', 'engineering_admitted': False,
               'input': {'sha256': sha256(inp), 'design': {**design, 'outlet_diameter_m': diameter}},
               'execution': {'returncode': 0, 'parsed_report': parsed},
               'hashes': {s: sha256(dest/f'Mussafah_00.{s}') for s in ['inp', 'rpt', 'out']}}
    (dest/'scenario_receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(f'{key}: {parsed["node_flooding"]["total_flood_volume_m3"]} m3', flush=True)
    return dest


def load_parser():
    spec = importlib.util.spec_from_file_location('mussafah_out', ROOT/'data_agent/uwm/abu_dhabi_flood/swmm_out_parser.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summarize(key, label, dest, pond_id=None, design=None):
    inp, rpt, out = [dest/f'Mussafah_00.{s}' for s in ['inp', 'rpt', 'out']]
    p = parse_external_inflow_report(rpt.read_text(errors='replace'))
    sec = sections(inp)
    q = p['quality']
    rows = {r['node_id']: r for r in p['node_flooding']['rows']}
    result = {'key': key, 'label': label, 'status': 'completed_actual_swmm',
              'source_dir': str(dest.relative_to(FORMAL)), 'engineering_admitted': False,
              'outputs': {'node_flood_volume_m3': p['node_flooding']['total_flood_volume_m3'],
                          'routing_flooding_loss_m3': q['routing_flooding_loss_m3'],
                          'flooded_node_count': p['node_flooding']['flooded_node_count'],
                          'maximum_ponded_depth_m': p['node_flooding']['maximum_ponded_depth_m'],
                          'continuity_error_percent': p['flow_routing_continuity']['continuity_error_percent'],
                          'steps_not_converging_percent': p['convergence']['steps_not_converging_percent'],
                          'warning_count': q['warning_count'], 'error_count': q['error_count']},
              'routing': p['flow_routing_continuity'], 'nodes': rows, 'design': design,
              'hashes': {s: sha256(dest/f'Mussafah_00.{s}') for s in ['inp', 'rpt', 'out']},
              'forcing_hash': forcing_hash(sec)}
    if pond_id:
        parser = load_parser()
        header = parser.read_swmm_out_header(out)
        assert not header['warning'] and header['flow_units'] == 4
        idx = header['node_names'].index(pond_id)
        timeline = []
        for t in range(header['period_count']):
            period = parser.read_node_period(out, header, t)
            v = period['nodes'][idx]
            timeline.append({'time_h': period['elapsed_minutes']/60, 'depth_m': v[0],
                             'volume_m3': v[2], 'inflow_lps': v[4], 'overflow_lps': v[5]})
        row = next(r for r in sec['[STORAGE]'] if r[0] == pond_id)
        points = [list(map(float, r[-2:])) for r in sec['[CURVES]'] if r[0] == row[5]]
        capacity = curve_capacity(points)
        peak = max(timeline, key=lambda t: t['volume_m3'])
        result['pond'] = {'node_id': pond_id, 'capacity_m3': capacity, 'peak': peak,
                          'final': timeline[-1], 'utilisation_percent': peak['volume_m3']/capacity*100,
                          'timeline': timeline, 'overflow_m3': rows.get(pond_id, {}).get('flood_volume_m3', 0)}
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    design = design_inputs()
    (OUT/'design.json').write_text(json.dumps(design, ensure_ascii=False, indent=2))
    variants = [('B1', .15), ('B2', .30)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(lambda kv: run_variant(*kv, design), variants))
    states = [summarize('L1', 'L1 · 既有管网', L1), summarize('L2', 'L2 · 加入现状塘', FORMAL/'MUSSAFAH_SOURCE_MODEL_L2_PROXY'),
              summarize('A', 'L2+ A · Parsons', A, 'STO-PO3')]
    for (key, diameter), dest in zip(variants, runs):
        states.append(summarize(key, f'L2+ {key} · 自主 / {int(diameter*1000)} mm 出水', dest, 'OPT-B-167073',
                                {**design, 'outlet_diameter_m': diameter}))
    assert len({s['forcing_hash'] for s in states}) == 1, 'forcing or options differ'
    base = states[0]
    for s in states:
        s['deltas'] = {k: s['outputs'][k]-base['outputs'][k] for k in ['node_flood_volume_m3', 'routing_flooding_loss_m3', 'flooded_node_count', 'maximum_ponded_depth_m']}
        union = set(s['nodes']) | set(base['nodes'])
        s['node_changes'] = {'resolved': sum(n in base['nodes'] and n not in s['nodes'] for n in union),
                             'new': sum(n not in base['nodes'] and n in s['nodes'] for n in union),
                             'improved_volume': sum(s['nodes'].get(n, {}).get('flood_volume_m3', 0) < base['nodes'].get(n, {}).get('flood_volume_m3', 0) for n in union),
                             'worsened_volume': sum(s['nodes'].get(n, {}).get('flood_volume_m3', 0) > base['nodes'].get(n, {}).get('flood_volume_m3', 0) for n in union)}
    sec = sections(A/'Mussafah_00.inp')
    nodes = {r[0]: list(map(float, r[1:3])) for r in sec['[COORDINATES]']}
    nodes['OPT-B-167073'] = design['center_utm']
    links = []
    for table in ['[CONDUITS]', '[PUMPS]', '[WEIRS]', '[ORIFICES]']:
        for r in sec.get(table, []):
            if r[1] in nodes and r[2] in nodes:
                links.append({'id': r[0], 'from': r[1], 'to': r[2], 'type': table,
                              'plan': 'A' if r[0] in ['PMP5', '1235'] else 'L1'})
    links += [{'id': 'OPT-B-IN', 'from': design['upstream'], 'to': 'OPT-B-167073', 'plan': 'B'},
              {'id': 'OPT-B-OUT', 'from': 'OPT-B-167073', 'to': design['downstream'], 'plan': 'B'}]
    project = Transformer.from_crs(4326, 32640, always_xy=True).transform
    boundary = json.loads((DELIVERY/'Mussafah00_formal_boundary_20260927.geojson').read_text())
    print('boundary crs', boundary.get('crs'), flush=True)
    geom = shape(boundary['features'][0]['geometry'])
    if geom.bounds[0] < 180: geom = transform(project, geom)
    hotspots = []
    for f in json.loads((SNAPSHOT/'hotspots.geojson').read_text()).get('features', []):
        g = transform(project, shape(f['geometry']))
        if geom.buffer(500).intersects(g):
            hotspots.append({'xy': list(g.centroid.coords[0]), 'properties': f['properties'], 'inside_boundary': geom.covers(g)})
    result = {'version': 'mussafah.actual.v2', 'updated': datetime.now(timezone.utc).isoformat(),
              'status': 'actual_swmm_comparison_complete', 'solver': 'EPA SWMM 5.2.4',
              'scope': {'label': 'Mussafah_00', 'area_ha': geom.area/10000, 'duration_h': 48,
                        'forcing': '咨询模型原始外部入流时序（总量 35,369 m³）；未指定设计重现期',
                        'current_l2_pond_count': 0, 'crs': 'EPSG:32640', 'forcing_sha256': states[0]['forcing_hash'],
                        'historical_points_in_boundary': sum(f['inside_boundary'] for f in hotspots)},
              'states': states, 'candidate': design,
              'map': {'nodes': nodes, 'links': links, 'boundary': mapping(geom), 'hotspots': hotspots},
              'metric_definitions': {'node_flood_volume_m3': 'RPT Node Flooding Summary 累计溢流体积，包含节点地表蓄水；不是系统净损失，也不是二维积水体积。',
                                     'routing_flooding_loss_m3': 'RPT Flow Routing Continuity 的 Flooding Loss：离开当前一维系统的水量。',
                                     'maximum_ponded_depth_m': 'RPT 最大节点地表蓄水深度（相对井顶），不是最大井内水深或二维栅格最大水深。'},
              'limitations': ['所有状态使用同一外部入流、边界与求解设置；尚未按观测校准。',
                              '该次结果不包含双向一二维交换；二维淹没面积、历史积水点消失率没有计算值。',
                              '地块和 DTM 为实际数据；自主塘、管径及连接高程为待审批设计参数，管线路权和冲突尚未核定。',
                              '工程单价和运营成本缺失，不能据此给出最低成本或全局最优结论。'],
              'corrections': ['撤回原 167073 方案的 15.2% 作为主结论：原中心、高程及两点曲线未一致校核。',
                              '本版采用地块真实中心、DTM 中位高程、21 点曲线，重新运行 B1/B2。']}
    (OUT/'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    with (OUT/'comparison.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=['state', *base['outputs']]); writer.writeheader()
        for s in states: writer.writerow({'state': s['label'], **s['outputs']})
    with (OUT/'node_comparison.csv').open('w') as f:
        w=csv.writer(f); w.writerow(['node_id', 'x', 'y', *[s['key']+'_flood_m3' for s in states]])
        for n in sorted(set().union(*(s['nodes'] for s in states))):
            w.writerow([n, *nodes.get(n,[None,None]), *[s['nodes'].get(n,{}).get('flood_volume_m3',0) for s in states]])
    report = [
        '# Mussafah_00 实际模型计算结果（v2）',
        '',
        f'更新：{result["updated"]}。页面：http://localhost:8000/mussafah00-gap',
        '',
        '本次交付包含原始 INP、RPT、OUT、五状态对比 CSV、逐节点 CSV 和完整 JSON。自主 B1/B2 已实际运行 EPA SWMM 5.2.4，未使用旧版理想化二维试验结果。',
        '',
        '## 计算范围与条件',
        '',
        f'- 正式边界面积 {geom.area/10000:.2f} ha；模型保留跨界连接。边界内静态历史积水点 {result["scope"]["historical_points_in_boundary"]} 个。',
        '- L1 为移除已识别规划 STO-PO3/PMP5 链后的源模型基准。其余设施角色仍需完整台账确认。',
        '- 当前边界内现状 pond 查询为 0，按本轮只考虑 pond 的约定，L2 与 L1 相同。',
        '- 五状态使用完全相同的 48 h 外部入流、出水边界和求解设置，已核对哈希。外部入流总量 35,369 m³。原模型 2000 年起算日期是模型时轴，不代表历史事件日期，未绑定设计重现期。',
        '- 本次为一维模型输出，未计算二维淹没面积、历史点消失率或二维最大水深。',
        '',
        '## 实际结果',
        '',
        '| 状态 | 节点累计溢流 m³ | 系统洪涝损失 m³ | 溢流节点 | 最大节点地表蓄水深度 m |',
        '|---|---:|---:|---:|---:|',
    ]
    for s in states:
        o=s['outputs']
        report.append(f'| {s["label"]} | {o["node_flood_volume_m3"]:.0f} | {o["routing_flooding_loss_m3"]:.0f} | {o["flooded_node_count"]} | {o["maximum_ponded_depth_m"]:.3f} |')
    report += ['', '节点累计溢流包含节点地表蓄水；系统洪涝损失指离开一维系统的水量，两者不能混用。最大节点地表蓄水深度相对井顶，不是井内总水深或二维水深。',
               '', 'Parsons 的系统洪涝损失减少 727 m³，但有 34 个节点新报告溢流。自主 B1/B2 分别减少系统损失 23 / 24 m³；两者仅差 1 m³，不能据此确认优劣，也不能将节点累计溢流减少约 13% 当成全域防洪收益。',
               '', '## 自主方案及选址依据', '',
               f'真实地块为 Makani 167073 / GISID {design["gisid"]}，面积 {design["parcel_area_m2"]:.2f} m²。工业/展厅用途，已分配、未建设。塘体完整位于地块 5 m 内退范围内。实际几何中心为 {design["center_utm"]}（EPSG:32640）。',
               '', f'塘顶 2,500 m²，底部 1,936 m²，深 1 m，边坡 3H:1V。按客户 DTM 的塘体范围中位高程设塘顶 {design["rim_m"]:.3f} m、塘底 {design["bottom_m"]:.3f} m。理论库容 2,212 m³，SWMM 21 点曲线积分库容 {design["swmm_tabular_capacity_m3"]:.3f} m³。',
               '', f'入口：CB4512 → 450 mm 管 → OPT-B-167073，拟定长度 {design["inlet_length_m"]:.3f} m，上游管底 {design["inlet_start_invert_m"]:.3f} m。出口：OPT-B-167073 → CB4513，拟定长度 {design["outlet_length_m"]:.3f} m，下游井底 {design["downstream_invert_m"]:.3f} m。B1 出口 150 mm，B2 出口 300 mm；未设置泵或止回阀，回水由 SWMM 计算。',
               '', '选用该配置是因为真实地块可容纳塘体、距既有节点较近，塘底高于下游井底。高位分流用于承接上游高水位来水，小出流配置考察滞蓄，大出流配置考察退水。管线、高程为提出的设计参数，不是已建连接或批准施工设计。',
               '', design['constraints'], '',
               '## 塘内蓄水与退水', '',
               '| 方案 | 峰值蓄水 m³ | 利用率 | 48 h 末蓄水 m³ |', '|---|---:|---:|---:|']
    for s in states[2:]:
        p=s['pond'];report.append(f'| {s["label"]} | {p["peak"]["volume_m3"]:.1f} | {p["utilisation_percent"]:.1f}% | {p["final"]["volume_m3"]:.1f} |')
    report += ['', '峰值为原始 OUT 的 5 分钟报告时刻采样值。Parsons 没有专用排空设施，末场剩余约 809 m³；自主方案在 48 h 后分别剩余约 43 / 25 m³。塘体由一维 Storage 独占计容，本次未修改 DTM。',
               '', '## 质量与未完成项', '',
               '| 状态 | 连续性误差 | 未收敛步比例 | 错误 / 告警 |', '|---|---:|---:|---:|']
    for s in states:
        o=s['outputs'];report.append(f'| {s["label"]} | {o["continuity_error_percent"]:.3f}% | {o["steps_not_converging_percent"]:.2f}% | {o["error_count"]} / {o["warning_count"]} |')
    report += ['', '计算完成，但所有状态未通过未收敛步比例 ≤1% 的数值筛查，因此不声明工程验收通过或最优方案。',
               '', *['- '+x for x in result['limitations']], '',
               '## 修正记录', '', *['- '+x for x in result['corrections']], '',
               '旧版 3,591 m³ / 15.2% 自主结果不再用于本页主结论。原始文件保留作审计，当前主结果为本目录 B1/B2。', '',
               f'统一输入 SHA256：`{states[0]["forcing_hash"]}`。各模型 INP/RPT/OUT 哈希见 comparison.json。']
    (OUT/'comparison_report.md').write_text('\n'.join(report)+'\n')
    print(json.dumps({s['key']: s['outputs'] for s in states}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()

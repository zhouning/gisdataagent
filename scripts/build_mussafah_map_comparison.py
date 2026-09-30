#!/usr/bin/env python3
"""Georeference the audited five-state reports without inventing inundation areas."""
import json
from collections import defaultdict
from datetime import datetime, timezone

from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform

from build_mussafah_review_results import OUT, FORMAL, sections, sha256


def build():
    source = OUT / 'comparison.json'
    data = json.loads(source.read_text())
    project = Transformer.from_crs(data['scope']['crs'], 4326, always_xy=True).transform
    boundary = shape(data['map']['boundary'])
    node_states = defaultdict(dict)
    coords = {}
    links = {}
    hashes = {}
    for state in data['states']:
        key = state['key']
        path = FORMAL / state['source_dir'] / 'Mussafah_00.inp'
        assert sha256(path) == state['hashes']['inp']
        hashes[key] = state['hashes']
        sec = sections(path)
        xy = {r[0]: list(map(float, r[1:3])) for r in sec.get('[COORDINATES]', [])}
        coords.update(xy)
        for table in ['[JUNCTIONS]', '[STORAGE]', '[OUTFALLS]', '[DIVIDERS]']:
            for row in sec.get(table, []):
                n = state['nodes'].get(row[0])
                node_states[row[0]][key] = {
                    'flood_volume_m3': n['flood_volume_m3'] if n else 0,
                    'max_ponded_depth_m': n['max_ponded_depth_m'] if n else 0,
                    'flooding_reported': n is not None,
                    'type': table[1:-1],
                }
        vertices = defaultdict(list)
        for row in sec.get('[VERTICES]', []):
            vertices[row[0]].append(list(map(float, row[1:3])))
        for table in ['[CONDUITS]', '[PUMPS]', '[WEIRS]', '[ORIFICES]', '[OUTLETS]']:
            for row in sec.get(table, []):
                id_, start, end = row[:3]
                if start not in xy or end not in xy:
                    continue
                line = [xy[start], *vertices[id_], xy[end]]
                if id_ in links:
                    assert links[id_]['utm'] == line, f'geometry differs: {id_}'
                else:
                    links[id_] = {'utm': line, 'states': [], 'from': start, 'to': end,
                                  'type': table[1:-1], 'has_vertices': bool(vertices[id_])}
                links[id_]['states'].append(key)

    features = []
    def add(id_, kind, geometry, **props):
        features.append({'type': 'Feature', 'id': id_, 'geometry': mapping(transform(project, shape(geometry))),
                         'properties': {'id': id_, 'kind': kind, **props}})

    add('formal-boundary', 'boundary', mapping(boundary), area_ha=data['scope']['area_ha'])
    missing = []
    for id_, states in node_states.items():
        if id_ not in coords:
            missing.append(id_)
            continue
        xy = coords[id_]
        add(id_, 'node', {'type': 'Point', 'coordinates': xy}, states=states,
            inside_boundary=boundary.covers(Point(xy)))
    for id_, info in links.items():
        add(id_, 'link', {'type': 'LineString', 'coordinates': info['utm']},
            **{k: v for k, v in info.items() if k != 'utm'})
    for i, hotspot in enumerate(data['map']['hotspots']):
        add(f'historical-{i+1}', 'historical', {'type': 'Point', 'coordinates': hotspot['xy']},
            inside_boundary=hotspot['inside_boundary'], source=hotspot['properties'])
    for key, kind in [('parcel_geometry_utm', 'parcel'), ('footprint_geometry_utm', 'pond')]:
        add('167073-' + kind, kind, data['candidate'][key], states=['B1', 'B2'], parcel_id='167073')
    # Parsons is a Storage point in the input; do not fabricate a surveyed pond polygon.
    result = {'type': 'FeatureCollection', 'features': features, 'metadata': {
        'schema': 'mussafah.geographic-comparison.v1', 'crs': 'EPSG:4326',
        'source_crs': data['scope']['crs'], 'source_sha256': sha256(source),
        'source_version': data['version'], 'source_hashes': hashes,
        'created': datetime.now(timezone.utc).isoformat(), 'missing_node_geometry': missing,
        'node_count': len(node_states), 'mapped_node_count': len(node_states)-len(missing),
        'link_count': len(links), 'links_with_source_vertices': sum(x['has_vertices'] for x in links.values()),
        'geometry_basis': 'SWMM COORDINATES/VERTICES + formal GIS boundary + Makani parcel; proposed B pipes use straight design alignments.',
        'result_basis': 'RPT Node Flooding Summary; absent rows mean no reported flooding for a node present in that state. Absent assets are null, not zero.',
        'surface_inundation_available': False,
    }}
    target = OUT / 'map_comparison.geojson'
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    print(json.dumps(result['metadata'], ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    build()

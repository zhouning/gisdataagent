"""Validate geographic overlays against native models and audited reports."""
import json
import sys
from pathlib import Path

import pytest
from pyproj import Transformer
from shapely.geometry import Point, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_mussafah_review_results import OUT, FORMAL, sections, sha256


@pytest.fixture(scope='module')
def pair():
    path = OUT / 'map_comparison.geojson'
    if not path.exists():
        pytest.skip('Customer spatial result package is not installed')
    return json.loads((OUT/'comparison.json').read_text()), json.loads(path.read_text())


def test_map_coordinates_and_boundary_are_in_real_world(pair):
    result, geo = pair
    assert geo['metadata']['source_sha256'] == sha256(OUT/'comparison.json')
    assert not geo['metadata']['missing_node_geometry']
    project = Transformer.from_crs(4326, 32640, always_xy=True)
    boundary = shape(result['map']['boundary'])
    for feature in geo['features']:
        if feature['properties']['kind'] != 'node':
            continue
        lon, lat = feature['geometry']['coordinates']
        assert 54 < lon < 55 and 24 < lat < 25
        xy = project.transform(lon, lat)
        id_ = feature['properties']['id']
        assert xy == pytest.approx(result['map']['nodes'][id_], abs=1e-5)
        assert feature['properties']['inside_boundary'] == boundary.covers(Point(xy))
    assert sum(f['properties'].get('inside_boundary', False) for f in geo['features']
               if f['properties']['kind'] == 'historical') == 3


def test_map_metrics_and_asset_presence_match_each_native_state(pair):
    result, geo = pair
    nodes = [f for f in geo['features'] if f['properties']['kind'] == 'node']
    for s in result['states']:
        sec = sections(FORMAL/s['source_dir']/'Mussafah_00.inp')
        native_ids = {r[0] for table in ['[JUNCTIONS]', '[STORAGE]', '[OUTFALLS]', '[DIVIDERS]']
                      for r in sec.get(table, [])}
        mapped_ids = {f['properties']['id'] for f in nodes if s['key'] in f['properties']['states']}
        assert mapped_ids == native_ids
        total = 0
        reported = 0
        for f in nodes:
            n = f['properties']['states'].get(s['key'])
            if n is None:
                continue
            row = s['nodes'].get(f['properties']['id'])
            assert n['flood_volume_m3'] == (row['flood_volume_m3'] if row else 0)
            assert n['max_ponded_depth_m'] == (row['max_ponded_depth_m'] if row else 0)
            total += n['flood_volume_m3']
            reported += n['flooding_reported']
        assert total == pytest.approx(s['outputs']['node_flood_volume_m3'])
        assert reported == s['outputs']['flooded_node_count']
    by_id = {f['properties']['id']: f for f in nodes}
    assert set(by_id['OPT-B-167073']['properties']['states']) == {'B1', 'B2'}
    assert set(by_id['STO-PO3']['properties']['states']) == {'A'}


def test_map_preserves_source_pipe_vertices_and_proposed_geometry(pair):
    result, geo = pair
    transform = Transformer.from_crs(4326, 32640, always_xy=True)
    links = {f['properties']['id']: f for f in geo['features'] if f['properties']['kind'] == 'link'}
    for s in result['states']:
        sec = sections(FORMAL/s['source_dir']/'Mussafah_00.inp')
        vertices = {}
        for row in sec.get('[VERTICES]', []):
            vertices.setdefault(row[0], []).append(list(map(float, row[1:3])))
        for id_, points in vertices.items():
            mapped = links[id_]['geometry']['coordinates'][1:-1]
            assert len(mapped) == len(points)
            for p, expected in zip(mapped, points):
                assert transform.transform(*p) == pytest.approx(expected, abs=1e-5)
    assert geo['metadata']['surface_inundation_available'] is False
    assert not any(f['properties']['kind'] == 'inundation' for f in geo['features'])

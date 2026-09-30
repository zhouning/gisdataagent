"""Audit the published hydraulic comparison against its native inputs/results."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_mussafah_review_results import OUT, FORMAL, sections, sha256, forcing_hash, curve_capacity
from compile_mussafah_formal_scenarios import parse_external_inflow_report


@pytest.fixture(scope='module')
def bundle():
    path = OUT / 'comparison.json'
    if not path.is_file():
        pytest.skip('Local customer result package is not installed')
    return json.loads(path.read_text())


def test_published_metrics_are_native_report_values(bundle):
    assert {s['key'] for s in bundle['states']} == {'L1', 'L2', 'A', 'B1', 'B2'}
    for state in bundle['states']:
        folder = FORMAL / state['source_dir']
        for ext in ('inp', 'rpt', 'out'):
            assert sha256(folder / f'Mussafah_00.{ext}') == state['hashes'][ext]
        parsed = parse_external_inflow_report((folder/'Mussafah_00.rpt').read_text(errors='replace'))
        assert parsed['quality']['report_completed_without_errors']
        assert state['outputs']['node_flood_volume_m3'] == parsed['node_flooding']['total_flood_volume_m3']
        assert state['outputs']['routing_flooding_loss_m3'] == parsed['quality']['routing_flooding_loss_m3']
        assert state['outputs']['maximum_ponded_depth_m'] == parsed['node_flooding']['maximum_ponded_depth_m']
        assert state['engineering_admitted'] is False


def test_same_forcing_and_no_hidden_baseline_changes(bundle):
    hashes = {forcing_hash(sections(FORMAL/s['source_dir']/'Mussafah_00.inp')) for s in bundle['states']}
    assert hashes == {bundle['scope']['forcing_sha256']}
    assert bundle['states'][0]['outputs'] == bundle['states'][1]['outputs']


def test_candidate_storage_matches_geometry_and_actual_inp(bundle):
    d = bundle['candidate']
    parcel = shape(d['parcel_geometry_utm'])
    footprint = shape(d['footprint_geometry_utm'])
    assert parcel.buffer(-5).covers(footprint)
    assert footprint.area == pytest.approx(2500)
    assert list(parcel.centroid.coords[0]) == pytest.approx(d['center_utm'])
    assert d['rim_m']-d['bottom_m'] == pytest.approx(1)
    assert d['bottom_m'] > d['downstream_invert_m']
    exact = (2500+1936+(2500*1936)**.5)/3
    assert abs(d['swmm_tabular_capacity_m3']-exact) < .02
    for state in bundle['states'][3:]:
        sec = sections(FORMAL/state['source_dir']/'Mussafah_00.inp')
        curve = [list(map(float,r[-2:])) for r in sec['[CURVES]'] if r[0]=='OPT-B-CURVE']
        assert len(curve) == 21
        assert state['pond']['capacity_m3'] == pytest.approx(curve_capacity(curve))
        storage = next(r for r in sec['[STORAGE]'] if r[0]=='OPT-B-167073')
        assert float(storage[1]) == d['bottom_m']
        assert state['pond']['final']['time_h'] == 48


def test_node_change_accounting(bundle):
    base = bundle['states'][0]
    for state in bundle['states']:
        c = state['node_changes']
        assert base['outputs']['flooded_node_count'] - c['resolved'] + c['new'] == state['outputs']['flooded_node_count']
        for key, delta in state['deltas'].items():
            assert delta == pytest.approx(state['outputs'][key]-base['outputs'][key])
        assert state['outputs']['steps_not_converging_percent'] > 1  # must not be published as quality-passed

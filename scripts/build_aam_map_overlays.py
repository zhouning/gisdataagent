#!/usr/bin/env python3
"""Build private AAM map overlays from the run's source GIS and official 506 points.

This only creates display derivatives. It does not change or rerun L1/L2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = Path('/Users/zhouning/Downloads/阿布扎比/AAM_L1_L2_100m_60mm1h_20261016')
SOURCE_LAYERS = ('PIPELINE', 'BOXCULVERT', 'GRATEDCHANNELDRAINAGE')
LAYER_ID = 'aam-stormwater-pipelines-v1'


def write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def build(run_dir: Path, gdb: Path, hotspots: Path) -> dict:
    target = run_dir / 'prepared' / 'map_assets'
    target.mkdir(parents=True, exist_ok=True)
    boundary_path = run_dir / 'prepared' / 'aam_boundary.gpkg'
    boundary = gpd.read_file(boundary_path).to_crs(32640).geometry.union_all()
    mapping = pd.read_csv(run_dir / 'prepared' / 'link_mapping_and_adaptations.csv')
    mapping['native_link_id'] = ['C%06d' % i if included else '' for i, included in enumerate(mapping.included)]
    mapping['source_feature_index'] = mapping.groupby('source_layer').cumcount()
    frames, counts = [], {}
    for layer in SOURCE_LAYERS:
        # Non-Arrow GDAL reading linearizes the FileGDB's occasional curve geometry.
        # Keep all source records until the exact point/line-in-polygon predicate.
        frame = pyogrio.read_dataframe(gdb, layer=layer, columns=['UNITID', 'LineLength'])
        if frame.crs is None:
            raise ValueError(f'{layer}: missing source CRS')
        frame = frame.to_crs(32640)
        frame['source_feature_index'] = range(len(frame))
        source_mapping = mapping[mapping.source_layer.eq(layer)]
        if frame.UNITID.fillna('').tolist() != source_mapping.source_unitid.fillna('').tolist():
            raise ValueError(f'{layer}: source record order differs from the run mapping')
        source_count = len(frame)
        frame = frame[frame.geometry.intersects(boundary)].copy()
        intersect_count = len(frame)
        frame.geometry = shapely.force_2d(frame.geometry.intersection(boundary))
        frame = frame[~frame.geometry.is_empty & (frame.geometry.length > 0)].copy()
        frame['source_layer'] = layer
        frame['source_unitid'] = frame.pop('UNITID')
        frame['source_length_m'] = pd.to_numeric(frame.pop('LineLength'), errors='coerce')
        frame['display_length_m'] = frame.geometry.length
        subset = source_mapping[[
            'source_layer', 'source_feature_index', 'native_link_id', 'included',
            'native_shape', 'height_or_diameter_m', 'width_m',
        ]]
        frame = frame.merge(subset, on=['source_layer', 'source_feature_index'], how='left', validate='one_to_one')
        if frame.included.isna().any():
            raise ValueError(f'{layer}: GIS features are missing from the run mapping')
        frame.rename(columns={'included': 'included_in_native_model'}, inplace=True)
        counts[layer] = {'source_count': source_count, 'intersect_count': intersect_count, 'display_count': len(frame)}
        frames.append(frame)
        print(layer, counts[layer], flush=True)
    network = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=32640)
    network.to_file(target / 'aam_drainage.fgb', driver='FlatGeobuf')

    source = json.loads(hotspots.read_text())
    features = source.get('features', [])
    ids = sorted(f['properties']['hotspot_id'] for f in features)
    if ids != list(range(1, 507)):
        raise ValueError('The official hotspot source must contain IDs 1–506 exactly once')
    points = gpd.GeoDataFrame.from_features(features, crs=4326).to_crs(32640)
    selected = points.geometry.intersects(boundary)
    admitted = []
    for feature, is_inside in zip(features, selected):
        if is_inside:
            admitted.append({**feature, 'properties': {**feature['properties'], 'in_aam': True}})
    hotspot_metadata = {
        'source_total_count': len(features), 'aam_count': len(admitted),
        'outside_aam_count': len(features) - len(admitted),
        'hotspot_ids': [f['properties']['hotspot_id'] for f in admitted],
        'source_file': hotspots.name, 'source_metadata': source.get('metadata', {}),
        'source_file_sha256': hashlib.sha256(hotspots.read_bytes()).hexdigest(),
        'scope': 'AAM 全行政区', 'spatial_predicate': 'intersects (boundary included), EPSG:32640',
        'historical_reference_only': True,
    }
    write_json(target / 'aam_hotspots.geojson', {
        'type': 'FeatureCollection', 'features': admitted, 'metadata': hotspot_metadata,
    })
    bounds = [float(v) for v in network.to_crs(4326).total_bounds]
    manifest = {
        'schema': 'aam.map_overlays.v1', 'boundary_file': str(boundary_path),
        'pipelines': {
            'feature_count': len(network), 'source_count': sum(c['source_count'] for c in counts.values()),
            'included_in_native_model_count': int(network.included_in_native_model.sum()),
            'source_archive': 'DMTStormWater_AlAin_Processed.gdb.zip',
            'source_gdb': str(gdb), 'source_layers': counts, 'crs': 'EPSG:32640',
            'bounds': bounds, 'scope': 'AAM 全行政区',
            'geometry_processing': 'GDAL curve linearization; exact intersection and clipping to AAM; 2D display geometry',
            'layer_id': LAYER_ID, 'source_layer': 'aam_drainage',
            'tile_url': f'/api/tiles/{LAYER_ID}/{{z}}/{{x}}/{{y}}.pbf',
            'metadata_url': f'/api/tiles/{LAYER_ID}/metadata.json',
        },
        'hotspots': hotspot_metadata,
    }
    write_json(target / 'manifest.json', manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--gdb', type=Path, default=ROOT / '.tmp/aam_feasibility_20261016/stormwater.gdb')
    parser.add_argument('--hotspots', type=Path, default=ROOT / 'data_agent/uploads/admin/abu_dhabi_customer_hotspots_506.geojson')
    parser.add_argument('--register-tiles', action='store_true')
    parser.add_argument('--owner', default='admin')
    args = parser.parse_args()
    manifest = build(args.run_dir, args.gdb, args.hotspots)
    if args.register_tiles:
        from dotenv import load_dotenv
        load_dotenv(ROOT / 'data_agent/.env')
        load_dotenv(ROOT / '.env')
        from data_agent.tile_server import create_tile_layer
        meta = create_tile_layer(
            str(args.run_dir / 'prepared/map_assets/aam_drainage.fgb'), args.owner, 'aam_drainage',
            layer_id=LAYER_ID, table_name='_mvt_aam_drainage_v1', expires_at=datetime(2099, 12, 31),
        )
        print('MVT registered:', meta['feature_count'], 'features', flush=True)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

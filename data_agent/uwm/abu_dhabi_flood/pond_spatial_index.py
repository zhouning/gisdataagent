"""Private immutable XY index for large, source-hashed pond GIS snapshots."""
from __future__ import annotations
import hashlib
import json
import math
import sqlite3
from pathlib import Path

from .pond_planning import canonical, load_snapshot, private_root, sha256, write_json


def prepare_spatial_index(snapshot_id: str, *, root: Path | None = None, progress=print) -> dict:
    import shapely
    from shapely.geometry import shape
    from shapely.ops import transform
    from pyproj import Transformer
    manifest, _ = load_snapshot(snapshot_id, root=root, layer_names=set())
    directory = private_root(root) / "snapshots" / snapshot_id
    receipt_path = directory / "spatial_index.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("snapshot_id") == snapshot_id and receipt.get("sha256") == sha256(directory / "spatial.sqlite"):
            return receipt
        raise ValueError("pond_spatial_index_checksum_mismatch")
    temporary = directory / "spatial.build.sqlite"
    if temporary.exists():
        raise ValueError("pond_spatial_index_build_already_exists")
    project = Transformer.from_crs(4326, 32640, always_xy=True).transform
    counts, skipped = {}, {}
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript("""CREATE TABLE features (id INTEGER PRIMARY KEY, layer TEXT NOT NULL, fid TEXT NOT NULL, properties TEXT NOT NULL, geometry BLOB NOT NULL);
            CREATE INDEX feature_layer_fid ON features(layer,fid);
            CREATE VIRTUAL TABLE bounds USING rtree(id,min_x,max_x,min_y,max_y);""")
        index = 0
        for name in sorted(manifest["layers"]):
            _, data = load_snapshot(snapshot_id, root=root, layer_names={name})
            counts[name], skipped[name] = 0, 0
            rows, bounds = [], []
            for feature in data[name]["features"]:
                if feature["geometry"] is None:
                    skipped[name] += 1
                    continue
                geom = transform(project, shapely.force_2d(shape(feature["geometry"])))
                if geom.is_empty or not all(math.isfinite(value) for value in geom.bounds):
                    skipped[name] += 1
                    continue
                index += 1
                props = feature["properties"]
                rows.append((index, name, str(props["source_fid"]), canonical(props).decode(), shapely.to_wkb(geom)))
                x0, y0, x1, y1 = geom.bounds
                bounds.append((index, x0, x1, y0, y1))
                counts[name] += 1
                if len(rows) >= 2000:
                    connection.executemany("INSERT INTO features VALUES (?,?,?,?,?)", rows)
                    connection.executemany("INSERT INTO bounds VALUES (?,?,?,?,?)", bounds)
                    rows, bounds = [], []
            connection.executemany("INSERT INTO features VALUES (?,?,?,?,?)", rows)
            connection.executemany("INSERT INTO bounds VALUES (?,?,?,?,?)", bounds)
            connection.commit()
            progress(json.dumps({"index_layer": name, "rows": counts[name], "skipped_empty_or_missing_geometry": skipped[name]}))
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("pond_spatial_index_integrity_failed")
    finally:
        connection.close()
    temporary.replace(directory / "spatial.sqlite")
    receipt = {"schema": "pond_screening_spatial_index.v1", "snapshot_id": snapshot_id,
               "source_manifest_sha256": sha256(directory / "manifest.json"), "file": "spatial.sqlite",
               "sha256": sha256(directory / "spatial.sqlite"), "crs": "EPSG:32640", "dimensions": "XY",
               "counts": counts, "skipped_empty_or_missing_geometry": skipped,
               "engineering_admitted": False}
    write_json(receipt_path, receipt)
    return receipt


def read_index_context(manifest: dict, bounds: tuple, *, root: Path | None = None) -> dict | None:
    import shapely
    directory = private_root(root) / "snapshots" / manifest["snapshot_id"]
    receipt_path = directory / "spatial_index.json"
    if not receipt_path.exists():
        return None
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("schema") != "pond_screening_spatial_index.v1" or receipt.get("snapshot_id") != manifest["snapshot_id"] or receipt.get("source_manifest_sha256") != sha256(directory / "manifest.json") or receipt.get("sha256") != sha256(directory / "spatial.sqlite"):
        raise ValueError("pond_spatial_index_checksum_mismatch")
    x0, y0, x1, y1 = bounds
    connection = sqlite3.connect((directory / "spatial.sqlite").as_uri() + "?mode=ro", uri=True)
    result = {name: {"_projected_rows": []} for name in manifest["layers"]}
    try:
        for layer, props, geom in connection.execute("""SELECT f.layer,f.properties,f.geometry FROM bounds b JOIN features f ON f.id=b.id
              WHERE b.min_x<=? AND b.max_x>=? AND b.min_y<=? AND b.max_y>=? ORDER BY f.id""", (x1,x0,y1,y0)):
            result[layer]["_projected_rows"].append((json.loads(props), shapely.from_wkb(geom)))
    finally:
        connection.close()
    return result

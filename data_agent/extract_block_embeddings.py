"""Extract AlphaEarth 64D embeddings for Bishan county blocks.

Extracts per-block zonal mean embeddings by sampling within each township's
bounding box, then aggregating to block centroids. Results cached as .npy files.

Usage:
    python -m data_agent.extract_block_embeddings --year 2023
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

CACHE_DIR = Path("results_dual_dreamer_real/embeddings")

TOWNSHIP_BBOXES = {
    "500227001": [106.14, 29.52, 106.24, 29.62],
    "500227002": [106.10, 29.56, 106.22, 29.68],
    "500227100": [106.18, 29.48, 106.28, 29.56],
    "500227101": [106.06, 29.44, 106.16, 29.54],
    "500227102": [106.16, 29.40, 106.28, 29.50],
    "500227103": [106.08, 29.54, 106.18, 29.64],
    "500227104": [106.20, 29.56, 106.32, 29.66],
    "500227105": [106.04, 29.34, 106.18, 29.46],
    "500227106": [106.18, 29.60, 106.30, 29.72],
    "500227107": [106.22, 29.50, 106.34, 29.60],
    "500227108": [106.12, 29.46, 106.22, 29.56],
    "500227109": [106.06, 29.48, 106.16, 29.56],
    "500227200": [106.14, 29.62, 106.26, 29.74],
}


def extract_township_embeddings(township_code: str, bbox: list, year: int = 2023,
                                n_samples: int = 500) -> np.ndarray | None:
    """Extract AlphaEarth embeddings for a township via GEE point sampling.

    Args:
        township_code: e.g. "500227001"
        bbox: [lon_min, lat_min, lon_max, lat_max]
        year: target year
        n_samples: number of random sample points

    Returns:
        (n_samples, 66) array: [lon, lat, 64D embedding] or None on failure
    """
    cache_file = CACHE_DIR / f"township_{township_code}_{year}.npy"
    if cache_file.exists():
        logger.info("Cache hit: %s", cache_file)
        return np.load(str(cache_file))

    try:
        import ee
        try:
            ee.Initialize()
        except Exception:
            ee.Authenticate()
            ee.Initialize()
        from data_agent.world_model import AEF_COLLECTION, AEF_BANDS

        region = ee.Geometry.Rectangle(bbox)
        img = (ee.ImageCollection(AEF_COLLECTION)
               .filterDate(f"{year}-01-01", f"{year}-12-31")
               .filterBounds(region)
               .first()
               .select(AEF_BANDS))

        samples = img.sample(
            region=region,
            scale=10,
            numPixels=n_samples,
            seed=42,
            geometries=True,
        )

        features = samples.getInfo()["features"]
        if not features:
            logger.warning("No samples for %s", township_code)
            return None

        rows = []
        for f in features:
            coords = f["geometry"]["coordinates"]
            props = f["properties"]
            emb = [props.get(b, 0.0) for b in AEF_BANDS]
            rows.append([coords[0], coords[1]] + emb)

        arr = np.array(rows, dtype=np.float32)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        np.save(str(cache_file), arr)
        logger.info("Extracted %d samples for %s → %s", len(arr), township_code, cache_file)
        return arr

    except Exception as e:
        logger.error("Failed to extract %s: %s", township_code, e)
        return None


def aggregate_to_blocks(township_embeddings: dict, block_compositions: dict,
                        parcel_centroids: np.ndarray) -> np.ndarray:
    """Aggregate point-sampled embeddings to block-level zonal means.

    For each block, find the nearest sampled point to each parcel centroid
    and average the embeddings.

    Args:
        township_embeddings: {township_code: (N, 66) array}
        block_compositions: {block_id: [parcel_indices]}
        parcel_centroids: (n_parcels, 2) lon/lat

    Returns:
        (n_blocks, 64) block-level embeddings
    """
    from scipy.spatial import cKDTree

    # Build a single KD-tree from all sampled points
    all_points = []
    all_embs = []
    for code, arr in township_embeddings.items():
        if arr is not None and len(arr) > 0:
            all_points.append(arr[:, :2])
            all_embs.append(arr[:, 2:])

    if not all_points:
        n_blocks = len(block_compositions)
        logger.warning("No embeddings available, returning zeros")
        return np.zeros((n_blocks, 64), dtype=np.float32)

    points = np.vstack(all_points)
    embs = np.vstack(all_embs)
    tree = cKDTree(points)

    n_blocks = len(block_compositions)
    block_embs = np.zeros((n_blocks, 64), dtype=np.float32)

    for bid, parcel_ids in block_compositions.items():
        bid_int = int(bid) if isinstance(bid, str) else bid
        if bid_int >= n_blocks:
            continue
        centroids = parcel_centroids[parcel_ids]
        if len(centroids) == 0:
            continue
        _, indices = tree.query(centroids, k=1)
        block_embs[bid_int] = embs[indices].mean(axis=0)

    return block_embs


def extract_all(year: int = 2023) -> np.ndarray | None:
    """Extract embeddings for all 13 townships and aggregate to blocks.

    Returns:
        (2600, 64) block-level embeddings or None
    """
    logger.info("Extracting AlphaEarth embeddings for all townships, year=%d", year)
    t0 = time.time()

    township_embs = {}
    for code, bbox in TOWNSHIP_BBOXES.items():
        logger.info("Processing %s...", code)
        arr = extract_township_embeddings(code, bbox, year, n_samples=500)
        township_embs[code] = arr
        time.sleep(1)  # rate limit

    n_ok = sum(1 for v in township_embs.values() if v is not None)
    logger.info("Extracted %d/%d townships in %.1fs", n_ok, len(TOWNSHIP_BBOXES), time.time() - t0)

    # Save combined
    out_path = CACHE_DIR / f"all_townships_{year}.npz"
    np.savez_compressed(str(out_path), **{
        k: v for k, v in township_embs.items() if v is not None
    })
    logger.info("Saved to %s", out_path)

    return township_embs


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2023)
    args = parser.parse_args()
    extract_all(args.year)


if __name__ == "__main__":
    main()

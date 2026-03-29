"""
pgvector Embedding Store — cache AlphaEarth embeddings in PostgreSQL.

Provides a three-tier cache: pgvector (ms) → .npy files (ms) → GEE (seconds).
Also enables similarity search across cached regions.
"""

import logging
import os
import time
from typing import Optional

import numpy as np

from .db_engine import get_engine

logger = logging.getLogger(__name__)

Z_DIM = 64  # AlphaEarth embedding dimensionality

# ---------------------------------------------------------------------------
# DDL — Table creation
# ---------------------------------------------------------------------------

_TABLE_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS agent_geo_embeddings (
    id BIGSERIAL PRIMARY KEY,
    area_name VARCHAR(100),
    year INT NOT NULL,
    bbox_minx DOUBLE PRECISION,
    bbox_miny DOUBLE PRECISION,
    bbox_maxx DOUBLE PRECISION,
    bbox_maxy DOUBLE PRECISION,
    grid_h INT,
    grid_w INT,
    pixel_x INT NOT NULL,
    pixel_y INT NOT NULL,
    location GEOMETRY(Point, 4326),
    embedding VECTOR(64) NOT NULL,
    lulc_class INT,
    source VARCHAR(20) DEFAULT 'gee',
    created_at TIMESTAMP DEFAULT NOW()
);
"""

_INDEX_DDL = [
    'CREATE INDEX IF NOT EXISTS idx_geo_emb_area_year ON agent_geo_embeddings(area_name, year)',
    'CREATE INDEX IF NOT EXISTS idx_geo_emb_location ON agent_geo_embeddings USING gist(location)',
    'CREATE INDEX IF NOT EXISTS idx_geo_emb_bbox ON agent_geo_embeddings(bbox_minx, bbox_miny, bbox_maxx, bbox_maxy, year)',
]

# ivfflat index requires data to exist first; created lazily after import
_VECTOR_INDEX_DDL = (
    'CREATE INDEX IF NOT EXISTS idx_geo_emb_vector '
    'ON agent_geo_embeddings USING ivfflat(embedding vector_cosine_ops) WITH (lists = 100)'
)

_tables_ensured = False


def ensure_tables():
    """Create embedding table and indexes if not exists."""
    global _tables_ensured
    if _tables_ensured:
        return
    engine = get_engine()
    if not engine:
        return
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text(_TABLE_DDL))
            for idx in _INDEX_DDL:
                try:
                    conn.execute(text(idx))
                except Exception:
                    pass  # Index may already exist
            conn.commit()
        _tables_ensured = True
        logger.info("[EmbeddingStore] Table ensured")
    except Exception as e:
        logger.warning("[EmbeddingStore] Table creation failed: %s", e)


# ---------------------------------------------------------------------------
# Store embeddings
# ---------------------------------------------------------------------------

def store_grid_embeddings(
    area_name: str,
    year: int,
    bbox: list[float],
    embeddings: np.ndarray,
    lulc_grid: Optional[np.ndarray] = None,
    source: str = "gee",
) -> int:
    """Store a [H, W, 64] embedding grid into pgvector.

    Args:
        area_name: Region identifier (e.g., "yangtze_delta").
        year: Year of the embeddings.
        bbox: [minx, miny, maxx, maxy] in WGS84.
        embeddings: ndarray of shape [H, W, 64].
        lulc_grid: Optional ndarray of shape [H, W] with LULC class labels.
        source: Data source identifier (default "gee").

    Returns:
        Number of rows inserted.
    """
    ensure_tables()
    engine = get_engine()
    if not engine:
        return 0

    h, w = embeddings.shape[0], embeddings.shape[1]
    minx, miny, maxx, maxy = bbox
    dx = (maxx - minx) / w
    dy = (maxy - miny) / h

    t0 = time.time()
    rows = []
    for y_idx in range(h):
        for x_idx in range(w):
            cx = minx + (x_idx + 0.5) * dx
            cy = maxy - (y_idx + 0.5) * dy
            emb = embeddings[y_idx, x_idx, :].tolist()
            lulc = int(lulc_grid[y_idx, x_idx]) if lulc_grid is not None else None
            rows.append({
                "area_name": area_name,
                "year": year,
                "bbox_minx": minx, "bbox_miny": miny,
                "bbox_maxx": maxx, "bbox_maxy": maxy,
                "grid_h": h, "grid_w": w,
                "pixel_x": x_idx, "pixel_y": y_idx,
                "cx": cx, "cy": cy,
                "embedding": str(emb),  # pgvector accepts '[1.0, 2.0, ...]' format
                "lulc_class": lulc,
                "source": source,
            })

    from sqlalchemy import text
    insert_sql = text("""
        INSERT INTO agent_geo_embeddings
            (area_name, year, bbox_minx, bbox_miny, bbox_maxx, bbox_maxy,
             grid_h, grid_w, pixel_x, pixel_y, location, embedding, lulc_class, source)
        VALUES
            (:area_name, :year, :bbox_minx, :bbox_miny, :bbox_maxx, :bbox_maxy,
             :grid_h, :grid_w, :pixel_x, :pixel_y,
             ST_SetSRID(ST_MakePoint(:cx, :cy), 4326),
             CAST(:embedding AS vector), :lulc_class, :source)
    """)

    try:
        with engine.connect() as conn:
            # Batch insert in chunks of 1000
            chunk_size = 1000
            for i in range(0, len(rows), chunk_size):
                conn.execute(insert_sql, rows[i:i + chunk_size])
            conn.commit()

        elapsed = time.time() - t0
        logger.info("[EmbeddingStore] Stored %d embeddings (%s/%d) in %.1fs",
                     len(rows), area_name, year, elapsed)
        return len(rows)
    except Exception as e:
        logger.error("[EmbeddingStore] Store failed: %s", e)
        return 0


# ---------------------------------------------------------------------------
# Load embeddings
# ---------------------------------------------------------------------------

def find_cached_bbox(bbox: list[float], year: int, tolerance: float = 0.001) -> bool:
    """Check if embeddings for a bbox+year exist in the store."""
    engine = get_engine()
    if not engine:
        return False
    ensure_tables()

    from sqlalchemy import text
    sql = text("""
        SELECT COUNT(*) FROM agent_geo_embeddings
        WHERE ABS(bbox_minx - :minx) < :tol
          AND ABS(bbox_miny - :miny) < :tol
          AND ABS(bbox_maxx - :maxx) < :tol
          AND ABS(bbox_maxy - :maxy) < :tol
          AND year = :year
    """)
    try:
        with engine.connect() as conn:
            count = conn.execute(sql, {
                "minx": bbox[0], "miny": bbox[1],
                "maxx": bbox[2], "maxy": bbox[3],
                "year": year, "tol": tolerance
            }).scalar()
        return count > 0
    except Exception:
        return False


def load_grid_embeddings(
    bbox: list[float],
    year: int,
    tolerance: float = 0.001,
) -> Optional[np.ndarray]:
    """Load cached embeddings for a bbox+year from pgvector.

    Returns:
        ndarray of shape [H, W, 64] or None if not cached.
    """
    engine = get_engine()
    if not engine:
        return None
    ensure_tables()

    from sqlalchemy import text
    sql = text("""
        SELECT grid_h, grid_w, pixel_x, pixel_y, embedding::text
        FROM agent_geo_embeddings
        WHERE ABS(bbox_minx - :minx) < :tol
          AND ABS(bbox_miny - :miny) < :tol
          AND ABS(bbox_maxx - :maxx) < :tol
          AND ABS(bbox_maxy - :maxy) < :tol
          AND year = :year
        ORDER BY pixel_y, pixel_x
    """)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, {
                "minx": bbox[0], "miny": bbox[1],
                "maxx": bbox[2], "maxy": bbox[3],
                "year": year, "tol": tolerance
            }).fetchall()

        if not rows:
            return None

        grid_h, grid_w = rows[0][0], rows[0][1]
        grid = np.zeros((grid_h, grid_w, Z_DIM), dtype=np.float32)

        for row in rows:
            px, py = row[2], row[3]
            # Parse pgvector text format: "[0.1,0.2,...,0.64]"
            emb_str = row[4].strip("[]")
            emb = np.fromstring(emb_str, sep=",", dtype=np.float32)
            if len(emb) == Z_DIM and py < grid_h and px < grid_w:
                grid[py, px, :] = emb

        logger.info("[EmbeddingStore] Loaded %dx%d grid (%d rows) for year=%d",
                     grid_h, grid_w, len(rows), year)
        return grid
    except Exception as e:
        logger.debug("[EmbeddingStore] Load failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Similarity search
# ---------------------------------------------------------------------------

def find_similar_embeddings(
    target_embedding: np.ndarray,
    k: int = 10,
    spatial_radius_km: Optional[float] = None,
    center_point: Optional[tuple[float, float]] = None,
) -> list[dict]:
    """Find k most similar embeddings by cosine distance.

    Args:
        target_embedding: [64] vector to search for.
        k: Number of results.
        spatial_radius_km: Optional spatial filter radius in km.
        center_point: Optional (lng, lat) center for spatial filter.

    Returns:
        List of dicts with area_name, year, distance, location, lulc_class.
    """
    engine = get_engine()
    if not engine:
        return []
    ensure_tables()

    from sqlalchemy import text
    emb_str = str(target_embedding.tolist())

    if spatial_radius_km and center_point:
        sql = text(f"""
            SELECT area_name, year, lulc_class,
                   ST_X(location) as lng, ST_Y(location) as lat,
                   embedding <=> :target::vector AS distance
            FROM agent_geo_embeddings
            WHERE ST_DWithin(
                location::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius_m
            )
            ORDER BY embedding <=> :target::vector
            LIMIT :k
        """)
        params = {
            "target": emb_str,
            "lng": center_point[0], "lat": center_point[1],
            "radius_m": spatial_radius_km * 1000,
            "k": k
        }
    else:
        sql = text("""
            SELECT area_name, year, lulc_class,
                   ST_X(location) as lng, ST_Y(location) as lat,
                   embedding <=> :target::vector AS distance
            FROM agent_geo_embeddings
            ORDER BY embedding <=> :target::vector
            LIMIT :k
        """)
        params = {"target": emb_str, "k": k}

    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "area_name": r[0], "year": r[1], "lulc_class": r[2],
                "lng": float(r[3]), "lat": float(r[4]),
                "distance": float(r[5]),
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("[EmbeddingStore] Similarity search failed: %s", e)
        return []


def get_temporal_trajectory(
    lng: float, lat: float, radius_m: float = 500,
) -> dict[int, np.ndarray]:
    """Get temporal embedding trajectory for a location across all cached years.

    Returns:
        Dict mapping year → [64] embedding vector.
    """
    engine = get_engine()
    if not engine:
        return {}
    ensure_tables()

    from sqlalchemy import text
    sql = text("""
        SELECT DISTINCT ON (year) year, embedding::text
        FROM agent_geo_embeddings
        WHERE ST_DWithin(
            location::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            :radius_m
        )
        ORDER BY year, ST_Distance(
            location::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
        )
    """)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, {"lng": lng, "lat": lat, "radius_m": radius_m}).fetchall()

        result = {}
        for row in rows:
            year = row[0]
            emb_str = row[1].strip("[]")
            emb = np.fromstring(emb_str, sep=",", dtype=np.float32)
            if len(emb) == Z_DIM:
                result[year] = emb
        return result
    except Exception as e:
        logger.error("[EmbeddingStore] Temporal query failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Coverage info
# ---------------------------------------------------------------------------

def get_coverage() -> dict:
    """Get summary of cached embedding coverage."""
    engine = get_engine()
    if not engine:
        return {"total_embeddings": 0, "areas": []}
    ensure_tables()

    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM agent_geo_embeddings")).scalar()
            areas = conn.execute(text("""
                SELECT area_name, MIN(year) as min_year, MAX(year) as max_year,
                       COUNT(DISTINCT year) as n_years, COUNT(*) as n_pixels,
                       MIN(bbox_minx) as minx, MIN(bbox_miny) as miny,
                       MAX(bbox_maxx) as maxx, MAX(bbox_maxy) as maxy
                FROM agent_geo_embeddings
                GROUP BY area_name
                ORDER BY area_name
            """)).fetchall()

        return {
            "total_embeddings": total,
            "areas": [
                {
                    "name": r[0], "min_year": r[1], "max_year": r[2],
                    "n_years": r[3], "n_pixels": r[4],
                    "bbox": [float(r[5]), float(r[6]), float(r[7]), float(r[8])],
                }
                for r in areas
            ],
        }
    except Exception as e:
        logger.error("[EmbeddingStore] Coverage query failed: %s", e)
        return {"total_embeddings": 0, "areas": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Import existing .npy cache
# ---------------------------------------------------------------------------

def import_npy_cache(
    raw_data_dir: Optional[str] = None,
    training_areas: Optional[list[dict]] = None,
) -> dict:
    """Import existing .npy embedding cache files into pgvector.

    Args:
        raw_data_dir: Path to .npy cache directory. Defaults to weights/raw_data/.
        training_areas: List of {"name": ..., "bbox": [...]} dicts.

    Returns:
        Summary of imported data.
    """
    if raw_data_dir is None:
        raw_data_dir = os.path.join(os.path.dirname(__file__), "weights", "raw_data")

    if training_areas is None:
        from .world_model import DEFAULT_TRAINING_AREAS, TRAINING_YEARS
        training_areas = DEFAULT_TRAINING_AREAS
        years = TRAINING_YEARS
    else:
        years = list(range(2017, 2025))

    ensure_tables()
    total_imported = 0
    skipped = 0

    for area in training_areas:
        name = area["name"]
        bbox = area["bbox"]

        for year in years:
            # Check if already in store
            if find_cached_bbox(bbox, year):
                skipped += 1
                continue

            # Try pts_ files (point-sampled, [N, 64])
            pts_path = os.path.join(raw_data_dir, f"pts_{name}_{year}.npy")
            if os.path.exists(pts_path):
                pts = np.load(pts_path)
                if pts.ndim == 2 and pts.shape[1] == Z_DIM:
                    # Reshape to [N, 1, 64] grid for storage
                    n = pts.shape[0]
                    grid = pts.reshape(n, 1, Z_DIM)
                    count = store_grid_embeddings(name, year, bbox, grid, source="npy_cache")
                    total_imported += count
                    continue

            # Try emb_ files (grid, [H, W, 64])
            emb_path = os.path.join(raw_data_dir, f"emb_{name}_{year}.npy")
            if os.path.exists(emb_path):
                emb = np.load(emb_path)
                if emb.ndim == 3 and emb.shape[2] == Z_DIM:
                    count = store_grid_embeddings(name, year, bbox, emb, source="npy_cache")
                    total_imported += count

    # Create vector index after bulk import
    try:
        engine = get_engine()
        if engine:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text(_VECTOR_INDEX_DDL))
                conn.commit()
            logger.info("[EmbeddingStore] Vector index created after import")
    except Exception:
        pass  # Index may already exist

    result = {
        "total_imported": total_imported,
        "skipped": skipped,
        "areas": len(training_areas),
    }
    logger.info("[EmbeddingStore] Import complete: %s", result)
    return result

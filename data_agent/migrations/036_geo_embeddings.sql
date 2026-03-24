-- 036: pgvector embedding cache for AlphaEarth geospatial world model
-- Stores 64-dim L2-normalized embeddings with spatial + temporal indexing

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

-- Composite index for cache lookup
CREATE INDEX IF NOT EXISTS idx_geo_emb_area_year
    ON agent_geo_embeddings(area_name, year);

-- Spatial index for bbox/proximity queries
CREATE INDEX IF NOT EXISTS idx_geo_emb_location
    ON agent_geo_embeddings USING gist(location);

-- Approximate nearest neighbor index for similarity search
-- Uses ivfflat with cosine distance (AlphaEarth embeddings are L2-normalized)
CREATE INDEX IF NOT EXISTS idx_geo_emb_vector
    ON agent_geo_embeddings USING ivfflat(embedding vector_cosine_ops)
    WITH (lists = 100);

-- BBox lookup index
CREATE INDEX IF NOT EXISTS idx_geo_emb_bbox
    ON agent_geo_embeddings(bbox_minx, bbox_miny, bbox_maxx, bbox_maxy, year);

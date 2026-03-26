-- Control Points table with PostGIS geometry
-- Run against a PostgreSQL + PostGIS database

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS control_points (
    id SERIAL PRIMARY KEY,
    point_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    geom GEOMETRY(PointZ, 4490) NOT NULL,
    elevation DOUBLE PRECISION,
    datum VARCHAR(50) NOT NULL DEFAULT 'CGCS2000',
    accuracy_class VARCHAR(10) NOT NULL DEFAULT 'C',
    source VARCHAR(200) DEFAULT '国家测绘基准',
    survey_date DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_control_points_geom
    ON control_points USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_control_points_datum
    ON control_points (datum);

COMMENT ON TABLE control_points IS '测绘控制点基准数据表';
COMMENT ON COLUMN control_points.geom IS 'CGCS2000坐标系下的三维点位';
COMMENT ON COLUMN control_points.accuracy_class IS '精度等级: A/B/C/D/E';

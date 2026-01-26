-- SafeMap PostGIS Schema
-- Run this script to create the database schema for POI storage and scoring

-- Enable PostGIS extension (requires superuser or extension already installed)
CREATE EXTENSION IF NOT EXISTS postgis;

-- =============================================================================
-- POI TABLE: Stores all points of interest (fire stations, hospitals, police)
-- =============================================================================
DROP TABLE IF EXISTS poi CASCADE;
CREATE TABLE poi (
    id BIGSERIAL PRIMARY KEY,
    type VARCHAR(50) NOT NULL,          -- 'fire', 'hospital', 'police'
    name VARCHAR(255),
    geom GEOMETRY(Point, 4326) NOT NULL,
    source VARCHAR(100) NOT NULL,       -- 'dsb_wfs', 'osm_overpass', etc.
    source_id VARCHAR(100),             -- Original ID from source (e.g., OSM ID)
    attributes JSONB,                   -- Additional attributes from source
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Spatial index for fast nearest-neighbor queries
CREATE INDEX idx_poi_geom ON poi USING GIST (geom);

-- Index for filtering by type
CREATE INDEX idx_poi_type ON poi (type);

-- Composite index for type + spatial queries
CREATE INDEX idx_poi_type_geom ON poi USING GIST (geom) WHERE type IS NOT NULL;

-- =============================================================================
-- SCORE CACHE: Caches computed scores for clicked points
-- =============================================================================
DROP TABLE IF EXISTS score_cache CASCADE;
CREATE TABLE score_cache (
    id BIGSERIAL PRIMARY KEY,
    geom GEOMETRY(Point, 4326) NOT NULL,
    geohash VARCHAR(12) NOT NULL,       -- For quick lookups of nearby cached points
    model_version VARCHAR(50) NOT NULL,
    score DECIMAL(5,2) NOT NULL,
    breakdown JSONB NOT NULL,           -- Detailed score components
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_score_cache_geohash ON score_cache (geohash, model_version);
CREATE INDEX idx_score_cache_geom ON score_cache USING GIST (geom);

-- =============================================================================
-- GRID CACHE: Caches computed grid cell scores
-- =============================================================================
DROP TABLE IF EXISTS grid_cache CASCADE;
CREATE TABLE grid_cache (
    id BIGSERIAL PRIMARY KEY,
    cell_geom GEOMETRY(Polygon, 4326) NOT NULL,
    resolution_m INTEGER NOT NULL,      -- Cell size in meters (250, 500, 1000, etc.)
    model_version VARCHAR(50) NOT NULL,
    score DECIMAL(5,2) NOT NULL,
    breakdown JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_grid_cache_geom ON grid_cache USING GIST (cell_geom);
CREATE INDEX idx_grid_cache_resolution ON grid_cache (resolution_m, model_version);

-- =============================================================================
-- HELPER FUNCTION: Find nearest POI of each type for a given point
-- =============================================================================
CREATE OR REPLACE FUNCTION find_nearest_pois(
    query_point GEOMETRY(Point, 4326),
    poi_types TEXT[] DEFAULT ARRAY['fire', 'hospital', 'police']
)
RETURNS TABLE (
    poi_type VARCHAR(50),
    poi_id BIGINT,
    poi_name VARCHAR(255),
    distance_m DOUBLE PRECISION
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT ON (p.type)
        p.type,
        p.id,
        p.name,
        ST_Distance(query_point::geography, p.geom::geography) AS distance_m
    FROM poi p
    WHERE p.type = ANY(poi_types)
    ORDER BY p.type, p.geom <-> query_point
    LIMIT array_length(poi_types, 1);
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- DATA INGESTION TRACKING
-- =============================================================================
DROP TABLE IF EXISTS ingestion_log CASCADE;
CREATE TABLE ingestion_log (
    id SERIAL PRIMARY KEY,
    source VARCHAR(100) NOT NULL,
    poi_type VARCHAR(50) NOT NULL,
    record_count INTEGER NOT NULL,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'running', -- 'running', 'success', 'failed'
    error_message TEXT
);

-- =============================================================================
-- EXAMPLE QUERIES (for reference)
-- =============================================================================
/*
-- Find nearest fire station to a point (Oslo sentrum)
SELECT * FROM find_nearest_pois(
    ST_SetSRID(ST_MakePoint(10.75, 59.91), 4326),
    ARRAY['fire', 'hospital', 'police']
);

-- Fast KNN query for nearest hospital
SELECT 
    id, name, 
    ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(10.75, 59.91), 4326)::geography) as dist_m
FROM poi
WHERE type = 'hospital'
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(10.75, 59.91), 4326)
LIMIT 1;

-- Count POIs by type
SELECT type, COUNT(*) FROM poi GROUP BY type;
*/

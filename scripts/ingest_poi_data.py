#!/usr/bin/env python3
"""
SafeMap POI Data Ingestion Script

Fetches POI data from:
1. DSB WFS (Brannstasjoner) - Official Norwegian fire station data
2. OpenStreetMap Overpass API - Hospitals and police stations

Imports all data into PostGIS database.

Usage:
    python ingest_poi_data.py --db-url postgresql://user:pass@localhost:5432/safemap
    
    Or set DATABASE_URL environment variable.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

import psycopg2
from psycopg2.extras import execute_values
import requests
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

OVERPASS_QUERIES = {
    "hospital": """
[out:json][timeout:120];
area["ISO3166-1"="NO"]->.norway;
(
  node["amenity"="hospital"](area.norway);
  way["amenity"="hospital"](area.norway);
  relation["amenity"="hospital"](area.norway);
);
out center;
""",
    "police": """
[out:json][timeout:120];
area["ISO3166-1"="NO"]->.norway;
(
  node["amenity"="police"](area.norway);
  way["amenity"="police"](area.norway);
  relation["amenity"="police"](area.norway);
);
out center;
""",
}

# DSB WFS configuration
DSB_WFS_URL = "https://wfs.geonorge.no/skwms1/wfs.brannstasjoner"
DSB_WFS_PARAMS = {
    "service": "WFS",
    "version": "2.0.0",
    "request": "GetFeature",
    "typeName": "app:Brannstasjon",
    "outputFormat": "application/json",
    "srsName": "EPSG:4326",
}


# =============================================================================
# Data Fetching Functions
# =============================================================================

def fetch_overpass(query: str, poi_type: str) -> list[dict[str, Any]]:
    """Fetch data from Overpass API and extract features."""
    logger.info(f"Fetching {poi_type} from Overpass API...")
    
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=180
    )
    response.raise_for_status()
    data = response.json()
    
    features = []
    for element in data.get("elements", []):
        # Get coordinates
        if element["type"] == "node":
            lat, lon = element["lat"], element["lon"]
        else:
            center = element.get("center", {})
            lat, lon = center.get("lat"), center.get("lon")
            if lat is None or lon is None:
                continue
        
        tags = element.get("tags", {})
        name = tags.get("name", tags.get("name:no", "Unnamed"))
        
        features.append({
            "type": poi_type,
            "name": name,
            "lon": lon,
            "lat": lat,
            "source": "osm_overpass",
            "source_id": f"osm_{element['type']}_{element['id']}",
            "attributes": tags,
        })
    
    logger.info(f"  Found {len(features)} {poi_type} locations")
    return features


def fetch_dsb_fire_stations() -> list[dict[str, Any]]:
    """Fetch fire station data from DSB WFS."""
    logger.info("Fetching fire stations from DSB WFS...")
    
    response = requests.get(DSB_WFS_URL, params=DSB_WFS_PARAMS, timeout=60)
    response.raise_for_status()
    data = response.json()
    
    features = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        
        if geom.get("type") != "Point":
            continue
        
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue
        
        lon, lat = coords[0], coords[1]
        
        # Try different name fields
        name = (
            props.get("navn") or 
            props.get("brannstasjonNavn") or 
            props.get("name") or 
            "Unnamed"
        )
        
        features.append({
            "type": "fire",
            "name": name,
            "lon": lon,
            "lat": lat,
            "source": "dsb_wfs",
            "source_id": str(props.get("id", props.get("gml_id", ""))),
            "attributes": props,
        })
    
    logger.info(f"  Found {len(features)} fire station locations")
    return features


# =============================================================================
# Database Functions
# =============================================================================

def get_db_connection(db_url: str):
    """Create database connection from URL."""
    return psycopg2.connect(db_url)


def clear_poi_table(conn, poi_type: str | None = None) -> None:
    """Clear POI table (optionally filter by type)."""
    with conn.cursor() as cur:
        if poi_type:
            cur.execute("DELETE FROM poi WHERE type = %s", (poi_type,))
            logger.info(f"Cleared existing {poi_type} records")
        else:
            cur.execute("TRUNCATE TABLE poi RESTART IDENTITY CASCADE")
            logger.info("Cleared all POI records")
    conn.commit()


def insert_pois(conn, features: list[dict[str, Any]]) -> int:
    """Insert POI features into database."""
    if not features:
        return 0
    
    insert_sql = """
        INSERT INTO poi (type, name, geom, source, source_id, attributes)
        VALUES %s
    """
    
    values = [
        (
            f["type"],
            f["name"][:255] if f["name"] else None,
            f"SRID=4326;POINT({f['lon']} {f['lat']})",
            f["source"],
            f["source_id"],
            json.dumps(f["attributes"], ensure_ascii=False) if f["attributes"] else None,
        )
        for f in features
    ]
    
    with conn.cursor() as cur:
        execute_values(cur, insert_sql, values, template="""
            (%s, %s, ST_GeomFromEWKT(%s), %s, %s, %s::jsonb)
        """)
    
    conn.commit()
    return len(values)


def log_ingestion(
    conn, 
    source: str, 
    poi_type: str, 
    count: int, 
    started: datetime,
    status: str = "success",
    error: str | None = None
) -> None:
    """Log ingestion run to database."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ingestion_log 
            (source, poi_type, record_count, started_at, completed_at, status, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (source, poi_type, count, started, datetime.now(), status, error))
    conn.commit()


def verify_schema(conn) -> bool:
    """Check if required tables exist."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'poi'
            )
        """)
        return cur.fetchone()[0]


# =============================================================================
# Main Ingestion Logic
# =============================================================================

def run_ingestion(db_url: str, clear_existing: bool = True) -> dict[str, int]:
    """Run full POI data ingestion."""
    
    logger.info("=" * 60)
    logger.info("SAFEMAP POI DATA INGESTION")
    logger.info("=" * 60)
    
    conn = get_db_connection(db_url)
    
    # Verify schema
    if not verify_schema(conn):
        logger.error("Database schema not found. Run database/schema.sql first.")
        sys.exit(1)
    
    results = {}
    
    # Clear existing data if requested
    if clear_existing:
        clear_poi_table(conn)
    
    # 1. Fetch and insert fire stations from DSB
    started = datetime.now()
    try:
        fire_features = fetch_dsb_fire_stations()
        count = insert_pois(conn, fire_features)
        results["fire"] = count
        log_ingestion(conn, "dsb_wfs", "fire", count, started)
        logger.info(f"✅ Inserted {count} fire stations")
    except Exception as e:
        logger.error(f"❌ Failed to ingest fire stations: {e}")
        log_ingestion(conn, "dsb_wfs", "fire", 0, started, "failed", str(e))
        results["fire"] = 0
    
    # 2. Fetch and insert hospitals from Overpass
    started = datetime.now()
    try:
        hospital_features = fetch_overpass(OVERPASS_QUERIES["hospital"], "hospital")
        count = insert_pois(conn, hospital_features)
        results["hospital"] = count
        log_ingestion(conn, "osm_overpass", "hospital", count, started)
        logger.info(f"✅ Inserted {count} hospitals")
    except Exception as e:
        logger.error(f"❌ Failed to ingest hospitals: {e}")
        log_ingestion(conn, "osm_overpass", "hospital", 0, started, "failed", str(e))
        results["hospital"] = 0
    
    # 3. Fetch and insert police stations from Overpass
    started = datetime.now()
    try:
        police_features = fetch_overpass(OVERPASS_QUERIES["police"], "police")
        count = insert_pois(conn, police_features)
        results["police"] = count
        log_ingestion(conn, "osm_overpass", "police", count, started)
        logger.info(f"✅ Inserted {count} police stations")
    except Exception as e:
        logger.error(f"❌ Failed to ingest police stations: {e}")
        log_ingestion(conn, "osm_overpass", "police", 0, started, "failed", str(e))
        results["police"] = 0
    
    conn.close()
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("INGESTION COMPLETE")
    logger.info("=" * 60)
    for poi_type, count in results.items():
        logger.info(f"  {poi_type.upper()}: {count} records")
    logger.info(f"  TOTAL: {sum(results.values())} records")
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Ingest POI data into SafeMap database")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection URL (or set DATABASE_URL env var)"
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Don't clear existing data before ingestion"
    )
    
    args = parser.parse_args()
    
    if not args.db_url:
        logger.error("Database URL required. Use --db-url or set DATABASE_URL")
        logger.error("Example: postgresql://user:password@localhost:5432/safemap")
        sys.exit(1)
    
    run_ingestion(args.db_url, clear_existing=not args.no_clear)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Check database and run ingestion if needed."""
import os
import sys

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import requests
import json

DB_URL = "postgresql://postgres:safemap@127.0.0.1:5433/safemap"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "status.txt")

def log(msg):
    print(msg)
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

# Clear output file
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("=== SafeMap Status Check ===\n")

try:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    log("Database connection: OK")
    
    # Check POI counts
    cur.execute("SELECT type, COUNT(*) FROM poi GROUP BY type ORDER BY type")
    results = cur.fetchall()
    
    if not results:
        log("No POI data found - running ingestion...")
        
        # Fetch hospitals from Overpass
        log("Fetching hospitals from Overpass API...")
        query = """
[out:json][timeout:120];
area["ISO3166-1"="NO"]->.norway;
(node["amenity"="hospital"](area.norway);way["amenity"="hospital"](area.norway););
out center;
"""
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=180)
        data = r.json()
        hospitals = []
        for el in data.get("elements", []):
            if el["type"] == "node":
                lat, lon = el["lat"], el["lon"]
            else:
                c = el.get("center", {})
                lat, lon = c.get("lat"), c.get("lon")
                if not lat: continue
            name = el.get("tags", {}).get("name", "Unnamed")
            hospitals.append((name, lon, lat))
        log(f"  Found {len(hospitals)} hospitals")
        
        # Fetch police from Overpass
        log("Fetching police stations from Overpass API...")
        query = """
[out:json][timeout:120];
area["ISO3166-1"="NO"]->.norway;
(node["amenity"="police"](area.norway);way["amenity"="police"](area.norway););
out center;
"""
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=180)
        data = r.json()
        police = []
        for el in data.get("elements", []):
            if el["type"] == "node":
                lat, lon = el["lat"], el["lon"]
            else:
                c = el.get("center", {})
                lat, lon = c.get("lat"), c.get("lon")
                if not lat: continue
            name = el.get("tags", {}).get("name", "Unnamed")
            police.append((name, lon, lat))
        log(f"  Found {len(police)} police stations")
        
        # Insert data
        log("Inserting POI data into database...")
        for name, lon, lat in hospitals:
            cur.execute("""
                INSERT INTO poi (type, name, geom, source, source_id)
                VALUES ('hospital', %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), 'osm', 'osm')
            """, (name[:255] if name else None, lon, lat))
        
        for name, lon, lat in police:
            cur.execute("""
                INSERT INTO poi (type, name, geom, source, source_id)
                VALUES ('police', %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), 'osm', 'osm')
            """, (name[:255] if name else None, lon, lat))
        
        conn.commit()
        log(f"Inserted {len(hospitals)} hospitals and {len(police)} police stations")
        
        # Recheck counts
        cur.execute("SELECT type, COUNT(*) FROM poi GROUP BY type ORDER BY type")
        results = cur.fetchall()
    
    log(f"POI counts: {dict(results)}")
    total = sum(r[1] for r in results)
    log(f"Total POIs: {total}")
    log("STATUS: OK")
    
    conn.close()
    
except Exception as e:
    log(f"ERROR: {e}")
    import traceback
    log(traceback.format_exc())

#!/usr/bin/env python3
"""Check database status and POI counts."""
import psycopg2

DB_URL = "postgresql://postgres:safemap@localhost:5432/postgres"
output = []

try:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    output.append("Database connection: OK")
    
    # Check if poi table exists
    cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'poi')")
    table_exists = cur.fetchone()[0]
    output.append(f"POI table exists: {table_exists}")
    
    if table_exists:
        # Count POIs by type
        cur.execute("SELECT type, COUNT(*) FROM poi GROUP BY type ORDER BY type")
        results = cur.fetchall()
        output.append(f"POI counts: {results}")
        
        if not results:
            output.append("STATUS: No POI data - need to run ingestion")
        else:
            total = sum(r[1] for r in results)
            output.append(f"Total POIs: {total}")
            output.append("STATUS: Data OK")
    
    conn.close()
    
except Exception as e:
    output.append(f"ERROR: {e}")

# Write results to file
with open("db_status.txt", "w") as f:
    f.write("\n".join(output))

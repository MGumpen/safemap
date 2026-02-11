from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from dotenv import load_dotenv
import os
import psycopg2
import json
import math
from typing import List, Dict, Any
from datetime import datetime, date
from decimal import Decimal

app = FastAPI(title="Safemap API")

# Use absolute paths to ensure it works regardless of where the server is started
BASE_DIR = Path(__file__).resolve().parent

load_dotenv()

USER = os.getenv("user")
PASSWORD = os.getenv("password")
HOST = os.getenv("host")
PORT = os.getenv("port")
DBNAME = os.getenv("dbname")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _find_data_file(filename: str) -> Path:
    candidates = [
        BASE_DIR.parent / "src" / filename,
        BASE_DIR / "data" / filename,
        Path("/src") / filename,
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
def health():
    return {"status": "ok"}


def _get_db_connection():
    if not all([USER, PASSWORD, HOST, PORT, DBNAME]):
        raise ValueError("Database-variabler mangler. Sett user, password, host, port og dbname i .env.")
    return psycopg2.connect(
        user=USER,
        password=PASSWORD,
        host=HOST,
        port=PORT,
        dbname=DBNAME,
    )


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _serialize_for_json(obj):
    """Konverterer objekter til JSON-serialiserbare typer"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, bytes):
        return obj.decode('utf-8', errors='ignore')
    elif isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_serialize_for_json(item) for item in obj]
    return obj


def _load_geojson_points(file_path: Path) -> List[Dict[str, Any]]:
    with open(file_path, "r", encoding="utf-8") as file:
        data = json.load(file)
    points = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        props = feature.get("properties") or {}
        points.append(
            {
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "label": props.get("navn") or props.get("adresse") or "Punkt",
            }
        )
    return points


def _load_shelter_points() -> List[Dict[str, Any]]:
    """Henter tilfluktsrom fra database"""
    try:
        connection = _get_db_connection()
        cursor = connection.cursor()
        
        # Finn tilfluktsrom-tabellen
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE lower(table_name) IN ('tilfluktsrom', 'shelters')
              AND table_schema = 'public'
        """)
        table_row = cursor.fetchone()
        
        if not table_row:
            cursor.close()
            connection.close()
            return []
        
        table_name = table_row[0]
        
        # Få kolonner
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s AND table_schema = 'public'
        """, (table_name,))
        
        column_rows = [row[0] for row in cursor.fetchall()]
        column_map = {name.lower(): name for name in column_rows}
        
        # Finn geometri-kolonne
        geom_column = None
        is_wkt = False
        
        if "wkt_geom" in column_map:
            geom_column = column_map["wkt_geom"]
            is_wkt = True
        else:
            for candidate in ("shape", "geom", "geometry", "point", "location", "wkb_geometry", "the_geom"):
                if candidate in column_map:
                    geom_column = column_map[candidate]
                    break
        
        if not geom_column:
            cursor.close()
            connection.close()
            return []
        
        # Hent data med transformert geometri
        if is_wkt:
            cursor.execute(f"""
                SELECT
                    ST_Y(ST_Transform(ST_GeomFromText("{geom_column}", 25833), 4326)) AS lat,
                    ST_X(ST_Transform(ST_GeomFromText("{geom_column}", 25833), 4326)) AS lon,
                    *
                FROM "{table_name}"
                WHERE "{geom_column}" IS NOT NULL;
            """)
        else:
            cursor.execute(f"""
                SELECT
                    ST_Y(ST_Transform("{geom_column}", 4326)) AS lat,
                    ST_X(ST_Transform("{geom_column}", 4326)) AS lon,
                    *
                FROM "{table_name}";
            """)
        
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        
        points = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            if row_dict.get('lat') and row_dict.get('lon'):
                # Finn label fra ulike mulige kolonner
                label = (row_dict.get('adresse') or 
                        row_dict.get('navn') or 
                        row_dict.get('name') or 
                        "Tilfluktsrom")
                
                points.append({
                    "lat": float(row_dict['lat']),
                    "lon": float(row_dict['lon']),
                    "label": label,
                    "properties": row_dict
                })
        
        cursor.close()
        connection.close()
        return points
        
    except Exception as e:
        print(f"Feil ved henting av tilfluktsrom fra database: {e}")
        return []


@app.get("/api/tilfluktsrom")
@app.get("/api/shelters")
def get_tilfluktsrom():
    """Henter tilfluktsrom fra Supabase database"""
    try:
        connection = _get_db_connection()
        cursor = connection.cursor()
        
        # Finn tilfluktsrom-tabellen
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE lower(table_name) IN ('tilfluktsrom', 'shelters')
              AND table_schema = 'public'
        """)
        table_row = cursor.fetchone()
        
        if not table_row:
            raise ValueError("Fant ikke tilfluktsrom-tabell i databasen.")
        
        table_name = table_row[0]
        
        # Få kolonner
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = %s AND table_schema = 'public'
            ORDER BY ordinal_position
        """, (table_name,))
        
        columns_info = cursor.fetchall()
        print(f"DEBUG: Kolonner i {table_name}:")
        for col_name, col_type in columns_info:
            print(f"  - {col_name}: {col_type}")
        
        column_rows = [row[0] for row in columns_info]
        column_map = {name.lower(): name for name in column_rows}
        
        # Finn geometri-kolonne
        geom_column = None
        is_wkt = False
        
        # Sjekk for WKT-format først
        if "wkt_geom" in column_map:
            geom_column = column_map["wkt_geom"]
            is_wkt = True
            print(f"DEBUG: Fant WKT geometri-kolonne: {geom_column}")
        else:
            # Sjekk vanlige PostGIS kolonner
            for candidate in ("shape", "geom", "geometry", "point", "location", "wkb_geometry", "the_geom", "geog", "geography"):
                if candidate in column_map:
                    geom_column = column_map[candidate]
                    print(f"DEBUG: Fant geometri-kolonne: {geom_column}")
                    break
        
        if not geom_column:
            all_cols = ", ".join(column_map.keys())
            raise ValueError(f"Fant ikke geometri-kolonne. Tilgjengelige kolonner: {all_cols}")
        
        # Hent data - håndter både WKT og PostGIS geometry
        if is_wkt:
            # Konverter WKT til geometry først, deretter til WGS84
            cursor.execute(f"""
                SELECT
                    *,
                    ST_AsGeoJSON(ST_Transform(ST_GeomFromText("{geom_column}", 25833), 4326)) AS geojson,
                    ST_X(ST_Transform(ST_GeomFromText("{geom_column}", 25833), 4326)) AS lon,
                    ST_Y(ST_Transform(ST_GeomFromText("{geom_column}", 25833), 4326)) AS lat
                FROM "{table_name}"
                WHERE "{geom_column}" IS NOT NULL;
            """)
        else:
            # Standard PostGIS geometry
            cursor.execute(f"""
                SELECT
                    *,
                    ST_AsGeoJSON(ST_Transform("{geom_column}", 4326)) AS geojson,
                    ST_X(ST_Transform("{geom_column}", 4326)) AS lon,
                    ST_Y(ST_Transform("{geom_column}", 4326)) AS lat
                FROM "{table_name}";
            """)
        
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        
        cursor.close()
        connection.close()
        
        # Konverter til GeoJSON format
        features = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            if row_dict.get('lat') and row_dict.get('lon'):
                # Fjern interne kolonner fra properties
                properties = {k: v for k, v in row_dict.items() 
                            if k not in ['geojson', 'lat', 'lon', geom_column.lower()]}
                
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [row_dict['lon'], row_dict['lat']]
                    },
                    "properties": properties
                })
        
        return {
            "type": "FeatureCollection",
            "features": features
        }
        
    except Exception as exc:
        return {"error": f"Failed to fetch tilfluktsrom: {exc}"}


@app.get("/api/brannstasjoner")
@app.get("/api/Brannstasjoner")
def get_brannstasjoner():
    try:
        connection = _get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE lower(table_name) = 'brannstasjoner'
              AND table_schema = 'public'
            """
        )
        table_row = cursor.fetchone()
        if not table_row:
            raise ValueError("Fant ikke brannstasjoner-tabell i databasen.")
        table_name = table_row[0]
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s
              AND table_schema = 'public'
            """
            ,
            (table_name,)
        )
        column_rows = [row[0] for row in cursor.fetchall()]
        column_map = {name.lower(): name for name in column_rows}
        geom_column = None
        is_wkt = False
        
        if "wkt_geom" in column_map:
            geom_column = column_map["wkt_geom"]
            is_wkt = True
        else:
            for candidate in ("shape", "geom", "geometry", "wkb_geometry", "the_geom"):
                if candidate in column_map:
                    geom_column = column_map[candidate]
                    break
        
        if not geom_column:
            raise ValueError("Fant ikke geometri-kolonne i brannstasjoner-tabellen.")
        
        if is_wkt:
            cursor.execute(f"""
                SELECT
                    *,
                    ST_AsGeoJSON(ST_Transform(ST_GeomFromText("{geom_column}", 25833), 4326)) AS shape,
                    ST_X(ST_Transform(ST_GeomFromText("{geom_column}", 25833), 4326)) AS lon,
                    ST_Y(ST_Transform(ST_GeomFromText("{geom_column}", 25833), 4326)) AS lat
                FROM "{table_name}"
                WHERE "{geom_column}" IS NOT NULL;
            """)
        else:
            cursor.execute(f"""
                SELECT
                    *,
                    ST_AsGeoJSON(ST_Transform("{geom_column}", 4326)) AS shape,
                    ST_X(ST_Transform("{geom_column}", 4326)) AS lon,
                    ST_Y(ST_Transform("{geom_column}", 4326)) AS lat
                FROM "{table_name}";
            """)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        cursor.close()
        connection.close()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as exc:
        return {"error": f"Failed to fetch brannstasjoner: {exc}"}
    
@app.get("/api/health-institutions")
def get_health_institutions():
    """Henter sykehus fra lokal JSON-fil"""
    
    json_file = _find_data_file("sykehus.json")
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except FileNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": "Sykehus data ikke funnet"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Feil ved lasting av data: {str(e)}"}
        )

@app.get("/api/emergency-clinics")
def get_emergency_clinics():
    """Henter kommunale legevakter fra lokal JSON-fil"""
    
    json_file = _find_data_file("legevakter.json")
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except FileNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": "Legevakt data ikke funnet"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Feil ved lasting av data: {str(e)}"}
        )

@app.get("/api/legevakter")
def get_legevakter():
    """Henter kommunale legevakter fra lokal JSON-fil"""
    
    json_file = _find_data_file("legevakter.json")
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except FileNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": "Legevakt data ikke funnet"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Feil ved lasting av data: {str(e)}"}
        )


@app.get("/api/nearest")
def get_nearest_point(type: str, lat: float, lon: float):
    if type not in {"hospital", "legevakt", "shelter"}:
        return {"error": "Ugyldig type. Bruk hospital, legevakt eller shelter."}

    if type == "hospital":
        points = _load_geojson_points(_find_data_file("sykehus.json"))
    elif type == "legevakt":
        points = _load_geojson_points(_find_data_file("legevakter.json"))
    else:
        points = _load_shelter_points()

    if not points:
        return {"error": "Ingen punkter tilgjengelig."}

    closest = min(points, key=lambda p: _haversine(lat, lon, p["lat"], p["lon"]))
    return closest


@app.get("/api/spatial-filter")
def spatial_filter(lat: float, lon: float, radius_km: float = 5.0):
    """
    Romlig filtrering - Finner alle objekter innenfor en gitt radius fra et punkt.
    
    Args:
        lat: Latitude for senterpunktet
        lon: Longitude for senterpunktet
        radius_km: Radius i kilometer (default 5 km)
    
    Returns:
        JSON med alle objekter innenfor radiusen, kategorisert etter type
    """
    try:
        # Last inn alle datasett
        hospitals = _load_geojson_points(_find_data_file("sykehus.json"))
        legevakter = _load_geojson_points(_find_data_file("legevakter.json"))
        shelters = _load_shelter_points()
        
        # Hent brannstasjoner fra database
        brannstasjoner = []
        try:
            connection = _get_db_connection()
            cursor = connection.cursor()
            
            # Finn tabellnavn
            cursor.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE lower(table_name) = 'brannstasjoner'
                  AND table_schema = 'public'
            """)
            table_row = cursor.fetchone()
            
            if table_row:
                table_name = table_row[0]
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = %s AND table_schema = 'public'
                """, (table_name,))
                
                column_rows = [row[0] for row in cursor.fetchall()]
                column_map = {name.lower(): name for name in column_rows}
                
                geom_column = None
                is_wkt = False
                
                if "wkt_geom" in column_map:
                    geom_column = column_map["wkt_geom"]
                    is_wkt = True
                else:
                    for candidate in ("shape", "geom", "geometry", "wkb_geometry", "the_geom"):
                        if candidate in column_map:
                            geom_column = column_map[candidate]
                            break
                
                if geom_column:
                    if is_wkt:
                        cursor.execute(f"""
                            SELECT
                                ST_Y(ST_Transform(ST_GeomFromText("{geom_column}", 25833), 4326)) AS lat,
                                ST_X(ST_Transform(ST_GeomFromText("{geom_column}", 25833), 4326)) AS lon,
                                *
                            FROM "{table_name}"
                            WHERE "{geom_column}" IS NOT NULL;
                        """)
                    else:
                        cursor.execute(f"""
                            SELECT
                                ST_Y(ST_Transform("{geom_column}", 4326)) AS lat,
                                ST_X(ST_Transform("{geom_column}", 4326)) AS lon,
                                *
                            FROM "{table_name}";
                        """)
                    rows = cursor.fetchall()
                    columns = [desc[0] for desc in cursor.description]
                    
                    for row in rows:
                        row_dict = dict(zip(columns, row))
                        if row_dict.get('lat') and row_dict.get('lon'):
                            # Kun ta med nødvendige felter for å unngå serialiseringsproblemer
                            label = row_dict.get('brannstasjon') or row_dict.get('navn') or "Brannstasjon"
                            brannstasjoner.append({
                                "lat": float(row_dict['lat']),
                                "lon": float(row_dict['lon']),
                                "label": str(label)
                            })
            
            cursor.close()
            connection.close()
        except Exception as db_err:
            print(f"Feil ved henting av brannstasjoner: {db_err}")
        
        # Filtrer alle objekter basert på avstand
        def filter_by_distance(points, category_name):
            filtered = []
            for point in points:
                try:
                    distance = _haversine(lat, lon, point["lat"], point["lon"])
                    if distance <= radius_km:
                        # Sikre at kun serialiserbare data inkluderes
                        filtered_point = {
                            "lat": float(point["lat"]),
                            "lon": float(point["lon"]),
                            "label": str(point.get("label", "Ukjent")),
                            "distance_km": round(distance, 2),
                            "category": category_name
                        }
                        filtered.append(filtered_point)
                except Exception as e:
                    print(f"Feil ved filtrering av punkt: {e}")
                    continue
            return sorted(filtered, key=lambda x: x["distance_km"])
        
        # Filtrer alle datasett
        filtered_hospitals = filter_by_distance(hospitals, "hospital")
        filtered_legevakter = filter_by_distance(legevakter, "legevakt")
        filtered_shelters = filter_by_distance(shelters, "shelter")
        filtered_brannstasjoner = filter_by_distance(brannstasjoner, "brannstasjon")
        
        results = {
            "center": {"lat": float(lat), "lon": float(lon)},
            "radius_km": float(radius_km),
            "results": {
                "hospitals": filtered_hospitals,
                "legevakter": filtered_legevakter,
                "shelters": filtered_shelters,
                "brannstasjoner": filtered_brannstasjoner
            },
            "total_count": len(filtered_hospitals) + len(filtered_legevakter) + len(filtered_shelters) + len(filtered_brannstasjoner)
        }
        
        return JSONResponse(content=results)
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Feil ved romlig filtrering: {str(e)}"}
        )

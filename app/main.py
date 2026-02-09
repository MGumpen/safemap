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
from pyproj import Transformer

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
    shelter_file = BASE_DIR / "static" / "Tilfluktsrom.json"
    if not shelter_file.exists():
        return []
    with open(shelter_file, "r", encoding="utf-8") as file:
        data = json.load(file)
    transformer = Transformer.from_crs(25833, 4326, always_xy=True)
    points = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = transformer.transform(coords[0], coords[1])
        props = feature.get("properties") or {}
        points.append(
            {
                "lat": float(lat),
                "lon": float(lon),
                "label": props.get("adresse") or "Tilfluktsrom",
            }
        )
    return points


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
        for candidate in ("shape", "geom", "geometry"):
            if candidate in column_map:
                geom_column = column_map[candidate]
                break
        if not geom_column:
            raise ValueError("Fant ikke geometri-kolonne i brannstasjoner-tabellen.")
        cursor.execute(
            f"""
            SELECT
                *,
                ST_AsGeoJSON(ST_Transform("{geom_column}", 4326)) AS shape,
                ST_X(ST_Transform("{geom_column}", 4326)) AS lon,
                ST_Y(ST_Transform("{geom_column}", 4326)) AS lat
            FROM "{table_name}";
            """
        )
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

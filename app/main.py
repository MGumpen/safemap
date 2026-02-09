from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from dotenv import load_dotenv
import os
import psycopg2
import json

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

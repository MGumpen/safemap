from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from dotenv import load_dotenv
import os
import psycopg2

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
def get_brannstasjoner():
    try:
        connection = _get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                *,
                ST_AsGeoJSON(ST_Transform("SHAPE", 4326)) AS shape,
                ST_X(ST_Transform("SHAPE", 4326)) AS lon,
                ST_Y(ST_Transform("SHAPE", 4326)) AS lat
            FROM brannstasjoner_brannstasjon;
            """
        )
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        cursor.close()
        connection.close()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as exc:
        return {"error": f"Failed to fetch brannstasjoner: {exc}"}
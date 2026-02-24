from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from dotenv import load_dotenv
import io
import os
import psycopg2
import json
import math
import ssl
import time
import zipfile
from threading import Lock
from typing import List, Dict, Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
from pyproj import Transformer

try:
    import certifi
except ImportError:
    certifi = None

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

# <changeLog>
#   <change date="2026-02-23" author="Codex">
#     <summary>Stabiliserte HTTPS-kall til Geonorge API for tilfluktsrom.</summary>
#     <details>
#       <item>Bruker eksplisitt SSL context med certifi CA-bundle når tilgjengelig.</item>
#       <item>Gir tydelig feilmelding når TLS-sertifikatverifisering feiler.</item>
#       <item>Beholder TLS-verifisering aktivert (ingen usikker bypass).</item>
#     </details>
#   </change>
# </changeLog>


SHELTER_METADATA_UUID = os.getenv("SHELTER_METADATA_UUID", "dbae9aae-10e7-4b75-8d67-7f0e8828f3d8")
SHELTER_CAPABILITIES_URL = os.getenv(
    "SHELTER_CAPABILITIES_URL",
    f"https://nedlasting.geonorge.no/api/capabilities/{SHELTER_METADATA_UUID}",
)
SHELTER_ORDER_URL = os.getenv("SHELTER_ORDER_URL", "https://nedlasting.geonorge.no/api/order")
SHELTER_CACHE_TTL_SECONDS = int(os.getenv("SHELTER_CACHE_TTL_SECONDS", "1800"))
SHELTER_ORDER_STATUS_POLL_ATTEMPTS = int(os.getenv("SHELTER_ORDER_STATUS_POLL_ATTEMPTS", "6"))
SHELTER_ORDER_STATUS_POLL_SECONDS = float(os.getenv("SHELTER_ORDER_STATUS_POLL_SECONDS", "1.0"))

SHELTER_ORDER_AREA = {"code": "0000", "name": "Hele landet", "type": "landsdekkende"}
SHELTER_ORDER_FORMAT = {"name": "GeoJSON"}
SHELTER_ORDER_PROJECTION = {
    "code": "25833",
    "name": "EUREF89 UTM sone 33, 2d",
    "codespace": "http://www.opengis.net/def/crs/EPSG/0/25833",
}

_shelter_cache_lock = Lock()
_shelter_geojson_cache: Dict[str, Any] = {"geojson": None, "expires_at": 0.0}
_shelter_transformer = Transformer.from_crs(25833, 4326, always_xy=True)


def _build_https_ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


_https_ssl_context = _build_https_ssl_context()


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


def _http_json_request(url: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "SafeMap/1.0",
    }
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = UrlRequest(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60, context=_https_ssl_context) as response:
            response_body = response.read()
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} fra Nedlasting API: {error_body}") from exc
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise RuntimeError(
                "Nettverksfeil mot Nedlasting API: TLS-sertifikat kunne ikke verifiseres. "
                "Sørg for gyldig CA-store i runtime (certifi/systemsertifikater)."
            ) from exc
        raise RuntimeError(f"Nettverksfeil mot Nedlasting API: {exc.reason}") from exc
    try:
        return json.loads(response_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Nedlasting API returnerte ugyldig JSON.") from exc


def _http_bytes_request(url: str) -> bytes:
    request = UrlRequest(url, headers={"User-Agent": "SafeMap/1.0"}, method="GET")
    try:
        with urlopen(request, timeout=120, context=_https_ssl_context) as response:
            return response.read()
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} ved nedlasting av tilfluktsrom: {error_body}") from exc
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise RuntimeError(
                "Nettverksfeil ved nedlasting av tilfluktsrom: TLS-sertifikat kunne ikke verifiseres. "
                "Sørg for gyldig CA-store i runtime (certifi/systemsertifikater)."
            ) from exc
        raise RuntimeError(f"Nettverksfeil ved nedlasting av tilfluktsrom: {exc.reason}") from exc


def _build_shelter_order_payload() -> Dict[str, Any]:
    return {
        "downloadAsBundle": False,
        "softwareClient": "safemap",
        "softwareClientVersion": "1.0",
        "orderLines": [
            {
                "metadataUuid": SHELTER_METADATA_UUID,
                "areas": [SHELTER_ORDER_AREA],
                "formats": [SHELTER_ORDER_FORMAT],
                "projections": [SHELTER_ORDER_PROJECTION],
            }
        ],
    }


def _extract_ready_download_url(order_receipt: Dict[str, Any]) -> Optional[str]:
    files = order_receipt.get("files") or []
    if not isinstance(files, list):
        return None
    for file_entry in files:
        if not isinstance(file_entry, dict):
            continue
        download_url = file_entry.get("downloadUrl")
        if not download_url:
            continue
        status = str(file_entry.get("status") or "").strip().lower()
        if status in {"readyfordownload", "ready"} or not status:
            return str(download_url)
    return None


def _extract_order_status_url(order_receipt: Dict[str, Any]) -> Optional[str]:
    links = order_receipt.get("_links") or []
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            if link.get("rel") == "self" and link.get("href"):
                return str(link["href"])
    reference_number = order_receipt.get("referenceNumber")
    if isinstance(reference_number, str) and reference_number.strip():
        return f"{SHELTER_ORDER_URL.rstrip('/')}/{reference_number.strip()}"
    return None


def _extract_geojson_from_zip(zip_content: bytes) -> Dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_content)) as archive:
            json_members = [name for name in archive.namelist() if name.lower().endswith(".json")]
            if not json_members:
                raise RuntimeError("Nedlastet zip mangler GeoJSON-fil.")
            with archive.open(json_members[0], "r") as member:
                with io.TextIOWrapper(member, encoding="utf-8") as text_member:
                    geojson = json.load(text_member)
    except zipfile.BadZipFile as exc:
        raise RuntimeError("Nedlasting fra API var ikke en gyldig zip-fil.") from exc

    if not isinstance(geojson, dict) or not isinstance(geojson.get("features"), list):
        raise RuntimeError("GeoJSON fra API mangler gyldig features-liste.")
    return geojson


def _download_shelter_geojson_from_api() -> Dict[str, Any]:
    order_receipt = _http_json_request(SHELTER_ORDER_URL, method="POST", payload=_build_shelter_order_payload())
    download_url = _extract_ready_download_url(order_receipt)
    if not download_url:
        order_status_url = _extract_order_status_url(order_receipt)
        if not order_status_url:
            raise RuntimeError(
                "Fikk ikke statuslenke fra Nedlasting API. Kontroller capabilities-URL og metadata UUID."
            )
        for _ in range(SHELTER_ORDER_STATUS_POLL_ATTEMPTS):
            time.sleep(SHELTER_ORDER_STATUS_POLL_SECONDS)
            order_receipt = _http_json_request(order_status_url, method="GET")
            download_url = _extract_ready_download_url(order_receipt)
            if download_url:
                break
    if not download_url:
        raise RuntimeError("Filen ble ikke klar til nedlasting innen forventet tid.")
    zip_content = _http_bytes_request(download_url)
    return _extract_geojson_from_zip(zip_content)


def _get_shelter_geojson(force_refresh: bool = False) -> Dict[str, Any]:
    now = time.time()
    with _shelter_cache_lock:
        cached_geojson = _shelter_geojson_cache.get("geojson")
        expires_at = float(_shelter_geojson_cache.get("expires_at", 0.0) or 0.0)
        if not force_refresh and isinstance(cached_geojson, dict) and expires_at > now:
            return cached_geojson
    fresh_geojson = _download_shelter_geojson_from_api()
    with _shelter_cache_lock:
        _shelter_geojson_cache["geojson"] = fresh_geojson
        _shelter_geojson_cache["expires_at"] = time.time() + SHELTER_CACHE_TTL_SECONDS
    return fresh_geojson


def _load_shelter_points() -> List[Dict[str, Any]]:
    data = _get_shelter_geojson()
    points = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = _shelter_transformer.transform(coords[0], coords[1])
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


@app.get("/api/shelters")
def get_shelters(force_refresh: bool = False):
    try:
        geojson = _get_shelter_geojson(force_refresh=force_refresh)
        return JSONResponse(content=geojson)
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "error": (
                    "Klarte ikke hente tilfluktsrom fra Nedlasting API. "
                    f"Kontroller capabilities URL ({SHELTER_CAPABILITIES_URL}) og metadata UUID. Detaljer: {exc}"
                )
            },
        )


@app.get("/api/nearest")
def get_nearest_point(type: str, lat: float, lon: float):
    if type not in {"hospital", "legevakt", "shelter"}:
        return {"error": "Ugyldig type. Bruk hospital, legevakt eller shelter."}

    try:
        if type == "hospital":
            points = _load_geojson_points(_find_data_file("sykehus.json"))
        elif type == "legevakt":
            points = _load_geojson_points(_find_data_file("legevakter.json"))
        else:
            points = _load_shelter_points()
    except Exception as exc:
        return {"error": f"Klarte ikke hente data for {type}: {exc}"}

    if not points:
        return {"error": "Ingen punkter tilgjengelig."}

    closest = min(points, key=lambda p: _haversine(lat, lon, p["lat"], p["lon"]))
    return closest

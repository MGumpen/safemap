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
from urllib.parse import urlencode
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
ROUTING_DRIVING_BASE_URL = os.getenv("ROUTING_DRIVING_BASE_URL", "https://router.project-osrm.org").strip()
ROUTING_DRIVING_PROFILE = os.getenv("ROUTING_DRIVING_PROFILE", "driving").strip() or "driving"
ROUTING_WALKING_BASE_URL = os.getenv("ROUTING_WALKING_BASE_URL", "").strip()
ROUTING_WALKING_PROFILE = os.getenv("ROUTING_WALKING_PROFILE", "foot").strip() or "foot"

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
_analysis_function_lock = Lock()
_analysis_function_ready = False

LOCATION_ANALYSIS_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION public.analyze_location_score(
    input_lat DOUBLE PRECISION,
    input_lon DOUBLE PRECISION
)
RETURNS JSONB
LANGUAGE sql
AS $$
WITH origin AS (
    SELECT
        ST_SetSRID(ST_MakePoint(input_lon, input_lat), 4326) AS geom_4326,
        ST_SetSRID(ST_MakePoint(input_lon, input_lat), 4326)::geography AS geog_4326
),
nearest_hospital AS (
    SELECT
        1 AS sort_order,
        'hospital'::text AS key,
        'Sykehus'::text AS label,
        h.navn AS name,
        COALESCE(h.adresse, h.poststed, h.kommune, 'Sykehus') AS description,
        ST_Y(h.geom) AS lat,
        ST_X(h.geom) AS lon,
        ST_Distance(h.geom::geography, o.geog_4326) AS distance_meters,
        ST_DWithin(h.geom::geography, o.geog_4326, 80000) AS within_max_distance,
        20::integer AS max_score,
        20000::double precision AS ideal_distance_m,
        80000::double precision AS max_distance_m
    FROM sykehus_points h
    CROSS JOIN origin o
    ORDER BY ST_Distance(h.geom::geography, o.geog_4326)
    LIMIT 1
),
nearest_legevakt AS (
    SELECT
        2 AS sort_order,
        'legevakt'::text AS key,
        'Legevakt'::text AS label,
        l.navn AS name,
        COALESCE(l.adresse, l.poststed, l.kommune, 'Legevakt') AS description,
        ST_Y(l.geom) AS lat,
        ST_X(l.geom) AS lon,
        ST_Distance(l.geom::geography, o.geog_4326) AS distance_meters,
        ST_DWithin(l.geom::geography, o.geog_4326, 30000) AS within_max_distance,
        25::integer AS max_score,
        8000::double precision AS ideal_distance_m,
        30000::double precision AS max_distance_m
    FROM legevakt_points l
    CROSS JOIN origin o
    ORDER BY ST_Distance(l.geom::geography, o.geog_4326)
    LIMIT 1
),
nearest_brannstasjon AS (
    SELECT
        3 AS sort_order,
        'fire_station'::text AS key,
        'Brannstasjon'::text AS label,
        COALESCE(b."brannstasjon", 'Brannstasjon') AS name,
        COALESCE(b."brannvesen", b."objtype", 'Brannstasjon') AS description,
        ST_Y(ST_Transform(b."SHAPE", 4326)) AS lat,
        ST_X(ST_Transform(b."SHAPE", 4326)) AS lon,
        ST_Distance(ST_Transform(b."SHAPE", 4326)::geography, o.geog_4326) AS distance_meters,
        ST_DWithin(ST_Transform(b."SHAPE", 4326)::geography, o.geog_4326, 10000) AS within_max_distance,
        25::integer AS max_score,
        2000::double precision AS ideal_distance_m,
        10000::double precision AS max_distance_m
    FROM "Brannstasjoner" b
    CROSS JOIN origin o
    ORDER BY ST_Distance(ST_Transform(b."SHAPE", 4326)::geography, o.geog_4326)
    LIMIT 1
),
nearest_shelter AS (
    SELECT
        4 AS sort_order,
        'shelter'::text AS key,
        'Tilfluktsrom'::text AS label,
        COALESCE(t.adresse, 'Tilfluktsrom') AS name,
        CASE
            WHEN t.plasser IS NOT NULL THEN CONCAT(t.plasser, ' plasser')
            ELSE 'Tilfluktsrom'
        END AS description,
        ST_Y(ST_Transform(ST_GeomFromText(t.wkt_geom, 25833), 4326)) AS lat,
        ST_X(ST_Transform(ST_GeomFromText(t.wkt_geom, 25833), 4326)) AS lon,
        ST_Distance(
            ST_Transform(ST_GeomFromText(t.wkt_geom, 25833), 4326)::geography,
            o.geog_4326
        ) AS distance_meters,
        ST_DWithin(
            ST_Transform(ST_GeomFromText(t.wkt_geom, 25833), 4326)::geography,
            o.geog_4326,
            5000
        ) AS within_max_distance,
        30::integer AS max_score,
        1000::double precision AS ideal_distance_m,
        5000::double precision AS max_distance_m
    FROM tilfluktsrom t
    CROSS JOIN origin o
    ORDER BY ST_Distance(
        ST_Transform(ST_GeomFromText(t.wkt_geom, 25833), 4326)::geography,
        o.geog_4326
    )
    LIMIT 1
),
nearest_targets AS (
    SELECT * FROM nearest_hospital
    UNION ALL
    SELECT * FROM nearest_legevakt
    UNION ALL
    SELECT * FROM nearest_brannstasjon
    UNION ALL
    SELECT * FROM nearest_shelter
),
scored AS (
    SELECT
        sort_order,
        key,
        label,
        name,
        description,
        lat,
        lon,
        ROUND(distance_meters)::integer AS distance_meters,
        ROUND((distance_meters / 1000.0)::numeric, 2) AS distance_km,
        within_max_distance,
        max_score,
        ideal_distance_m::integer AS ideal_distance_m,
        max_distance_m::integer AS max_distance_m,
        CASE
            WHEN distance_meters <= ideal_distance_m THEN max_score
            WHEN distance_meters >= max_distance_m THEN 0
            ELSE ROUND(
                max_score * (
                    (max_distance_m - distance_meters) / NULLIF(max_distance_m - ideal_distance_m, 0)
                )
            )::integer
        END AS score
    FROM nearest_targets
)
SELECT jsonb_build_object(
    'clicked_point',
    jsonb_build_object(
        'lat', input_lat,
        'lon', input_lon
    ),
    'score',
    COALESCE((SELECT SUM(score) FROM scored), 0),
    'max_score',
    100,
    'breakdown',
    COALESCE(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'key', key,
                    'label', label,
                    'name', name,
                    'description', description,
                    'lat', lat,
                    'lon', lon,
                    'distance_meters', distance_meters,
                    'distance_km', distance_km,
                    'within_max_distance', within_max_distance,
                    'score', score,
                    'max_score', max_score,
                    'ideal_distance_m', ideal_distance_m,
                    'max_distance_m', max_distance_m,
                    'score_ratio', ROUND(score::numeric / NULLIF(max_score, 0), 4)
                )
                ORDER BY sort_order
            )
            FROM scored
        ),
        '[]'::jsonb
    )
);
$$;
"""

LOCATION_ANALYSIS_GRID_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION public.analyze_location_grid(
    min_lat DOUBLE PRECISION,
    min_lon DOUBLE PRECISION,
    max_lat DOUBLE PRECISION,
    max_lon DOUBLE PRECISION,
    requested_cell_size_m INTEGER DEFAULT 2000,
    max_cells INTEGER DEFAULT 144
)
RETURNS JSONB
LANGUAGE sql
AS $$
WITH normalized AS (
    SELECT
        LEAST(min_lat, max_lat) AS min_lat,
        LEAST(min_lon, max_lon) AS min_lon,
        GREATEST(min_lat, max_lat) AS max_lat,
        GREATEST(min_lon, max_lon) AS max_lon,
        GREATEST(500, LEAST(requested_cell_size_m, 25000))::double precision AS requested_cell_size_m,
        GREATEST(16, LEAST(max_cells, 400))::integer AS max_cells
),
bounds AS (
    SELECT
        ST_Transform(ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326), 3857) AS geom_3857,
        requested_cell_size_m,
        max_cells,
        GREATEST(1, FLOOR(SQRT(max_cells::numeric)))::integer AS max_side_cells
    FROM normalized
),
grid_meta AS (
    SELECT
        geom_3857,
        GREATEST(
            requested_cell_size_m,
            (ST_XMax(geom_3857) - ST_XMin(geom_3857)) / max_side_cells,
            (ST_YMax(geom_3857) - ST_YMin(geom_3857)) / max_side_cells
        ) AS actual_cell_size_m,
        ST_XMin(geom_3857) AS min_x,
        ST_XMax(geom_3857) AS max_x,
        ST_YMin(geom_3857) AS min_y,
        ST_YMax(geom_3857) AS max_y
    FROM bounds
),
cells AS (
    SELECT
        ST_MakeEnvelope(
            meta.min_x + (gx * meta.actual_cell_size_m),
            meta.min_y + (gy * meta.actual_cell_size_m),
            LEAST(meta.min_x + ((gx + 1) * meta.actual_cell_size_m), meta.max_x),
            LEAST(meta.min_y + ((gy + 1) * meta.actual_cell_size_m), meta.max_y),
            3857
        ) AS geom_3857,
        meta.actual_cell_size_m
    FROM grid_meta meta
    CROSS JOIN LATERAL generate_series(
        0,
        GREATEST(0, CEIL((meta.max_x - meta.min_x) / meta.actual_cell_size_m)::integer - 1)
    ) AS gx
    CROSS JOIN LATERAL generate_series(
        0,
        GREATEST(0, CEIL((meta.max_y - meta.min_y) / meta.actual_cell_size_m)::integer - 1)
    ) AS gy
),
cells_wgs84 AS (
    SELECT
        ST_Transform(geom_3857, 4326) AS geom_4326,
        ST_Transform(ST_Centroid(geom_3857), 4326) AS centroid_4326,
        actual_cell_size_m
    FROM cells
),
scored AS (
    SELECT
        geom_4326,
        actual_cell_size_m,
        public.analyze_location_score(
            ST_Y(centroid_4326),
            ST_X(centroid_4326)
        ) AS analysis
    FROM cells_wgs84
)
SELECT jsonb_build_object(
    'type',
    'FeatureCollection',
    'cell_size_m',
    COALESCE((SELECT ROUND(MAX(actual_cell_size_m))::integer FROM scored), 0),
    'feature_count',
    COALESCE((SELECT COUNT(*) FROM scored), 0),
    'features',
    COALESCE(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'type',
                    'Feature',
                    'geometry',
                    ST_AsGeoJSON(geom_4326)::jsonb,
                    'properties',
                    jsonb_build_object(
                        'score', COALESCE((analysis->>'score')::integer, 0),
                        'max_score', COALESCE((analysis->>'max_score')::integer, 100),
                        'score_label',
                        CASE
                            WHEN COALESCE((analysis->>'score')::integer, 0) >= 80 THEN 'Svært god'
                            WHEN COALESCE((analysis->>'score')::integer, 0) >= 60 THEN 'God'
                            WHEN COALESCE((analysis->>'score')::integer, 0) >= 40 THEN 'Moderat'
                            WHEN COALESCE((analysis->>'score')::integer, 0) >= 20 THEN 'Lav'
                            ELSE 'Svak'
                        END
                    )
                )
            )
            FROM scored
        ),
        '[]'::jsonb
    )
);
$$;
"""


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
    return templates.TemplateResponse(request=request, name="index.html")

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


def _get_route_mode_settings(mode: str) -> Dict[str, str]:
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode == "driving":
        return {
            "label": "Bilvei",
            "base_url": ROUTING_DRIVING_BASE_URL,
            "profile": ROUTING_DRIVING_PROFILE,
        }
    if normalized_mode == "walking":
        return {
            "label": "Gangvei",
            "base_url": ROUTING_WALKING_BASE_URL,
            "profile": ROUTING_WALKING_PROFILE,
        }
    raise ValueError("Ugyldig rutemodus. Bruk driving eller walking.")


def _build_osrm_route_url(
    base_url: str,
    profile: str,
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
) -> str:
    query = urlencode(
        {
            "overview": "full",
            "geometries": "geojson",
        }
    )
    return (
        f"{base_url.rstrip('/')}/route/v1/{profile}/"
        f"{from_lon},{from_lat};{to_lon},{to_lat}?{query}"
    )


def _fetch_routed_path(
    mode: str,
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
) -> Dict[str, Any]:
    settings = _get_route_mode_settings(mode)
    base_url = settings["base_url"]
    profile = settings["profile"]

    if not base_url:
        guidance = (
            "til en rutetjeneste som faktisk er bygget for denne modusen."
            if mode != "walking"
            else "til en gangruter bygget paa Vegnett Pluss."
        )
        raise RuntimeError(
            f"{settings['label']} er ikke konfigurert. Sett ROUTING_{mode.upper()}_BASE_URL i backend-miljoet "
            f"{guidance}"
        )

    payload = _http_json_request(
        _build_osrm_route_url(base_url, profile, from_lat, from_lon, to_lat, to_lon)
    )
    routes = payload.get("routes")
    if not isinstance(routes, list) or not routes:
        raise RuntimeError(f"Rutemotoren returnerte ingen {settings['label'].lower()} for dette punktparet.")

    route = routes[0]
    geometry = route.get("geometry") or {}
    coordinates = geometry.get("coordinates")
    if geometry.get("type") != "LineString" or not isinstance(coordinates, list) or len(coordinates) < 2:
        raise RuntimeError("Rutemotoren returnerte ugyldig geometri.")

    return {
        "mode": mode,
        "label": settings["label"],
        "distance_meters": route.get("distance"),
        "duration_seconds": route.get("duration"),
        "geometry": geometry,
        "provider_profile": profile,
    }


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


def _ensure_location_analysis_function() -> None:
    global _analysis_function_ready
    if _analysis_function_ready:
        return

    with _analysis_function_lock:
        if _analysis_function_ready:
            return

        connection = _get_db_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(LOCATION_ANALYSIS_FUNCTION_SQL)
            cursor.execute(LOCATION_ANALYSIS_GRID_FUNCTION_SQL)
            connection.commit()
            cursor.close()
            _analysis_function_ready = True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


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
def get_nearest_point(type: str, lat: float, lon: float, mode: str = "air"):
    if type not in {"hospital", "legevakt", "shelter"}:
        return JSONResponse(
            status_code=400,
            content={"error": "Ugyldig type. Bruk hospital, legevakt eller shelter."},
        )
    if mode not in {"air", "driving", "walking"}:
        return JSONResponse(
            status_code=400,
            content={"error": "Ugyldig rutemodus. Bruk air, driving eller walking."},
        )

    try:
        if type == "hospital":
            points = _load_geojson_points(_find_data_file("sykehus.json"))
        elif type == "legevakt":
            points = _load_geojson_points(_find_data_file("legevakter.json"))
        else:
            points = _load_shelter_points()
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": f"Klarte ikke hente data for {type}: {exc}"},
        )

    if not points:
        return JSONResponse(status_code=404, content={"error": "Ingen punkter tilgjengelig."})

    sorted_points = sorted(points, key=lambda p: _haversine(lat, lon, p["lat"], p["lon"]))
    if mode == "air":
        return sorted_points[0]

    best_point = None
    best_distance_meters = None
    candidate_points = sorted_points[:8]

    try:
        for point in candidate_points:
            route = _fetch_routed_path(mode, lat, lon, point["lat"], point["lon"])
            routed_distance = route.get("distance_meters")
            if not isinstance(routed_distance, (int, float)) or not math.isfinite(routed_distance):
                continue
            if best_distance_meters is None or routed_distance < best_distance_meters:
                best_distance_meters = float(routed_distance)
                best_point = {
                    **point,
                    "route_distance_meters": round(float(routed_distance), 2),
                    "route_mode": mode,
                }
    except RuntimeError as exc:
        status_code = 501 if "ikke konfigurert" in str(exc) else 502
        return JSONResponse(status_code=status_code, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Klarte ikke beregne naermeste {type} for {mode}: {exc}"},
        )

    if best_point is None:
        return JSONResponse(
            status_code=502,
            content={"error": f"Fant ingen gyldig {mode}-rute til {type}."},
        )

    return best_point


@app.get("/api/route")
def get_route(
    mode: str,
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
):
    if mode == "air":
        distance_meters = _haversine(from_lat, from_lon, to_lat, to_lon) * 1000
        return JSONResponse(
            content={
                "mode": "air",
                "label": "Luftlinje",
                "distance_meters": round(distance_meters, 2),
                "duration_seconds": None,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [from_lon, from_lat],
                        [to_lon, to_lat],
                    ],
                },
            }
        )

    try:
        payload = _fetch_routed_path(mode, from_lat, from_lon, to_lat, to_lon)
        return JSONResponse(content=payload)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except RuntimeError as exc:
        status_code = 501 if "ikke konfigurert" in str(exc) else 502
        return JSONResponse(status_code=status_code, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Klarte ikke hente rute: {exc}"},
        )


@app.get("/api/location-analysis")
def get_location_analysis(lat: float, lon: float):
    connection = None
    cursor = None

    try:
        _ensure_location_analysis_function()
        connection = _get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT public.analyze_location_score(%s, %s)", (lat, lon))
        row = cursor.fetchone()
        if not row or row[0] is None:
            return JSONResponse(
                status_code=404,
                content={"error": "Ingen analysedata tilgjengelig for dette punktet."},
            )

        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return JSONResponse(content=payload)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Klarte ikke analysere punktet: {exc}"},
        )
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.get("/api/location-analysis-grid")
def get_location_analysis_grid(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    cell_size_m: int = 2000,
):
    connection = None
    cursor = None

    try:
        _ensure_location_analysis_function()
        connection = _get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT public.analyze_location_grid(%s, %s, %s, %s, %s)",
            (min_lat, min_lon, max_lat, max_lon, cell_size_m),
        )
        row = cursor.fetchone()
        if not row or row[0] is None:
            return JSONResponse(
                status_code=404,
                content={"error": "Ingen analysedata tilgjengelig for dette kartutsnittet."},
            )

        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return JSONResponse(content=payload)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Klarte ikke analysere kartutsnittet: {exc}"},
        )
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

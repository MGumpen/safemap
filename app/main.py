from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from dotenv import load_dotenv
import heapq
import io
import os
import psycopg2
import json
import math
import ssl
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import List, Dict, Any, Optional, Tuple, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen
from pyproj import Transformer
from psycopg2 import sql

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
WALKING_NETWORK_TABLE = os.getenv("WALKING_NETWORK_TABLE", "vegnett_pluss_gangnett").strip() or "vegnett_pluss_gangnett"
WALKING_NETWORK_CACHE_TTL_SECONDS = int(os.getenv("WALKING_NETWORK_CACHE_TTL_SECONDS", "300"))
WALKING_MAX_SNAP_DISTANCE_METERS = float(os.getenv("WALKING_MAX_SNAP_DISTANCE_METERS", "1500"))
WALKING_SPEED_MPS = float(os.getenv("WALKING_SPEED_MPS", "1.4"))
WALKING_CONNECTOR_SPEED_MPS = float(os.getenv("WALKING_CONNECTOR_SPEED_MPS", "1.4"))
WALKING_TRAIL_SPEED_MPS = float(os.getenv("WALKING_TRAIL_SPEED_MPS", "1.2"))
WALKING_TRACTOR_ROAD_SPEED_MPS = float(os.getenv("WALKING_TRACTOR_ROAD_SPEED_MPS", "1.3"))
WALKING_STAIRS_SPEED_MPS = float(os.getenv("WALKING_STAIRS_SPEED_MPS", "0.8"))
WALKING_CROSSING_SPEED_MPS = float(os.getenv("WALKING_CROSSING_SPEED_MPS", "1.1"))
WALKING_JUNCTION_SPEED_MPS = float(os.getenv("WALKING_JUNCTION_SPEED_MPS", "1.15"))
WALKING_EDGE_CANDIDATE_LIMIT = int(os.getenv("WALKING_EDGE_CANDIDATE_LIMIT", "6"))
WALKING_SHELTER_EDGE_CANDIDATE_LIMIT = int(os.getenv("WALKING_SHELTER_EDGE_CANDIDATE_LIMIT", "40"))
WALKING_TARGET_ACCESS_CANDIDATE_LIMIT = int(os.getenv("WALKING_TARGET_ACCESS_CANDIDATE_LIMIT", "8"))
WALKING_SHELTER_TARGET_ACCESS_CANDIDATE_LIMIT = int(
    os.getenv("WALKING_SHELTER_TARGET_ACCESS_CANDIDATE_LIMIT", "12")
)
WALKING_TARGET_ACCESS_MARGIN_METERS = float(os.getenv("WALKING_TARGET_ACCESS_MARGIN_METERS", "35"))
WALKING_TARGET_ACCESS_SCAN_LIMIT = int(os.getenv("WALKING_TARGET_ACCESS_SCAN_LIMIT", "32"))
WALKING_SHELTER_ACCESS_MARGIN_METERS = float(os.getenv("WALKING_SHELTER_ACCESS_MARGIN_METERS", "20"))
WALKING_NEAREST_HOSPITAL_POINT_LIMIT = int(os.getenv("WALKING_NEAREST_HOSPITAL_POINT_LIMIT", "0"))
WALKING_NEAREST_LEGEVAKT_POINT_LIMIT = int(os.getenv("WALKING_NEAREST_LEGEVAKT_POINT_LIMIT", "24"))
WALKING_NEAREST_SHELTER_POINT_LIMIT = int(os.getenv("WALKING_NEAREST_SHELTER_POINT_LIMIT", "32"))

DEDICATED_WALKING_TYPE_VALUES = {
    "Fortau",
    "Gangfelt",
    "Gang- og sykkelveg",
    "Gangveg",
    "Gågate",
    "Trapp",
    "Sykkelveg",
}
TRAIL_WALKING_TYPE_VALUES = {
    "Sti",
    "Stitrapp",
    "Traktorveg",
}
SHARED_ROAD_WALKING_TYPE_VALUES = {
    "Enkel bilveg",
    "Gatetun",
}
JUNCTION_WALKING_TYPE_VALUES = {
    "Kanalisert veg",
    "Rundkjøring",
}
NON_WALKABLE_VEHICLE_TYPE_VALUES = {
    "Motorveg",
    "Motortrafikkveg",
    "Rampe",
}


def _no_dedicated_walking_path_message() -> str:
    return (
        "Det finnes ikke egen gangvei helt frem til valgt punkt. "
        "Ruten kan derfor kreve at du går langs bilveg."
    )


def _normalize_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_walkable_walking_edge(
    type_veg: Optional[str],
    trafikantgruppe: Optional[str],
) -> bool:
    normalized_type = _normalize_optional_text(type_veg)
    normalized_group = _normalize_optional_text(trafikantgruppe)

    if normalized_type in NON_WALKABLE_VEHICLE_TYPE_VALUES:
        return False
    if normalized_type in DEDICATED_WALKING_TYPE_VALUES or normalized_type in TRAIL_WALKING_TYPE_VALUES:
        return True
    if normalized_group == "G":
        return True
    if normalized_group == "K" and (
        normalized_type in SHARED_ROAD_WALKING_TYPE_VALUES
        or normalized_type in JUNCTION_WALKING_TYPE_VALUES
    ):
        return True
    return False


def _walking_edge_speed_mps(
    type_veg: Optional[str],
    trafikantgruppe: Optional[str],
) -> Optional[float]:
    normalized_type = _normalize_optional_text(type_veg)
    normalized_group = _normalize_optional_text(trafikantgruppe)

    if not _is_walkable_walking_edge(normalized_type, normalized_group):
        return None
    if normalized_type == "Trapp" or normalized_type == "Stitrapp":
        return WALKING_STAIRS_SPEED_MPS
    if normalized_type == "Traktorveg":
        return WALKING_TRACTOR_ROAD_SPEED_MPS
    if normalized_type == "Sti":
        return WALKING_TRAIL_SPEED_MPS
    if normalized_type == "Gangfelt":
        return WALKING_CROSSING_SPEED_MPS
    if normalized_type in JUNCTION_WALKING_TYPE_VALUES:
        return WALKING_JUNCTION_SPEED_MPS
    return WALKING_SPEED_MPS


def _walking_time_seconds(distance_meters: float, speed_mps: float) -> float:
    safe_speed = max(float(speed_mps), 0.1)
    return max(float(distance_meters), 0.0) / safe_speed


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.on_event("startup")
def _warm_runtime_caches_on_startup() -> None:
    try:
        _load_walking_network_graph()
    except Exception as exc:
        print(f"[startup] Klarte ikke forvarme walking-grafen: {exc}")

    for file_name in ("sykehus.json", "legevakter.json"):
        try:
            _load_geojson_points(_find_data_file(file_name))
        except Exception as exc:
            print(f"[startup] Klarte ikke forvarme {file_name}: {exc}")

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
_walking_network_lock = Lock()
_walking_network_cache: Dict[str, Any] = {"graph": None, "expires_at": 0.0}
_walking_target_access_cache_lock = Lock()
_walking_target_access_cache: Dict[Tuple[float, float, str, int], Dict[str, Any]] = {}
_static_points_cache_lock = Lock()
_static_points_cache: Dict[str, Any] = {}

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
        ST_DWithin(h.geom::geography, o.geog_4326, 250000) AS within_max_distance,
        20::integer AS max_score,
        20000::double precision AS ideal_distance_m,
        250000::double precision AS max_distance_m
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
        ST_DWithin(l.geom::geography, o.geog_4326, 60000) AS within_max_distance,
        25::integer AS max_score,
        8000::double precision AS ideal_distance_m,
        60000::double precision AS max_distance_m
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
        ST_DWithin(ST_Transform(b."SHAPE", 4326)::geography, o.geog_4326, 50000) AS within_max_distance,
        25::integer AS max_score,
        5000::double precision AS ideal_distance_m,
        50000::double precision AS max_distance_m
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
            20000
        ) AS within_max_distance,
        30::integer AS max_score,
        2000::double precision AS ideal_distance_m,
        20000::double precision AS max_distance_m
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


def _fetch_external_route(
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
        raise RuntimeError(
            f"{settings['label']} er ikke konfigurert. Sett ROUTING_{mode.upper()}_BASE_URL i backend-miljoet "
            "til en rutetjeneste som faktisk er bygget for denne modusen."
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


def _parse_geojson_geometry(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Kunne ikke lese GeoJSON-geometri.")


def _extract_coords_from_geometry(value: Any) -> List[List[float]]:
    geometry = _parse_geojson_geometry(value)
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString" and isinstance(coordinates, list):
        return [[float(coord[0]), float(coord[1])] for coord in coordinates if isinstance(coord, list) and len(coord) >= 2]
    if geometry_type == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
        return [[float(coordinates[0]), float(coordinates[1])]]
    raise ValueError(f"Ustottet geometri for walking-ruting: {geometry_type}")


def _normalize_coord_pair(coord: Any) -> List[float]:
    if not isinstance(coord, (list, tuple)) or len(coord) < 2:
        raise ValueError("Ugyldig koordinat.")
    return [float(coord[0]), float(coord[1])]


def _merge_coord_segments(*segments: List[List[float]]) -> List[List[float]]:
    merged: List[List[float]] = []
    for segment in segments:
        for coord in segment:
            normalized = _normalize_coord_pair(coord)
            if merged and merged[-1] == normalized:
                continue
            merged.append(normalized)
    return merged


def _reverse_coords(coords: List[List[float]]) -> List[List[float]]:
    return [list(coord) for coord in reversed(coords)]


def _coord_distance_meters(start: List[float], end: List[float]) -> float:
    return _haversine(start[1], start[0], end[1], end[0]) * 1000


def _interpolate_coord(start: List[float], end: List[float], fraction: float) -> List[float]:
    clamped_fraction = max(0.0, min(1.0, float(fraction)))
    return [
        start[0] + (end[0] - start[0]) * clamped_fraction,
        start[1] + (end[1] - start[1]) * clamped_fraction,
    ]


def _extract_line_subsegment(
    coords: List[List[float]],
    start_ratio: float,
    end_ratio: float,
) -> List[List[float]]:
    if len(coords) < 2:
        return coords

    reverse_output = end_ratio < start_ratio
    from_ratio = max(0.0, min(1.0, min(start_ratio, end_ratio)))
    to_ratio = max(0.0, min(1.0, max(start_ratio, end_ratio)))

    if math.isclose(from_ratio, to_ratio, abs_tol=1e-9):
        point = _interpolate_coord(coords[0], coords[-1], from_ratio)
        return [point, point]

    cumulative_lengths = [0.0]
    total_length = 0.0
    for index in range(1, len(coords)):
        total_length += _coord_distance_meters(coords[index - 1], coords[index])
        cumulative_lengths.append(total_length)

    if total_length <= 0:
        base_segment = [coords[0], coords[-1]]
        return _reverse_coords(base_segment) if reverse_output else base_segment

    start_distance = from_ratio * total_length
    end_distance = to_ratio * total_length

    def point_at_distance(target_distance: float) -> List[float]:
        if target_distance <= 0:
            return list(coords[0])
        if target_distance >= total_length:
            return list(coords[-1])
        for segment_index in range(1, len(coords)):
            segment_start_distance = cumulative_lengths[segment_index - 1]
            segment_end_distance = cumulative_lengths[segment_index]
            if target_distance > segment_end_distance:
                continue
            segment_length = max(segment_end_distance - segment_start_distance, 1e-9)
            fraction = (target_distance - segment_start_distance) / segment_length
            return _interpolate_coord(coords[segment_index - 1], coords[segment_index], fraction)
        return list(coords[-1])

    segment_coords: List[List[float]] = [point_at_distance(start_distance)]
    for coord_index in range(1, len(coords) - 1):
        coord_distance = cumulative_lengths[coord_index]
        if start_distance < coord_distance < end_distance:
            segment_coords.append(list(coords[coord_index]))
    segment_coords.append(point_at_distance(end_distance))

    return _reverse_coords(segment_coords) if reverse_output else segment_coords


def _build_temp_edge(
    adjacency: Dict[str, List[Tuple[str, float, float, str, bool]]],
    temp_edge_coords: Dict[str, List[List[float]]],
    edge_id: str,
    from_node: str,
    to_node: str,
    distance_meters: float,
    travel_seconds: float,
    coords: List[List[float]],
) -> None:
    if not math.isfinite(distance_meters) or distance_meters < 0:
        return
    if not math.isfinite(travel_seconds) or travel_seconds < 0:
        return
    if len(coords) < 2:
        return
    temp_edge_coords[edge_id] = coords
    adjacency.setdefault(from_node, []).append((to_node, float(travel_seconds), float(distance_meters), edge_id, True))
    adjacency.setdefault(to_node, []).append((from_node, float(travel_seconds), float(distance_meters), edge_id, False))


def _load_walking_network_graph(force_refresh: bool = False) -> Dict[str, Any]:
    now = time.time()
    with _walking_network_lock:
        cached_graph = _walking_network_cache.get("graph")
        expires_at = float(_walking_network_cache.get("expires_at", 0.0) or 0.0)
        if not force_refresh and isinstance(cached_graph, dict) and expires_at > now:
            return cached_graph

    connection = None
    cursor = None
    try:
        connection = _get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            sql.SQL(
                """
                SELECT
                    id,
                    source_node,
                    target_node,
                    type_veg,
                    properties ->> 'trafikantgruppe' AS trafikantgruppe,
                    COALESCE(length_meters, ST_Length(geom::geography)) AS length_meters,
                    ST_AsGeoJSON(geom) AS geometry_json
                FROM {table_name}
                WHERE geom IS NOT NULL
                  AND source_node IS NOT NULL
                  AND target_node IS NOT NULL
                """
            ).format(table_name=sql.Identifier(WALKING_NETWORK_TABLE))
        )
        rows = cursor.fetchall()
    except Exception as exc:
        raise RuntimeError(
            f"Klarte ikke laste walking-nett fra {WALKING_NETWORK_TABLE}. "
            "Kontroller at Vegnett Pluss er hentet og importert. "
            f"Detaljer: {exc}"
        ) from exc
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    if not rows:
        raise RuntimeError(
            f"Fant ingen ganglenker i {WALKING_NETWORK_TABLE}. "
            "Kjor fetch_vegnett_pluss_gangnett.py og importer resultatet til PostGIS."
        )

    adjacency: Dict[str, List[Tuple[str, float, float, str, bool]]] = {}
    edge_coords: Dict[str, List[List[float]]] = {}
    edge_count = 0

    for edge_id_raw, source_node_raw, target_node_raw, type_veg_raw, trafikantgruppe_raw, length_raw, geometry_json in rows:
        source_node = str(source_node_raw).strip()
        target_node = str(target_node_raw).strip()
        if not source_node or not target_node:
            continue
        coords = _extract_coords_from_geometry(geometry_json)
        if len(coords) < 2:
            continue
        length_meters = float(length_raw or 0.0)
        travel_speed_mps = _walking_edge_speed_mps(type_veg_raw, trafikantgruppe_raw)
        if travel_speed_mps is None:
            continue
        travel_seconds = _walking_time_seconds(length_meters, travel_speed_mps)
        edge_id = str(edge_id_raw)
        edge_coords[edge_id] = coords
        adjacency.setdefault(source_node, []).append((target_node, travel_seconds, length_meters, edge_id, True))
        adjacency.setdefault(target_node, []).append((source_node, travel_seconds, length_meters, edge_id, False))
        edge_count += 1

    if not edge_count:
        raise RuntimeError(
            f"{WALKING_NETWORK_TABLE} inneholder ingen brukbare lenker med nodekoblinger. "
            "Hent data pa nytt med fetch_vegnett_pluss_gangnett.py og importer dem pa nytt."
        )

    graph = {
        "adjacency": adjacency,
        "edge_coords": edge_coords,
        "edge_count": edge_count,
        "node_count": len(adjacency),
    }

    with _walking_network_lock:
        _walking_network_cache["graph"] = graph
        _walking_network_cache["expires_at"] = time.time() + WALKING_NETWORK_CACHE_TTL_SECONDS
    with _walking_target_access_cache_lock:
        _walking_target_access_cache.clear()

    return graph


def _fetch_nearest_walking_edges(
    lat: float,
    lon: float,
    limit: int = 4,
    connection: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    owned_connection = connection is None
    cursor = None
    try:
        if connection is None:
            connection = _get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            sql.SQL(
                """
                WITH input_point AS (
                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom
                )
                SELECT
                    e.id,
                    e.source_node,
                    e.target_node,
                    e.type_veg,
                    e.properties ->> 'trafikantgruppe' AS trafikantgruppe,
                    COALESCE(e.length_meters, ST_Length(e.geom::geography)) AS length_meters,
                    ST_AsGeoJSON(e.geom) AS geometry_json,
                    ST_AsGeoJSON(ST_ClosestPoint(e.geom, input_point.geom)) AS snap_point_json,
                    ST_LineLocatePoint(e.geom, input_point.geom) AS locate_ratio,
                    ST_AsGeoJSON(ST_LineSubstring(e.geom, 0, ST_LineLocatePoint(e.geom, input_point.geom))) AS prefix_json,
                    ST_AsGeoJSON(ST_LineSubstring(e.geom, ST_LineLocatePoint(e.geom, input_point.geom), 1)) AS suffix_json,
                    ST_Distance(e.geom::geography, input_point.geom::geography) AS snap_distance_meters
                FROM {table_name} e
                CROSS JOIN input_point
                WHERE e.geom IS NOT NULL
                  AND e.source_node IS NOT NULL
                  AND e.target_node IS NOT NULL
                ORDER BY e.geom <-> input_point.geom
                LIMIT %s
                """
            ).format(table_name=sql.Identifier(WALKING_NETWORK_TABLE)),
            (lon, lat, max(1, limit)),
        )
        rows = cursor.fetchall()
    except Exception as exc:
        raise RuntimeError(
            f"Klarte ikke finne naermeste ganglenke i {WALKING_NETWORK_TABLE}. "
            f"Detaljer: {exc}"
        ) from exc
    finally:
        if cursor is not None:
            cursor.close()
        if owned_connection and connection is not None:
            connection.close()

    if not rows:
        raise RuntimeError(
            f"Fant ingen ganglenker i {WALKING_NETWORK_TABLE}. "
            "Importer Vegnett Pluss-gangnettet til databasen for walking-ruting."
        )

    preferred_candidates: List[Dict[str, Any]] = []
    fallback_candidates: List[Dict[str, Any]] = []
    for row in rows:
        (
            edge_id_raw,
            source_node_raw,
            target_node_raw,
            type_veg_raw,
            trafikantgruppe_raw,
            length_raw,
            geometry_json,
            snap_point_json,
            locate_ratio_raw,
            prefix_json,
            suffix_json,
            snap_distance_raw,
        ) = row

        snap_coords = _extract_coords_from_geometry(snap_point_json)
        if not snap_coords:
            continue

        snap_distance_meters = float(snap_distance_raw or 0.0)

        locate_ratio = float(locate_ratio_raw or 0.0)
        locate_ratio = max(0.0, min(1.0, locate_ratio))
        total_length_meters = float(length_raw or 0.0)
        travel_speed_mps = _walking_edge_speed_mps(type_veg_raw, trafikantgruppe_raw)
        if travel_speed_mps is None:
            continue

        candidate = {
            "edge_id": str(edge_id_raw),
            "source_node": str(source_node_raw),
            "target_node": str(target_node_raw),
            "type_veg": str(type_veg_raw or "").strip(),
            "trafikantgruppe": str(trafikantgruppe_raw or "").strip(),
            "total_length_meters": total_length_meters,
            "travel_speed_mps": travel_speed_mps,
            "locate_ratio": locate_ratio,
            "snap_distance_meters": snap_distance_meters,
            "is_off_network_connector": snap_distance_meters > WALKING_MAX_SNAP_DISTANCE_METERS,
            "edge_coords": _extract_coords_from_geometry(geometry_json),
            "snap_coords": snap_coords,
            "prefix_coords": _extract_coords_from_geometry(prefix_json),
            "suffix_coords": _extract_coords_from_geometry(suffix_json),
        }
        if snap_distance_meters <= WALKING_MAX_SNAP_DISTANCE_METERS:
            preferred_candidates.append(candidate)
        else:
            fallback_candidates.append(candidate)

    if preferred_candidates:
        return preferred_candidates

    if fallback_candidates:
        return fallback_candidates

    if not preferred_candidates and not fallback_candidates:
        raise RuntimeError(
            f"Fant ingen brukbare ganglenker i {WALKING_NETWORK_TABLE} for valgt punkt."
        )


def _fetch_nearest_walking_edges_batch(
    points: List[Dict[str, Any]],
    limit: int = 4,
    connection: Optional[Any] = None,
) -> Dict[int, List[Dict[str, Any]]]:
    if not points:
        return {}

    owned_connection = connection is None
    cursor = None
    try:
        if connection is None:
            connection = _get_db_connection()
        cursor = connection.cursor()

        value_rows: List[sql.SQL] = []
        params: List[Any] = []
        for index, point in enumerate(points):
            value_rows.append(sql.SQL("(%s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))"))
            params.extend([index, float(point["lon"]), float(point["lat"])])
        params.append(max(1, limit))

        cursor.execute(
            sql.SQL(
                """
                WITH input_points(input_key, geom) AS (
                    VALUES {input_values}
                )
                SELECT
                    input_points.input_key,
                    e.id,
                    e.source_node,
                    e.target_node,
                    e.type_veg,
                    e.properties ->> 'trafikantgruppe' AS trafikantgruppe,
                    COALESCE(e.length_meters, ST_Length(e.geom::geography)) AS length_meters,
                    ST_AsGeoJSON(e.geom) AS geometry_json,
                    ST_AsGeoJSON(ST_ClosestPoint(e.geom, input_points.geom)) AS snap_point_json,
                    ST_LineLocatePoint(e.geom, input_points.geom) AS locate_ratio,
                    ST_AsGeoJSON(ST_LineSubstring(e.geom, 0, ST_LineLocatePoint(e.geom, input_points.geom))) AS prefix_json,
                    ST_AsGeoJSON(ST_LineSubstring(e.geom, ST_LineLocatePoint(e.geom, input_points.geom), 1)) AS suffix_json,
                    ST_Distance(e.geom::geography, input_points.geom::geography) AS snap_distance_meters
                FROM input_points
                CROSS JOIN LATERAL (
                    SELECT
                        e.id,
                        e.source_node,
                        e.target_node,
                        e.type_veg,
                        e.properties,
                        e.length_meters,
                        e.geom
                    FROM {table_name} e
                    WHERE e.geom IS NOT NULL
                      AND e.source_node IS NOT NULL
                      AND e.target_node IS NOT NULL
                    ORDER BY e.geom <-> input_points.geom
                    LIMIT %s
                ) e
                ORDER BY input_points.input_key
                """
            ).format(
                input_values=sql.SQL(", ").join(value_rows),
                table_name=sql.Identifier(WALKING_NETWORK_TABLE),
            ),
            params,
        )
        rows = cursor.fetchall()
    except Exception as exc:
        raise RuntimeError(
            f"Klarte ikke finne naermeste ganglenker i {WALKING_NETWORK_TABLE}. "
            f"Detaljer: {exc}"
        ) from exc
    finally:
        if cursor is not None:
            cursor.close()
        if owned_connection and connection is not None:
            connection.close()

    grouped_candidates: Dict[int, Dict[str, List[Dict[str, Any]]]] = {
        index: {"preferred": [], "fallback": []}
        for index in range(len(points))
    }

    for row in rows:
        input_index = int(row[0])
        (
            edge_id_raw,
            source_node_raw,
            target_node_raw,
            type_veg_raw,
            trafikantgruppe_raw,
            length_raw,
            geometry_json,
            snap_point_json,
            locate_ratio_raw,
            prefix_json,
            suffix_json,
            snap_distance_raw,
        ) = row[1:]

        snap_coords = _extract_coords_from_geometry(snap_point_json)
        if not snap_coords:
            continue

        snap_distance_meters = float(snap_distance_raw or 0.0)
        locate_ratio = float(locate_ratio_raw or 0.0)
        locate_ratio = max(0.0, min(1.0, locate_ratio))
        total_length_meters = float(length_raw or 0.0)
        travel_speed_mps = _walking_edge_speed_mps(type_veg_raw, trafikantgruppe_raw)
        if travel_speed_mps is None:
            continue

        candidate = {
            "edge_id": str(edge_id_raw),
            "source_node": str(source_node_raw),
            "target_node": str(target_node_raw),
            "type_veg": str(type_veg_raw or "").strip(),
            "trafikantgruppe": str(trafikantgruppe_raw or "").strip(),
            "total_length_meters": total_length_meters,
            "travel_speed_mps": travel_speed_mps,
            "locate_ratio": locate_ratio,
            "snap_distance_meters": snap_distance_meters,
            "is_off_network_connector": snap_distance_meters > WALKING_MAX_SNAP_DISTANCE_METERS,
            "edge_coords": _extract_coords_from_geometry(geometry_json),
            "snap_coords": snap_coords,
            "prefix_coords": _extract_coords_from_geometry(prefix_json),
            "suffix_coords": _extract_coords_from_geometry(suffix_json),
        }

        candidate_group = grouped_candidates.setdefault(input_index, {"preferred": [], "fallback": []})
        if snap_distance_meters <= WALKING_MAX_SNAP_DISTANCE_METERS:
            candidate_group["preferred"].append(candidate)
        else:
            candidate_group["fallback"].append(candidate)

    resolved_candidates: Dict[int, List[Dict[str, Any]]] = {}
    for index in range(len(points)):
        candidate_group = grouped_candidates.get(index) or {}
        preferred_candidates = candidate_group.get("preferred") or []
        fallback_candidates = candidate_group.get("fallback") or []
        if preferred_candidates:
            resolved_candidates[index] = preferred_candidates
        elif fallback_candidates:
            resolved_candidates[index] = fallback_candidates

    return resolved_candidates


def _fetch_nearest_walking_edge(lat: float, lon: float) -> Dict[str, Any]:
    return _fetch_nearest_walking_edges(lat, lon, limit=1)[0]


def _select_target_access_candidates(
    candidates: List[Dict[str, Any]],
    target_kind: Optional[str] = None,
    limit: int = WALKING_TARGET_ACCESS_CANDIDATE_LIMIT,
    margin_meters: float = WALKING_TARGET_ACCESS_MARGIN_METERS,
) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    sorted_candidates = sorted(
        candidates,
        key=lambda candidate: (
            float(candidate.get("snap_distance_meters") or 0.0),
            float(candidate.get("total_length_meters") or 0.0),
            str(candidate.get("edge_id") or ""),
        ),
    )
    best_snap_distance = float(sorted_candidates[0].get("snap_distance_meters") or 0.0)
    if target_kind == "shelter":
        allowed_margin = max(0.0, WALKING_SHELTER_ACCESS_MARGIN_METERS)
        nearest_candidates = [
            candidate
            for candidate in sorted_candidates
            if float(candidate.get("snap_distance_meters") or 0.0) <= best_snap_distance + allowed_margin
        ]
        if nearest_candidates:
            return nearest_candidates[: max(1, WALKING_SHELTER_TARGET_ACCESS_CANDIDATE_LIMIT)]
        return sorted_candidates[:1]

    allowed_margin = max(0.0, float(margin_meters))
    filtered_candidates = [
        candidate
        for candidate in sorted_candidates
        if float(candidate.get("snap_distance_meters") or 0.0) <= best_snap_distance + allowed_margin
    ]
    if filtered_candidates:
        return filtered_candidates[: max(1, limit)]
    return sorted_candidates[:1]


def _walking_target_access_cache_key(
    lat: float,
    lon: float,
    target_kind: Optional[str],
    edge_candidate_limit: int,
) -> Tuple[float, float, str, int]:
    return (
        round(float(lat), 7),
        round(float(lon), 7),
        str(target_kind or ""),
        int(edge_candidate_limit),
    )


def _get_walking_target_access_candidates(
    lat: float,
    lon: float,
    edge_candidate_limit: int,
    target_kind: Optional[str] = None,
    connection: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    cache_key = _walking_target_access_cache_key(lat, lon, target_kind, edge_candidate_limit)
    now = time.time()

    with _walking_target_access_cache_lock:
        cached_entry = _walking_target_access_cache.get(cache_key)
        if isinstance(cached_entry, dict):
            expires_at = float(cached_entry.get("expires_at", 0.0) or 0.0)
            cached_candidates = cached_entry.get("candidates")
            if expires_at > now and isinstance(cached_candidates, list):
                return cached_candidates

    end_candidates = _fetch_nearest_walking_edges(
        lat,
        lon,
        limit=max(1, edge_candidate_limit, WALKING_TARGET_ACCESS_SCAN_LIMIT),
        connection=connection,
    )
    selected_candidates = _select_target_access_candidates(end_candidates, target_kind=target_kind)

    with _walking_target_access_cache_lock:
        _walking_target_access_cache[cache_key] = {
            "expires_at": time.time() + WALKING_NETWORK_CACHE_TTL_SECONDS,
            "candidates": selected_candidates,
        }

    return selected_candidates


def _get_walking_target_access_candidates_batch(
    points: List[Dict[str, Any]],
    edge_candidate_limit: int,
    target_kind: Optional[str] = None,
    connection: Optional[Any] = None,
) -> List[List[Dict[str, Any]]]:
    if not points:
        return []

    now = time.time()
    results: List[Optional[List[Dict[str, Any]]]] = [None] * len(points)
    missing_points: List[Dict[str, Any]] = []
    missing_indexes: List[int] = []

    with _walking_target_access_cache_lock:
        for index, point in enumerate(points):
            cache_key = _walking_target_access_cache_key(point["lat"], point["lon"], target_kind, edge_candidate_limit)
            cached_entry = _walking_target_access_cache.get(cache_key)
            if not isinstance(cached_entry, dict):
                missing_points.append(point)
                missing_indexes.append(index)
                continue
            expires_at = float(cached_entry.get("expires_at", 0.0) or 0.0)
            cached_candidates = cached_entry.get("candidates")
            if expires_at > now and isinstance(cached_candidates, list):
                results[index] = cached_candidates
            else:
                missing_points.append(point)
                missing_indexes.append(index)

    if missing_points:
        fetched_candidates = _fetch_nearest_walking_edges_batch(
            missing_points,
            limit=max(1, edge_candidate_limit, WALKING_TARGET_ACCESS_SCAN_LIMIT),
            connection=connection,
        )
        cache_expires_at = time.time() + WALKING_NETWORK_CACHE_TTL_SECONDS

        with _walking_target_access_cache_lock:
            for local_index, point in enumerate(missing_points):
                global_index = missing_indexes[local_index]
                nearest_edges = fetched_candidates.get(local_index) or []
                selected_candidates = _select_target_access_candidates(nearest_edges, target_kind=target_kind)
                results[global_index] = selected_candidates
                cache_key = _walking_target_access_cache_key(point["lat"], point["lon"], target_kind, edge_candidate_limit)
                _walking_target_access_cache[cache_key] = {
                    "expires_at": cache_expires_at,
                    "candidates": selected_candidates,
                }

    return [result or [] for result in results]


def _iter_walking_neighbors(
    graph: Dict[str, Any],
    extra_adjacency: Dict[str, List[Tuple[str, float, float, str, bool]]],
    node_id: str,
) -> List[Tuple[str, float, float, str, bool]]:
    return [*graph["adjacency"].get(node_id, []), *extra_adjacency.get(node_id, [])]


def _run_walking_dijkstra(
    graph: Dict[str, Any],
    extra_adjacency: Dict[str, List[Tuple[str, float, float, str, bool]]],
    start_node: str,
    target_nodes: Optional[Iterable[str]] = None,
) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, Tuple[str, str, bool]]]:
    distances: Dict[str, float] = {start_node: 0.0}
    route_lengths: Dict[str, float] = {start_node: 0.0}
    previous: Dict[str, Tuple[str, str, bool]] = {}
    heap: List[Tuple[float, str]] = [(0.0, start_node)]
    remaining_targets = {str(node) for node in (target_nodes or []) if node}

    while heap:
        current_distance, current_node = heapq.heappop(heap)
        if current_distance > distances.get(current_node, float("inf")):
            continue
        if remaining_targets and current_node in remaining_targets:
            remaining_targets.remove(current_node)
            if not remaining_targets:
                break
        current_route_length = route_lengths.get(current_node, 0.0)
        for neighbor, travel_seconds, edge_distance_meters, edge_id, is_forward in _iter_walking_neighbors(
            graph, extra_adjacency, current_node
        ):
            next_distance = current_distance + travel_seconds
            next_route_length = current_route_length + edge_distance_meters
            existing_distance = distances.get(neighbor)
            existing_route_length = route_lengths.get(neighbor, float("inf"))
            if existing_distance is not None:
                if next_distance > existing_distance + 1e-9:
                    continue
                if math.isclose(next_distance, existing_distance, abs_tol=1e-9) and next_route_length >= existing_route_length:
                    continue
            if existing_distance is None and not math.isfinite(next_route_length):
                continue
            distances[neighbor] = next_distance
            route_lengths[neighbor] = next_route_length
            previous[neighbor] = (current_node, edge_id, is_forward)
            heapq.heappush(heap, (next_distance, neighbor))

    return distances, route_lengths, previous


def _reconstruct_walking_path(
    graph: Dict[str, Any],
    temp_edge_coords: Dict[str, List[List[float]]],
    previous: Dict[str, Tuple[str, str, bool]],
    end_node: str,
) -> List[List[float]]:
    segments: List[List[List[float]]] = []
    current = end_node
    while current in previous:
        previous_node, edge_id, is_forward = previous[current]
        coords = temp_edge_coords.get(edge_id) or graph["edge_coords"].get(edge_id)
        if not coords:
            raise RuntimeError("Mangler geometri for walking-ruten.")
        segments.append(coords if is_forward else _reverse_coords(coords))
        current = previous_node
    segments.reverse()
    return _merge_coord_segments(*segments)


def _prepare_walking_origin_search(
    graph: Dict[str, Any],
    from_lat: float,
    from_lon: float,
    target_nodes: Optional[Iterable[str]] = None,
    connection: Optional[Any] = None,
    start_edge_limit: int = WALKING_EDGE_CANDIDATE_LIMIT,
) -> Dict[str, Any]:
    extra_adjacency: Dict[str, List[Tuple[str, float, float, str, bool]]] = {}
    temp_edge_coords: Dict[str, List[List[float]]] = {}
    start_node = "__walk_start__"
    start_point = [[from_lon, from_lat]]
    start_candidates = _fetch_nearest_walking_edges(
        from_lat,
        from_lon,
        limit=max(1, start_edge_limit),
        connection=connection,
    )
    enriched_start_candidates: List[Dict[str, Any]] = []

    for index, start_snap in enumerate(start_candidates):
        start_snap_coord = start_snap["snap_coords"][-1]
        start_connector_meters = _haversine(from_lat, from_lon, start_snap_coord[1], start_snap_coord[0]) * 1000
        start_connector_seconds = _walking_time_seconds(start_connector_meters, WALKING_CONNECTOR_SPEED_MPS)
        start_prefix_length = start_snap["locate_ratio"] * start_snap["total_length_meters"]
        start_suffix_length = start_snap["total_length_meters"] - start_prefix_length
        start_prefix_seconds = _walking_time_seconds(start_prefix_length, start_snap["travel_speed_mps"])
        start_suffix_seconds = _walking_time_seconds(start_suffix_length, start_snap["travel_speed_mps"])

        _build_temp_edge(
            extra_adjacency,
            temp_edge_coords,
            f"temp:start:{index}:source",
            start_node,
            start_snap["source_node"],
            start_connector_meters + start_prefix_length,
            start_connector_seconds + start_prefix_seconds,
            _merge_coord_segments(
                start_point,
                [start_snap_coord],
                _reverse_coords(start_snap["prefix_coords"]),
            ),
        )
        _build_temp_edge(
            extra_adjacency,
            temp_edge_coords,
            f"temp:start:{index}:target",
            start_node,
            start_snap["target_node"],
            start_connector_meters + start_suffix_length,
            start_connector_seconds + start_suffix_seconds,
            _merge_coord_segments(
                start_point,
                [start_snap_coord],
                start_snap["suffix_coords"],
            ),
        )
        enriched_start_candidates.append(
            {
                **start_snap,
                "snap_coord": start_snap_coord,
                "start_connector_meters": start_connector_meters,
                "start_connector_seconds": start_connector_seconds,
            }
        )

    distances, route_lengths, previous = _run_walking_dijkstra(
        graph,
        extra_adjacency,
        start_node,
        target_nodes=target_nodes,
    )

    return {
        "from_lat": from_lat,
        "from_lon": from_lon,
        "start_point": start_point,
        "start_candidates": enriched_start_candidates,
        "extra_adjacency": extra_adjacency,
        "temp_edge_coords": temp_edge_coords,
        "distances": distances,
        "route_lengths": route_lengths,
        "previous": previous,
        "path_cache": {},
    }


def _get_walking_path_to_node(
    graph: Dict[str, Any],
    origin_search: Dict[str, Any],
    node_id: str,
) -> List[List[float]]:
    path_cache = origin_search["path_cache"]
    if node_id not in path_cache:
        path_cache[node_id] = _reconstruct_walking_path(
            graph,
            origin_search["temp_edge_coords"],
            origin_search["previous"],
            node_id,
        )
    return path_cache[node_id]


def _build_walking_route_payload(route_option: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mode": "walking",
        "label": "Gangvei",
        "distance_meters": round(float(route_option["distance_meters"]), 2),
        "duration_seconds": round(float(route_option["duration_seconds"]), 2),
        "geometry": {
            "type": "LineString",
            "coordinates": route_option["coordinates"],
        },
        "provider_profile": f"local:{WALKING_NETWORK_TABLE}",
    }


def _select_best_walking_route_option(
    graph: Dict[str, Any],
    origin_search: Dict[str, Any],
    end_candidates: List[Dict[str, Any]],
    to_lat: float,
    to_lon: float,
) -> Optional[Dict[str, Any]]:
    best_option: Optional[Dict[str, Any]] = None
    end_point = [[to_lon, to_lat]]
    travel_times = origin_search["distances"]
    route_lengths = origin_search["route_lengths"]

    def register_option(duration_seconds: float, distance_meters: float, coordinates: List[List[float]]) -> None:
        nonlocal best_option
        if (
            not math.isfinite(duration_seconds)
            or not math.isfinite(distance_meters)
            or len(coordinates) < 2
        ):
            return
        if (
            best_option is None
            or duration_seconds < float(best_option["duration_seconds"]) - 1e-9
            or (
                math.isclose(duration_seconds, float(best_option["duration_seconds"]), abs_tol=1e-9)
                and distance_meters < float(best_option["distance_meters"])
            )
        ):
            best_option = {
                "duration_seconds": float(duration_seconds),
                "distance_meters": float(distance_meters),
                "coordinates": coordinates,
            }

    for end_snap in end_candidates:
        end_snap_coord = end_snap["snap_coords"][-1]
        end_connector_meters = _haversine(to_lat, to_lon, end_snap_coord[1], end_snap_coord[0]) * 1000
        end_connector_seconds = _walking_time_seconds(end_connector_meters, WALKING_CONNECTOR_SPEED_MPS)
        end_prefix_length = end_snap["locate_ratio"] * end_snap["total_length_meters"]
        end_suffix_length = end_snap["total_length_meters"] - end_prefix_length
        end_prefix_seconds = _walking_time_seconds(end_prefix_length, end_snap["travel_speed_mps"])
        end_suffix_seconds = _walking_time_seconds(end_suffix_length, end_snap["travel_speed_mps"])

        time_to_source = travel_times.get(end_snap["source_node"])
        length_to_source = route_lengths.get(end_snap["source_node"])
        if time_to_source is not None and length_to_source is not None:
            register_option(
                time_to_source + end_connector_seconds + end_prefix_seconds,
                length_to_source + end_connector_meters + end_prefix_length,
                _merge_coord_segments(
                    _get_walking_path_to_node(graph, origin_search, end_snap["source_node"]),
                    end_snap["prefix_coords"],
                    [end_snap_coord],
                    end_point,
                ),
            )

        time_to_target = travel_times.get(end_snap["target_node"])
        length_to_target = route_lengths.get(end_snap["target_node"])
        if time_to_target is not None and length_to_target is not None:
            register_option(
                time_to_target + end_connector_seconds + end_suffix_seconds,
                length_to_target + end_connector_meters + end_suffix_length,
                _merge_coord_segments(
                    _get_walking_path_to_node(graph, origin_search, end_snap["target_node"]),
                    _reverse_coords(end_snap["suffix_coords"]),
                    [end_snap_coord],
                    end_point,
                ),
            )

        for start_snap in origin_search["start_candidates"]:
            if start_snap["edge_id"] != end_snap["edge_id"]:
                continue
            direct_edge_length = abs(start_snap["locate_ratio"] - end_snap["locate_ratio"]) * start_snap["total_length_meters"]
            same_edge_coords = _extract_line_subsegment(
                start_snap["edge_coords"],
                start_snap["locate_ratio"],
                end_snap["locate_ratio"],
            )
            register_option(
                start_snap["start_connector_seconds"]
                + _walking_time_seconds(direct_edge_length, start_snap["travel_speed_mps"])
                + end_connector_seconds,
                start_snap["start_connector_meters"] + direct_edge_length + end_connector_meters,
                _merge_coord_segments(
                    origin_search["start_point"],
                    same_edge_coords,
                    end_point,
                ),
            )

    return best_option


def _fetch_local_walking_route(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    edge_candidate_limit: int = WALKING_EDGE_CANDIDATE_LIMIT,
    target_kind: Optional[str] = None,
) -> Dict[str, Any]:
    graph = _load_walking_network_graph()
    connection = None
    try:
        connection = _get_db_connection()
        end_candidates = _get_walking_target_access_candidates(
            to_lat,
            to_lon,
            edge_candidate_limit=edge_candidate_limit,
            target_kind=target_kind,
            connection=connection,
        )
        target_nodes = {
            node_id
            for end_snap in end_candidates
            for node_id in (end_snap["source_node"], end_snap["target_node"])
            if node_id
        }
        origin_search = _prepare_walking_origin_search(
            graph,
            from_lat,
            from_lon,
            target_nodes=target_nodes,
            connection=connection,
            start_edge_limit=edge_candidate_limit,
        )
    finally:
        if connection is not None:
            connection.close()
    best_route = _select_best_walking_route_option(
        graph,
        origin_search,
        end_candidates,
        to_lat,
        to_lon,
    )

    if best_route is None:
        raise RuntimeError(_no_dedicated_walking_path_message())

    return _build_walking_route_payload(best_route)


def _fetch_routed_path(
    mode: str,
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    edge_candidate_limit: int = WALKING_EDGE_CANDIDATE_LIMIT,
    target_kind: Optional[str] = None,
) -> Dict[str, Any]:
    if mode == "walking":
        return _fetch_local_walking_route(
            from_lat,
            from_lon,
            to_lat,
            to_lon,
            edge_candidate_limit=edge_candidate_limit,
            target_kind=target_kind,
        )
    return _fetch_external_route(mode, from_lat, from_lon, to_lat, to_lon)


def _load_geojson_points(file_path: Path) -> List[Dict[str, Any]]:
    resolved_path = file_path.resolve()
    cache_key = str(resolved_path)
    try:
        mtime_ns = resolved_path.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = None

    with _static_points_cache_lock:
        cached = _static_points_cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("mtime_ns") == mtime_ns:
            cached_points = cached.get("points")
            if isinstance(cached_points, list):
                return cached_points

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

    with _static_points_cache_lock:
        _static_points_cache[cache_key] = {
            "mtime_ns": mtime_ns,
            "points": points,
        }

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


def _find_nearest_walking_point(
    lat: float,
    lon: float,
    candidate_points: List[Dict[str, Any]],
    edge_candidate_limit: int = WALKING_EDGE_CANDIDATE_LIMIT,
    target_kind: Optional[str] = None,
) -> Dict[str, Any]:
    graph = _load_walking_network_graph()
    prepared_targets: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    target_nodes = set()
    connection = None
    try:
        connection = _get_db_connection()
        try:
            candidate_access_sets = _get_walking_target_access_candidates_batch(
                candidate_points,
                edge_candidate_limit=edge_candidate_limit,
                target_kind=target_kind,
                connection=connection,
            )
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from exc

        for point, end_candidates in zip(candidate_points, candidate_access_sets):
            if not end_candidates:
                continue
            prepared_targets.append((point, end_candidates))
            for end_snap in end_candidates:
                target_nodes.add(end_snap["source_node"])
                target_nodes.add(end_snap["target_node"])

        if not prepared_targets:
            raise RuntimeError(_no_dedicated_walking_path_message())

        origin_search = _prepare_walking_origin_search(
            graph,
            lat,
            lon,
            target_nodes=target_nodes,
            connection=connection,
            start_edge_limit=WALKING_EDGE_CANDIDATE_LIMIT,
        )
    finally:
        if connection is not None:
            connection.close()

    best_point: Optional[Dict[str, Any]] = None
    best_route: Optional[Dict[str, Any]] = None
    best_score_seconds: Optional[float] = None

    for point, end_candidates in prepared_targets:
        route_option = _select_best_walking_route_option(
            graph,
            origin_search,
            end_candidates,
            point["lat"],
            point["lon"],
        )
        if route_option is not None:
            candidate_route = _build_walking_route_payload(route_option)
            candidate_score_seconds = float(route_option["duration_seconds"])
            if best_route is None or best_score_seconds is None or candidate_score_seconds < best_score_seconds:
                best_score_seconds = candidate_score_seconds
                best_route = candidate_route
                best_point = {
                    **point,
                    "route_distance_meters": round(float(candidate_route["distance_meters"]), 2),
                    "route_duration_seconds": round(float(candidate_route["duration_seconds"]), 2),
                    "route_mode": "walking",
                }

    if best_point is None or best_route is None:
        raise RuntimeError(_no_dedicated_walking_path_message())

    best_point["route"] = best_route
    return best_point


def _walking_point_candidate_limit(point_type: str, total_points: int) -> int:
    configured_limit = {
        "hospital": WALKING_NEAREST_HOSPITAL_POINT_LIMIT,
        "legevakt": WALKING_NEAREST_LEGEVAKT_POINT_LIMIT,
        "shelter": WALKING_NEAREST_SHELTER_POINT_LIMIT,
    }.get(point_type, 0)
    if configured_limit <= 0:
        return max(1, total_points)
    return max(1, min(total_points, configured_limit))


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

    if mode == "walking":
        try:
            edge_candidate_limit = (
                WALKING_SHELTER_EDGE_CANDIDATE_LIMIT if type == "shelter" else WALKING_EDGE_CANDIDATE_LIMIT
            )
            candidate_limit = _walking_point_candidate_limit(type, len(sorted_points))
            candidate_points = sorted_points[:candidate_limit]
            return _find_nearest_walking_point(
                lat,
                lon,
                candidate_points,
                edge_candidate_limit=edge_candidate_limit,
                target_kind=type,
            )
        except RuntimeError as exc:
            status_code = 501 if "ikke konfigurert" in str(exc) else 502
            return JSONResponse(status_code=status_code, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={"error": f"Klarte ikke beregne naermeste {type} for walking: {exc}"},
            )

    candidate_points = sorted_points[:8]

    best_point = None
    best_route = None
    best_distance_meters = None
    last_runtime_error: Optional[str] = None

    try:
        def evaluate_point(point: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], Optional[str]]:
            try:
                route = _fetch_routed_path(mode, lat, lon, point["lat"], point["lon"])
            except RuntimeError as exc:
                return point, None, str(exc)
            routed_distance = route.get("distance_meters")
            if not isinstance(routed_distance, (int, float)) or not math.isfinite(routed_distance):
                return point, None, None
            return point, route, None

        if mode == "driving" and len(candidate_points) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(candidate_points))) as executor:
                futures = [executor.submit(evaluate_point, point) for point in candidate_points]
                evaluated_candidates = [future.result() for future in as_completed(futures)]
        else:
            evaluated_candidates = [evaluate_point(point) for point in candidate_points]

        for point, route, route_error in evaluated_candidates:
            if route_error:
                last_runtime_error = route_error
                continue
            if route is None:
                continue
            routed_distance = route.get("distance_meters")
            if best_distance_meters is None or routed_distance < best_distance_meters:
                best_distance_meters = float(routed_distance)
                best_route = route
                best_point = {
                    **point,
                    "route_distance_meters": round(float(routed_distance), 2),
                    "route_mode": mode,
                }
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Klarte ikke beregne naermeste {type} for {mode}: {exc}"},
        )

    if best_point is None:
        if last_runtime_error:
            status_code = 501 if "ikke konfigurert" in last_runtime_error else 502
            return JSONResponse(status_code=status_code, content={"error": last_runtime_error})
        return JSONResponse(
            status_code=502,
            content={"error": f"Fant ingen gyldig {mode}-rute til {type}."},
        )

    if isinstance(best_route, dict):
        best_point["route"] = best_route

    return best_point


@app.get("/api/route")
def get_route(
    mode: str,
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    target_kind: Optional[str] = None,
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
        payload = _fetch_routed_path(
            mode,
            from_lat,
            from_lon,
            to_lat,
            to_lon,
            target_kind=target_kind,
        )
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

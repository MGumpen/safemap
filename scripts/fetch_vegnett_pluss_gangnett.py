#!/usr/bin/env python3
"""
Fetch walkable NVDB Vegnett Pluss links and write them as GeoJSON.

The graph is scoped to routes that are realistic to walk in a crisis: dedicated
walking infrastructure, large paths/trails, and ordinary road links that are
still defensible to walk when no separate gangvei exists. Turruter are not
included.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from pyproj import Transformer

NVDB_VEGNETT_URL = "https://nvdbapiles.atlas.vegvesen.no/vegnett/api/v4/veglenkesekvenser/segmentert"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "src" / "vegnett_pluss_gangnett.geojson"
DEFAULT_PAGE_SIZE = 200

# Dedicated walking links and larger trail types from NVDB Vegnett Pluss.
WALKING_TYPE_VALUES = {
    "Fortau",
    "Gangfelt",
    "Gang- og sykkelveg",
    "Gangveg",
    "Gågate",
    "Sti",
    "Stitrapp",
    "Traktorveg",
    "Trapp",
    "Sykkelveg",
}
SHARED_ROAD_TYPE_VALUES = {
    "Enkel bilveg",
    "Gatetun",
    "Kanalisert veg",
    "Rundkjøring",
}
NON_WALKABLE_VEHICLE_TYPE_VALUES = {
    "Motorveg",
    "Motortrafikkveg",
    "Rampe",
}

_transformers: dict[int, Transformer] = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hent gangbart Vegnett Pluss-nett fra NVDB API og skriv GeoJSON."
    )
    parser.add_argument(
        "--kommune",
        dest="kommuner",
        metavar="KOMMUNE",
        nargs="+",
        required=True,
        help="En eller flere kommunenummer som skal hentes fra NVDB.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"GeoJSON-fil som skal skrives. Standard: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Antall veglenkesekvenser per side. Standard: {DEFAULT_PAGE_SIZE}",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Valgfri grense for antall sider per kommune under testing.",
    )
    parser.add_argument(
        "--client-name",
        default="safemap",
        help="Verdi satt i X-Client-headeren mot NVDB API.",
    )
    return parser.parse_args()


def http_json_request(url: str, client_name: str) -> dict[str, Any]:
    request = UrlRequest(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "SafeMap/1.0 (vegnett-pluss-gangnett)",
            "X-Client": client_name,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} fra NVDB API: {error_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Nettverksfeil mot NVDB API: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("NVDB API returnerte ugyldig JSON.") from exc


def build_initial_url(kommune: str, page_size: int) -> str:
    query = urlencode(
        {
            "kommune": kommune,
            "antall": page_size,
            "inkluderAntall": "false",
        }
    )
    return f"{NVDB_VEGNETT_URL}?{query}"


def transformer_for_srid(srid: int) -> Transformer:
    transformer = _transformers.get(srid)
    if transformer is None:
        transformer = Transformer.from_crs(srid, 4326, always_xy=True)
        _transformers[srid] = transformer
    return transformer


def parse_linestring_wkt(wkt: str) -> list[tuple[float, float]]:
    normalized = (wkt or "").strip()
    if not normalized.upper().startswith("LINESTRING"):
        raise ValueError(f"Ustottet geometri fra NVDB: {normalized[:32]}")

    start_idx = normalized.find("(")
    end_idx = normalized.rfind(")")
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        raise ValueError("Ugyldig WKT for linjegeometri.")

    coordinates: list[tuple[float, float]] = []
    for raw_pair in normalized[start_idx + 1:end_idx].split(","):
        parts = raw_pair.strip().split()
        if len(parts) < 2:
            continue
        coordinates.append((float(parts[0]), float(parts[1])))

    if len(coordinates) < 2:
        raise ValueError("Linjegeometrien inneholder for faa koordinater.")
    return coordinates


def transform_coordinates(
    coordinates: list[tuple[float, float]],
    srid: int,
) -> list[list[float]]:
    if srid == 4326:
        return [[round(x, 8), round(y, 8)] for x, y in coordinates]

    transformer = transformer_for_srid(srid)
    transformed: list[list[float]] = []
    for x, y in coordinates:
        lon, lat = transformer.transform(x, y)
        transformed.append([round(lon, 8), round(lat, 8)])
    return transformed


def build_source_key(segment: dict[str, Any]) -> str:
    return ":".join(
        [
            str(segment.get("veglenkesekvensid") or ""),
            str(segment.get("veglenkenummer") or ""),
            str(segment.get("segmentnummer") or ""),
            str(segment.get("startnode") or ""),
            str(segment.get("sluttnode") or ""),
            str(segment.get("kortform") or ""),
        ]
    )


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _find_nested_value(payload: Any, key: str) -> str | None:
    if isinstance(payload, dict):
        direct_value = _normalize_text(payload.get(key))
        if direct_value:
            return direct_value
        for value in payload.values():
            nested_value = _find_nested_value(value, key)
            if nested_value:
                return nested_value
    elif isinstance(payload, list):
        for item in payload:
            nested_value = _find_nested_value(item, key)
            if nested_value:
                return nested_value
    return None


def extract_vegsystem_context(segment: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    vegsystemreferanse = segment.get("vegsystemreferanse") or {}
    vegsystem = vegsystemreferanse.get("vegsystem") or {}
    vegkategori = _normalize_text(vegsystem.get("vegkategori"))
    trafikantgruppe = _find_nested_value(vegsystemreferanse, "trafikantgruppe")
    kortform = _normalize_text(vegsystemreferanse.get("kortform"))
    return vegkategori, trafikantgruppe, kortform


def is_walkable_segment(segment: dict[str, Any]) -> bool:
    type_veg = _normalize_text(segment.get("typeVeg"))
    if type_veg in WALKING_TYPE_VALUES:
        return True

    _, trafikantgruppe, _ = extract_vegsystem_context(segment)
    if type_veg in NON_WALKABLE_VEHICLE_TYPE_VALUES:
        return False
    if trafikantgruppe == "G":
        return True
    if trafikantgruppe == "K" and type_veg in SHARED_ROAD_TYPE_VALUES:
        return True
    return False


def build_feature(segment: dict[str, Any]) -> dict[str, Any] | None:
    if not is_walkable_segment(segment):
        return None
    if segment.get("sluttdato"):
        return None

    geometry = segment.get("geometri") or {}
    wkt = geometry.get("wkt")
    srid = int(geometry.get("srid") or 4326)
    if not wkt:
        return None

    coordinates = transform_coordinates(parse_linestring_wkt(wkt), srid)
    vegsystemreferanse = segment.get("vegsystemreferanse") or {}
    adresse = segment.get("adresse") or {}
    vegkategori, trafikantgruppe, vegsystem_kortform = extract_vegsystem_context(segment)

    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates,
        },
        "properties": {
            "source_key": build_source_key(segment),
            "veglenkesekvensid": segment.get("veglenkesekvensid"),
            "veglenkenummer": segment.get("veglenkenummer"),
            "segmentnummer": segment.get("segmentnummer"),
            "kortform": segment.get("kortform"),
            "startnode": segment.get("startnode"),
            "sluttnode": segment.get("sluttnode"),
            "type_veg": segment.get("typeVeg"),
            "type_veg_sosi": segment.get("typeVeg_sosi"),
            "lengde_meters": segment.get("lengde") or geometry.get("lengde"),
            "kommune": segment.get("kommune") or geometry.get("kommune"),
            "fylke": segment.get("fylke"),
            "topologinivaa": segment.get("topologinivå"),
            "vegkategori": vegkategori,
            "trafikantgruppe": trafikantgruppe,
            "adresse_navn": adresse.get("navn"),
            "vegsystemreferanse": vegsystem_kortform or vegsystemreferanse.get("kortform"),
        },
    }


def fetch_features_for_kommune(
    kommune: str,
    client_name: str,
    page_size: int,
    max_pages: int | None,
) -> tuple[list[dict[str, Any]], int]:
    next_url = build_initial_url(kommune, page_size)
    page_count = 0
    features: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    while next_url:
        payload = http_json_request(next_url, client_name)
        objects = payload.get("objekter") or []
        if not isinstance(objects, list):
            raise RuntimeError("NVDB API mangler objekter-liste for segmenterte veglenkesekvenser.")

        for segment in objects:
            if not isinstance(segment, dict):
                continue
            feature = build_feature(segment)
            if feature is None:
                continue
            source_key = str(feature["properties"]["source_key"])
            if source_key in seen_keys:
                continue
            seen_keys.add(source_key)
            features.append(feature)

        page_count += 1
        metadata = payload.get("metadata") or {}
        next_info = metadata.get("neste") or {}
        next_url = str(next_info.get("href") or "").strip() or None
        if max_pages is not None and page_count >= max_pages:
            break

    return features, page_count


def write_geojson(output_path: Path, features: list[dict[str, Any]], kommuner: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "name": "vegnett_pluss_gangnett",
        "metadata": {
            "source": "NVDB Vegnett Pluss",
            "kommuner": kommuner,
            "included_type_veg": sorted(WALKING_TYPE_VALUES | SHARED_ROAD_TYPE_VALUES),
            "feature_count": len(features),
        },
        "features": features,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    kommuner = [value.strip() for value in args.kommuner if value.strip()]
    if not kommuner:
        raise SystemExit("Du maa oppgi minst ett kommunenummer via --kommune.")

    all_features: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    total_pages = 0

    for kommune in kommuner:
        kommune_features, page_count = fetch_features_for_kommune(
            kommune=kommune,
            client_name=args.client_name,
            page_size=max(1, args.page_size),
            max_pages=args.max_pages,
        )
        total_pages += page_count

        added_for_kommune = 0
        for feature in kommune_features:
            source_key = str(feature["properties"]["source_key"])
            if source_key in seen_keys:
                continue
            seen_keys.add(source_key)
            all_features.append(feature)
            added_for_kommune += 1

        print(
            f"{kommune}: hentet {added_for_kommune} ganglenker "
            f"fra {page_count} side(r)."
        )

    write_geojson(args.output, all_features, kommuner)
    print(
        f"Skrev {len(all_features)} ganglenker til {args.output} "
        f"(totalt {total_pages} side(r) lest)."
    )


if __name__ == "__main__":
    main()

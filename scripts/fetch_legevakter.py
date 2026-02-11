#!/usr/bin/env python3
"""
Leser kommunale legevakter fra Excel og skriver GeoJSON.
Adresser og koordinater dobbeltsjekkes med GeoNorge + Nominatim.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx

XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
WB_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}

GEONORGE_URL = "https://ws.geonorge.no/adresser/v1/sok"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "SafeMap/1.0 (legevakt-import)"

DEFAULT_EXCEL = Path(
    "/Users/marius/Downloads/Kopi-av-Offisiell-oversikt-legevakter-i-Norge-2024.xlsx"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "src" / "legevakter.json"
DEFAULT_REPORT = (
    Path(__file__).resolve().parent.parent / "src" / "legevakter_validation_report.json"
)

NOMINATIM_DELAY_SECONDS = 1.05
GEONORGE_DELAY_SECONDS = 0.05
WARN_COORD_DIFF_METERS = 500.0
DOUBT_COORD_DIFF_METERS = 2000.0


@dataclass(slots=True)
class LegevaktRow:
    source_row: int
    navn: str
    kommune: str
    adresse: str
    postnummer: str
    poststed: str


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def sanitize_postnummer(value: Any) -> str:
    raw = normalize_text(value)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw
    if len(digits) >= 4:
        return digits[:4]
    return digits.zfill(4)


def normalize_for_compare(value: str) -> str:
    text = normalize_text(value).lower()
    text = (
        text.replace("æ", "ae")
        .replace("ø", "o")
        .replace("å", "a")
    )
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\bgt\b", "gate", text)
    text = re.sub(r"\bvn\b", "veien", text)
    text = re.sub(r"\bv\b", "veien", text)
    text = re.sub(r"\bvei\b", "veien", text)
    text = re.sub(r"\bvei\.\b", "veien", text)
    text = re.sub(r"\bsv\.\b", "sving", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def cell_col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - 64)
    return idx


def parse_shared_strings(xlsx: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in xlsx.namelist():
        return []
    root = ET.fromstring(xlsx.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for si in root.findall(f"{XML_NS}si"):
        parts = [t.text or "" for t in si.iter(f"{XML_NS}t")]
        values.append("".join(parts))
    return values


def resolve_first_sheet_path(xlsx: zipfile.ZipFile) -> str:
    wb = ET.fromstring(xlsx.read("xl/workbook.xml"))
    first_sheet = wb.find("main:sheets/main:sheet", WB_NS)
    if first_sheet is None:
        raise ValueError("Fant ingen ark i workbook.xml")

    rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    if not rel_id:
        raise ValueError("Mangler relasjon-ID for første ark")

    rels = ET.fromstring(xlsx.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall("rel:Relationship", REL_NS):
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target", "")
            return f"xl/{target.lstrip('/')}"
    raise ValueError(f"Fant ikke ark-sti for relasjon {rel_id}")


def extract_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    v = cell.find(f"{XML_NS}v")

    if cell_type == "inlineStr":
        parts = [t.text or "" for t in cell.iter(f"{XML_NS}t")]
        return normalize_text("".join(parts))

    if v is None:
        return ""

    raw = normalize_text(v.text)
    if cell_type == "s":
        if raw.isdigit():
            idx = int(raw)
            if 0 <= idx < len(shared_strings):
                return normalize_text(shared_strings[idx])
        return raw

    if raw.endswith(".0"):
        return raw[:-2]
    return raw


def parse_sheet_rows(xlsx_path: Path) -> list[dict[int, str]]:
    with zipfile.ZipFile(xlsx_path) as xlsx:
        shared_strings = parse_shared_strings(xlsx)
        sheet_path = resolve_first_sheet_path(xlsx)
        sheet = ET.fromstring(xlsx.read(sheet_path))

    sheet_data = sheet.find(f"{XML_NS}sheetData")
    if sheet_data is None:
        return []

    rows: list[dict[int, str]] = []
    for row in sheet_data.findall(f"{XML_NS}row"):
        row_map: dict[int, str] = {}
        for cell in row.findall(f"{XML_NS}c"):
            ref = cell.attrib.get("r", "")
            if not ref:
                continue
            row_map[cell_col_index(ref)] = extract_cell_value(cell, shared_strings)
        rows.append(row_map)

    return rows


def find_column_index(header: dict[int, str], expected_terms: list[str]) -> int:
    normalized_header = {
        col_idx: normalize_for_compare(value) for col_idx, value in header.items()
    }
    for col_idx, text in normalized_header.items():
        if all(term in text for term in expected_terms):
            return col_idx
    raise ValueError(f"Fant ikke kolonne med nøkkelord: {expected_terms}")


def read_legevakter_from_excel(xlsx_path: Path) -> list[LegevaktRow]:
    rows = parse_sheet_rows(xlsx_path)
    if not rows:
        raise ValueError("Excel-filen inneholder ingen rader")

    header = rows[0]
    col_navn = find_column_index(header, ["legevaktnavn"])
    col_kommune = find_column_index(header, ["hovedkommuner"])
    col_adresse = find_column_index(header, ["besoksadresse", "legevakt"])
    col_postnummer = find_column_index(header, ["postnummer", "legevakt"])
    col_poststed = find_column_index(header, ["poststed", "legevakt"])

    legevakter: list[LegevaktRow] = []
    for idx, row in enumerate(rows[1:], start=2):
        navn = normalize_text(row.get(col_navn))
        kommune = normalize_text(row.get(col_kommune))
        adresse = normalize_text(row.get(col_adresse)).rstrip(",")
        postnummer = sanitize_postnummer(row.get(col_postnummer))
        poststed = normalize_text(row.get(col_poststed))

        if not (navn and kommune and adresse and postnummer and poststed):
            continue

        legevakter.append(
            LegevaktRow(
                source_row=idx,
                navn=navn,
                kommune=kommune,
                adresse=adresse,
                postnummer=postnummer,
                poststed=poststed,
            )
        )

    return legevakter


def has_kommune_match(source_value: str, candidate_value: str) -> bool:
    source_norm = normalize_for_compare(source_value)
    candidate_norm = normalize_for_compare(candidate_value)
    if not source_norm or not candidate_norm:
        return False
    if candidate_norm in source_norm:
        return True

    source_parts = re.split(r"[,/()-]", source_norm)
    for part in source_parts:
        part = part.strip()
        if part and (part == candidate_norm or part in candidate_norm):
            return True
    return False


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = normalize_text(item)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def expand_address_abbreviations(address: str) -> str:
    text = normalize_text(address)
    replacements = [
        (r"\bgt\.?\b", "gate"),
        (r"\bg\.\b", "gate"),
        (r"\bvn\.?\b", "vegen"),
        (r"\bv\.\b", "vegen"),
        (r"\bveg\.\b", "vegen"),
        (r"\bsv\.\b", "sving"),
        (r"\bveiengen\b", "vegen"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def address_variants(address: str) -> list[str]:
    base = normalize_text(address).strip(",")
    variants = [base]

    parts = [normalize_text(part) for part in re.split(r"[;,]", base) if normalize_text(part)]
    variants.extend(parts)
    variants.extend([part for part in parts if re.search(r"\d", part)])

    # Ta ut mulig gate+nummer-segment hvis teksten starter med institusjonsnavn.
    match = re.search(r"([A-Za-zÆØÅæøå0-9 .'\-]+?\d+[A-Za-z]?)", base)
    if match:
        variants.append(normalize_text(match.group(1)))

    expanded: list[str] = []
    for candidate in variants:
        expanded.append(candidate)
        expanded.append(expand_address_abbreviations(candidate))

    return dedupe_keep_order(expanded)


def kommune_variants(kommune: str) -> list[str]:
    base = normalize_text(kommune)
    parts = [normalize_text(part) for part in re.split(r"[,/()-]", base) if normalize_text(part)]
    if base and base not in parts:
        parts.append(base)
    return dedupe_keep_order(parts)


def geonorge_queries(row: LegevaktRow) -> list[str]:
    queries: list[str] = []
    kommuner = kommune_variants(row.kommune)
    hovedkommune = kommuner[0] if kommuner else row.kommune

    for address in address_variants(row.adresse):
        queries.append(f"{address} {row.postnummer} {row.poststed}")
        queries.append(f"{address} {row.poststed}")
        queries.append(f"{address} {hovedkommune}")
        queries.append(f"{address} Norge")
        if len(queries) >= 20:
            break

    return dedupe_keep_order(queries)[:20]


def nominatim_queries(
    row: LegevaktRow,
    preferred_address: str | None = None,
    preferred_postnummer: str | None = None,
    preferred_poststed: str | None = None,
) -> list[str]:
    queries: list[str] = []
    kommuner = kommune_variants(row.kommune)
    hovedkommune = kommuner[0] if kommuner else row.kommune

    if preferred_address:
        queries.append(
            ", ".join(
                part
                for part in [
                    preferred_address,
                    f"{preferred_postnummer or row.postnummer} {preferred_poststed or row.poststed}",
                    "Norge",
                ]
                if normalize_text(part)
            )
        )
        queries.append(
            ", ".join(
                part
                for part in [
                    preferred_address,
                    preferred_poststed or row.poststed,
                    "Norge",
                ]
                if normalize_text(part)
            )
        )
        queries.append(
            ", ".join(
                part
                for part in [
                    preferred_address,
                    f"{preferred_postnummer or row.postnummer} {preferred_poststed or row.poststed}",
                    hovedkommune,
                    "Norge",
                ]
                if normalize_text(part)
            )
        )

    for address in address_variants(row.adresse):
        queries.append(
            ", ".join(
                part
                for part in [
                    address,
                    f"{row.postnummer} {row.poststed}",
                    hovedkommune,
                    "Norge",
                ]
                if normalize_text(part)
            )
        )
        queries.append(
            ", ".join(
                part for part in [address, row.poststed, hovedkommune, "Norge"] if normalize_text(part)
            )
        )
        if len(queries) >= 12:
            break

    return dedupe_keep_order(queries)[:12]


def haversine_meters(a: list[float], b: list[float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    aa = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(aa), math.sqrt(1 - aa))
    return 6371000.0 * c


def score_geonorge_candidate(candidate: dict[str, Any], row: LegevaktRow) -> tuple[float, float]:
    candidate_address = normalize_text(
        candidate.get("adressetekst")
        or candidate.get("adressetekstutenadressetilleggsnavn")
        or ""
    )
    candidate_postnummer = sanitize_postnummer(candidate.get("postnummer"))
    candidate_poststed = normalize_text(candidate.get("poststed"))
    candidate_kommune = normalize_text(candidate.get("kommunenavn"))

    input_address_norm = normalize_for_compare(row.adresse)
    candidate_address_norm = normalize_for_compare(candidate_address)
    ratio = SequenceMatcher(None, input_address_norm, candidate_address_norm).ratio()

    score = ratio * 5.0
    if candidate_postnummer and candidate_postnummer == row.postnummer:
        score += 3.0
    if candidate_poststed and normalize_for_compare(candidate_poststed) == normalize_for_compare(
        row.poststed
    ):
        score += 2.0
    if has_kommune_match(row.kommune, candidate_kommune):
        score += 1.0
    if candidate_address_norm and candidate_address_norm == input_address_norm:
        score += 1.0

    return score, ratio


async def request_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str],
    extra_headers: dict[str, str] | None = None,
) -> Any | None:
    headers = extra_headers or {}
    for attempt in range(5):
        try:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait_seconds = float(retry_after) if retry_after else 2.0 * (attempt + 1)
                except ValueError:
                    wait_seconds = 2.0 * (attempt + 1)
                await asyncio.sleep(wait_seconds)
                continue
        except Exception:
            pass
        await asyncio.sleep(0.8 * (attempt + 1))
    return None


async def geocode_geonorge(client: httpx.AsyncClient, row: LegevaktRow) -> dict[str, Any] | None:
    scored: list[tuple[float, float, dict[str, Any]]] = []
    seen_candidates: set[tuple[str, str, str]] = set()

    for query in geonorge_queries(row):
        data = await request_json(
            client=client,
            url=GEONORGE_URL,
            params={
                "sok": query,
                "fuzzy": "true",
                "utkoordsys": "4258",
                "treffPerSide": "10",
            },
        )
        if not data:
            continue

        candidates = data.get("adresser", []) or []
        for candidate in candidates:
            address = normalize_text(candidate.get("adressetekst") or "")
            postnummer = sanitize_postnummer(candidate.get("postnummer") or "")
            kommunenummer = normalize_text(candidate.get("kommunenummer") or "")
            key = (address, postnummer, kommunenummer)
            if key in seen_candidates:
                continue
            seen_candidates.add(key)

            point = candidate.get("representasjonspunkt") or {}
            lat = point.get("lat")
            lon = point.get("lon")
            if lat is None or lon is None:
                continue
            score, ratio = score_geonorge_candidate(candidate, row)
            scored.append((score, ratio, candidate))

        await asyncio.sleep(GEONORGE_DELAY_SECONDS)

        if scored:
            best_score = max(item[0] for item in scored)
            if best_score >= 9.5:
                break

    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_ratio, best_candidate = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else None

    point = best_candidate.get("representasjonspunkt") or {}
    coords = [float(point["lon"]), float(point["lat"])]
    confidence = "high" if best_score >= 8.0 else "medium" if best_score >= 6.0 else "low"
    ambiguous = second_score is not None and (best_score - second_score) < 0.75

    return {
        "coordinates": coords,
        "address": normalize_text(
            best_candidate.get("adressetekst")
            or best_candidate.get("adressetekstutenadressetilleggsnavn")
            or row.adresse
        ),
        "postnummer": sanitize_postnummer(best_candidate.get("postnummer") or row.postnummer),
        "poststed": normalize_text(best_candidate.get("poststed") or row.poststed),
        "kommunenavn": normalize_text(best_candidate.get("kommunenavn")),
        "score": round(best_score, 3),
        "address_ratio": round(best_ratio, 3),
        "confidence": confidence,
        "ambiguous": ambiguous,
    }


async def geocode_nominatim(
    client: httpx.AsyncClient,
    row: LegevaktRow,
    geonorge_match: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    queries = nominatim_queries(
        row=row,
        preferred_address=geonorge_match.get("address") if geonorge_match else None,
        preferred_postnummer=geonorge_match.get("postnummer") if geonorge_match else None,
        preferred_poststed=geonorge_match.get("poststed") if geonorge_match else None,
    )

    for query in queries:
        data = await request_json(
            client=client,
            url=NOMINATIM_URL,
            params={
                "format": "jsonv2",
                "q": query,
                "limit": "1",
                "countrycodes": "no",
                "addressdetails": "1",
            },
            extra_headers={"User-Agent": USER_AGENT},
        )

        if not data or not isinstance(data, list):
            await asyncio.sleep(NOMINATIM_DELAY_SECONDS)
            continue
        if not data:
            await asyncio.sleep(NOMINATIM_DELAY_SECONDS)
            continue

        best = data[0]
        lat = best.get("lat")
        lon = best.get("lon")
        if lat is None or lon is None:
            await asyncio.sleep(NOMINATIM_DELAY_SECONDS)
            continue

        return {
            "coordinates": [float(lon), float(lat)],
            "display_name": normalize_text(best.get("display_name")),
            "type": normalize_text(best.get("type")),
        }

    return None


def make_feature(
    row: LegevaktRow,
    coords: list[float],
    verified_address: str,
    verified_postnummer: str,
    verified_poststed: str,
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {
            "navn": row.navn,
            "kommune": row.kommune,
            "adresse": verified_address,
            "postnummer": verified_postnummer,
            "poststed": verified_poststed,
        },
        "geometry": {
            "type": "Point",
            "coordinates": coords,
        },
    }


async def build_geojson_and_report(
    rows: list[LegevaktRow],
    warn_diff_meters: float,
    doubt_diff_meters: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    features: list[dict[str, Any]] = []
    report_entries: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    doubtful: list[dict[str, Any]] = []

    async with httpx.AsyncClient(
        timeout=30.0,
        verify=False,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        total = len(rows)
        for idx, row in enumerate(rows, start=1):
            print(f"[{idx}/{total}] {row.navn}")

            geonorge = await geocode_geonorge(client, row)
            await asyncio.sleep(GEONORGE_DELAY_SECONDS)
            nominatim = await geocode_nominatim(client, row)
            await asyncio.sleep(NOMINATIM_DELAY_SECONDS)

            warnings: list[str] = []
            coordinate_difference_m: float | None = None

            if geonorge and nominatim:
                coordinate_difference_m = haversine_meters(
                    geonorge["coordinates"], nominatim["coordinates"]
                )
                if coordinate_difference_m > warn_diff_meters:
                    warnings.append(
                        f"coordinate_diff_gt_{int(warn_diff_meters)}m"
                    )
                if coordinate_difference_m > doubt_diff_meters:
                    warnings.append(
                        f"coordinate_diff_gt_{int(doubt_diff_meters)}m"
                    )

            if geonorge and geonorge["confidence"] == "low":
                warnings.append("low_geonorge_confidence")
            if geonorge and geonorge["ambiguous"]:
                warnings.append("ambiguous_geonorge_match")
            if not geonorge:
                warnings.append("missing_geonorge_match")
            if not nominatim:
                warnings.append("missing_nominatim_match")

            chosen_coords: list[float] | None = None
            verified_address = row.adresse
            verified_postnummer = row.postnummer
            verified_poststed = row.poststed

            if geonorge:
                chosen_coords = geonorge["coordinates"]
                verified_address = geonorge["address"] or row.adresse
                verified_postnummer = geonorge["postnummer"] or row.postnummer
                verified_poststed = geonorge["poststed"] or row.poststed
            elif nominatim:
                chosen_coords = nominatim["coordinates"]

            if not chosen_coords:
                unresolved.append(
                    {
                        "source_row": row.source_row,
                        "navn": row.navn,
                        "kommune": row.kommune,
                        "adresse": row.adresse,
                        "postnummer": row.postnummer,
                        "poststed": row.poststed,
                        "warnings": warnings,
                    }
                )
                continue

            if any(tag in warnings for tag in ["coordinate_diff_gt_2000m", "low_geonorge_confidence"]):
                doubtful.append(
                    {
                        "source_row": row.source_row,
                        "navn": row.navn,
                        "warnings": warnings,
                    }
                )

            feature = make_feature(
                row=row,
                coords=chosen_coords,
                verified_address=verified_address,
                verified_postnummer=verified_postnummer,
                verified_poststed=verified_poststed,
            )
            features.append(feature)

            report_entries.append(
                {
                    "source_row": row.source_row,
                    "navn": row.navn,
                    "input": {
                        "kommune": row.kommune,
                        "adresse": row.adresse,
                        "postnummer": row.postnummer,
                        "poststed": row.poststed,
                    },
                    "selected": {
                        "adresse": verified_address,
                        "postnummer": verified_postnummer,
                        "poststed": verified_poststed,
                        "coordinates": chosen_coords,
                    },
                    "geonorge": geonorge,
                    "nominatim": nominatim,
                    "coordinate_difference_m": (
                        round(coordinate_difference_m, 1)
                        if coordinate_difference_m is not None
                        else None
                    ),
                    "warnings": warnings,
                }
            )

    geojson = {"type": "FeatureCollection", "features": features}
    report = {
        "summary": {
            "total_input_rows": len(rows),
            "features_written": len(features),
            "unresolved_count": len(unresolved),
            "doubtful_count": len(doubtful),
            "warn_coord_diff_meters": warn_diff_meters,
            "doubt_coord_diff_meters": doubt_diff_meters,
        },
        "unresolved": unresolved,
        "doubtful": doubtful,
        "entries": report_entries,
    }
    return geojson, report


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


async def run(args: argparse.Namespace) -> int:
    xlsx_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()

    if not xlsx_path.exists():
        print(f"Fant ikke inputfil: {xlsx_path}")
        return 1

    rows = read_legevakter_from_excel(xlsx_path)
    if not rows:
        print("Fant ingen legevaktrader i Excel-filen.")
        return 1

    print(f"Leste {len(rows)} legevakter fra {xlsx_path}")
    geojson, report = await build_geojson_and_report(
        rows=rows,
        warn_diff_meters=args.warn_diff_meters,
        doubt_diff_meters=args.doubt_diff_meters,
    )

    write_json(output_path, geojson)
    write_json(report_path, report)

    summary = report["summary"]
    print()
    print(f"Skrev {summary['features_written']} legevakter til {output_path}")
    print(f"Skrev valideringsrapport til {report_path}")
    print(
        "Uavklarte: "
        f"{summary['unresolved_count']}, tvetydige/lav tillit: {summary['doubtful_count']}"
    )

    if args.strict and (summary["unresolved_count"] > 0 or summary["doubtful_count"] > 0):
        return 2

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Importer legevakter fra Excel, valider mot GeoNorge/Nominatim, "
            "og skriv GeoJSON."
        )
    )
    parser.add_argument("--input", default=str(DEFAULT_EXCEL), help="Sti til Excel-fil")
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT), help="Sti til output GeoJSON-fil"
    )
    parser.add_argument(
        "--report", default=str(DEFAULT_REPORT), help="Sti til valideringsrapport (JSON)"
    )
    parser.add_argument(
        "--warn-diff-meters",
        dest="warn_diff_meters",
        type=float,
        default=WARN_COORD_DIFF_METERS,
        help="Varselgrense for avstand mellom kilder (meter)",
    )
    parser.add_argument(
        "--doubt-diff-meters",
        dest="doubt_diff_meters",
        type=float,
        default=DOUBT_COORD_DIFF_METERS,
        help="Tvilgrense for avstand mellom kilder (meter)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Returner feilkode hvis noe er uavklart eller tvetydig",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(run(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

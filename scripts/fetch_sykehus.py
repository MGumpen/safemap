#!/usr/bin/env python3
"""
Script for aa hente sykehus fra Bronnoysundregisteret
og geokode adressene til en GeoJSON-fil.
"""

import asyncio
import json
import re
from pathlib import Path

import httpx

DEFAULT_HEADERS = {"User-Agent": "SafeMap/1.0 (local)"}
WIKIPEDIA_WIKITEXT_URL = (
    "https://no.wikipedia.org/w/index.php"
    "?title=Liste_over_norske_sykehus"
    "&action=raw"
)
WIKIPEDIA_FALLBACK_URL = (
    "https://r.jina.ai/http://no.wikipedia.org/w/index.php"
    "?title=Liste_over_norske_sykehus"
    "&action=raw"
)


def normalize_upper(value: str | None) -> str:
    return (value or "").strip().upper()


def normalize_name_for_match(value: str | None) -> str:
    name = normalize_upper(value)
    name = name.replace("SJUK", "SYK")
    name = name.replace("SYKEEHUS", "SYKEHUS")
    name = name.replace("SYKEESTUGU", "SYKESTUGU")
    name = " ".join(name.split())
    return name


MANUAL_OVERRIDES = {
    (
        normalize_name_for_match("Nordlandssykehuset Vesterålen"),
        normalize_upper("Hadsel"),
    ): {
        "adresse": "Knut Hamsunsgate",
        "postnummer": "8450",
        "poststed": "Stokmarknes",
        "kommune": "Hadsel",
        "coordinates": [14.9102326, 68.5600072],
    },
    (
        normalize_name_for_match("Universitetssykehuset Nord-Norge"),
        normalize_upper("Harstad"),
    ): {
        "adresse": "St Olavs gate",
        "postnummer": "9406",
        "poststed": "Harstad",
        "kommune": "Harstad",
        "coordinates": [16.5252583, 68.7962475],
    },
    (
        normalize_name_for_match("Universitetssykehuset Nord-Norge"),
        normalize_upper("Narvik"),
    ): {
        "adresse": "Sykehusveien",
        "postnummer": "8516",
        "poststed": "Narvik",
        "kommune": "Narvik",
        "coordinates": [17.4131795, 68.4420993],
    },
    (
        normalize_name_for_match("Finnmarkssykehuset"),
        normalize_upper("Sør-Varanger"),
    ): {
        "adresse": "Skytterhusveien 2",
        "postnummer": "9900",
        "poststed": "Kirkenes",
        "kommune": "Sør-Varanger",
        "coordinates": [30.0344410, 69.7068580],
    },
    (
        normalize_name_for_match("Haukeland universitetssykehus"),
        normalize_upper("Voss"),
    ): {
        "adresse": "Sjukehusvegen 16",
        "postnummer": "5704",
        "poststed": "Voss",
        "kommune": "Voss",
        "coordinates": [6.4203925, 60.6330514],
    },
}


def clean_wikitext_value(value: str) -> str:
    value = re.sub(r"<ref[^>]*>.*?</ref>", "", value)
    value = re.sub(r"<ref[^/]*/>", "", value)
    value = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"''+", "", value)
    value = re.sub(r"\[\d+\]", "", value)
    return value.strip()


def extract_hospital_entries_from_wikitext(wikitext: str) -> list[dict]:
    lines = wikitext.splitlines()
    entries: list[dict] = []

    in_list_section = False
    in_table = False
    current_cells: list[str] = []

    for line in lines:
        if line.startswith("==") and "Liste" in line:
            in_list_section = True
            continue

        if in_list_section and line.startswith("==") and "Liste" not in line:
            in_list_section = False

        if in_list_section:
            if line.startswith("{|"):
                in_table = True
                continue

            if in_table:
                if line.startswith("|}"):
                    if len(current_cells) >= 2:
                        entries.append(
                            {
                                "name": current_cells[0],
                                "kommune": current_cells[1],
                            }
                        )
                    in_table = False
                    current_cells = []
                    continue
                if line.startswith("|-"):
                    if len(current_cells) >= 2:
                        entries.append(
                            {
                                "name": current_cells[0],
                                "kommune": current_cells[1],
                            }
                        )
                    current_cells = []
                    continue
                if not line.startswith("|"):
                    continue

                cell = line.lstrip("|").strip()
                if "|" in cell:
                    cell = cell.split("|", 1)[1].strip()

                link_match = re.search(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", cell)
                value = clean_wikitext_value(link_match.group(1) if link_match else cell)
                if value and len(current_cells) < 2:
                    current_cells.append(value)

    filtered = []
    for entry in entries:
        name = entry.get("name", "")
        if re.search(r"[A-ZÆØÅ]", normalize_upper(name)):
            filtered.append(entry)

    return filtered


async def fetch_wikipedia_allowlist(client) -> list[dict]:
    try:
        response = await client.get(WIKIPEDIA_WIKITEXT_URL, headers=DEFAULT_HEADERS)
        if response.status_code != 200:
            response = await client.get(WIKIPEDIA_FALLBACK_URL, headers=DEFAULT_HEADERS)
            if response.status_code != 200:
                print(
                    "Fikk ikke hentet sykehusliste fra Wikipedia: "
                    f"{response.status_code}"
                )
                return set()

        wikitext = response.text
        if not wikitext:
            return []

        entries = extract_hospital_entries_from_wikitext(wikitext)
        return entries
    except Exception as exc:
        print(f"Klarte ikke aa hente sykehusliste fra Wikipedia: {exc}")
        return []


async def geocode_address(client, address, postnummer, poststed, kommune):
    """Geokod en adresse ved hjelp av Nominatim"""
    query = [address, postnummer, poststed, kommune, "Norge"]
    query_str = ", ".join(filter(None, query))

    try:
        response = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "format": "json",
                "q": query_str,
                "limit": 1,
                "addressdetails": 1,
            },
            headers=DEFAULT_HEADERS,
        )

        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                item = data[0]
                addr = item.get("address", {})
                road = addr.get("road")
                house_number = addr.get("house_number")
                if road and house_number:
                    address_line = f"{road} {house_number}"
                else:
                    address_line = road or item.get("display_name")

                postnummer = addr.get("postcode")
                poststed = (
                    addr.get("city")
                    or addr.get("town")
                    or addr.get("village")
                    or addr.get("municipality")
                )
                kommune = addr.get("municipality") or kommune

                return {
                    "coordinates": [float(item["lon"]), float(item["lat"])],
                    "adresse": address_line,
                    "postnummer": postnummer,
                    "poststed": poststed,
                    "kommune": kommune,
                }
    except Exception as e:
        print(f"Geokoding feilet for {query_str}: {e}")

    return None


async def fetch_sykehus():
    """Hent sykehus fra Bronnoysundregisteret"""
    sykehus = []

    async with httpx.AsyncClient(timeout=30.0, headers=DEFAULT_HEADERS) as client:
        print("Henter sykehusliste fra Wikipedia...")

        entries = await fetch_wikipedia_allowlist(client)
        if not entries:
            print("Fikk ikke hentet sykehusliste, avbryter.")
            return []

        print(f"Fant {len(entries)} sykehus i listen")

        for i, entry in enumerate(entries):
            navn = entry["name"]
            kommune = entry.get("kommune")
            print(f"\n[{i + 1}/{len(entries)}] Behandler: {navn}")

            override_key = (
                normalize_name_for_match(navn),
                normalize_upper(kommune) if kommune else None,
            )

            if override_key in MANUAL_OVERRIDES:
                geo = MANUAL_OVERRIDES[override_key]
                print(f"  ✓ Manuell adresse: {geo['adresse']}")
            else:
                print(
                    f"  📍 Geokoder: {navn}" + (f", {kommune}" if kommune else "")
                )
                geo = await geocode_address(client, navn, None, None, kommune)

            if geo:
                print(f"  ✓ Koordinater: {geo['coordinates']}")
                sykehus.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "navn": navn,
                            "adresse": geo.get("adresse"),
                            "postnummer": geo.get("postnummer"),
                            "poststed": geo.get("poststed"),
                            "kommune": geo.get("kommune") or kommune,
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": geo["coordinates"],
                        },
                    }
                )
            else:
                print("  ✗ Kunne ikke geokode")

            # Respekter rate limit for Nominatim (1 req/sekund)
            await asyncio.sleep(1.1)

    return sykehus


async def main():
    sykehus = await fetch_sykehus()

    if sykehus:
        geojson = {
            "type": "FeatureCollection",
            "features": sykehus,
        }

        output_file = Path(__file__).parent.parent / "src" / "sykehus.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)

        print(f"\n✓ Skrev {len(sykehus)} sykehus til {output_file}")
    else:
        print("\n✗ Ingen sykehus funnet")


if __name__ == "__main__":
    asyncio.run(main())

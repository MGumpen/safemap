#!/usr/bin/env python3
"""
Verify Overpass API data for hospitals and police stations in Norway.
Run this script to see what data is available before importing to PostGIS.
"""

import json
import requests
from typing import Any

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

QUERIES = {
    "hospital": """
[out:json][timeout:120];
area["ISO3166-1"="NO"]->.norway;
(
  node["amenity"="hospital"](area.norway);
  way["amenity"="hospital"](area.norway);
  relation["amenity"="hospital"](area.norway);
);
out center;
""",
    "police": """
[out:json][timeout:120];
area["ISO3166-1"="NO"]->.norway;
(
  node["amenity"="police"](area.norway);
  way["amenity"="police"](area.norway);
  relation["amenity"="police"](area.norway);
);
out center;
""",
}


def fetch_overpass(query: str) -> dict[str, Any]:
    """Fetch data from Overpass API."""
    response = requests.post(OVERPASS_URL, data={"data": query}, timeout=180)
    response.raise_for_status()
    return response.json()


def extract_features(data: dict[str, Any], poi_type: str) -> list[dict[str, Any]]:
    """Extract features from Overpass response into a simple list."""
    features = []
    for element in data.get("elements", []):
        # Get coordinates (for ways/relations, use 'center')
        if element["type"] == "node":
            lat, lon = element["lat"], element["lon"]
        else:
            center = element.get("center", {})
            lat, lon = center.get("lat"), center.get("lon")
            if lat is None or lon is None:
                continue

        tags = element.get("tags", {})
        name = tags.get("name", tags.get("name:no", "Unnamed"))

        features.append({
            "osm_id": element["id"],
            "osm_type": element["type"],
            "type": poi_type,
            "name": name,
            "lat": lat,
            "lon": lon,
            "tags": tags,
        })
    return features


def main() -> None:
    print("=" * 60)
    print("OVERPASS DATA VERIFICATION FOR NORWAY")
    print("=" * 60)

    all_features: dict[str, list[dict[str, Any]]] = {}

    for poi_type, query in QUERIES.items():
        print(f"\n📍 Fetching {poi_type.upper()} data from Overpass API...")
        try:
            data = fetch_overpass(query)
            features = extract_features(data, poi_type)
            all_features[poi_type] = features

            print(f"   ✅ Found {len(features)} {poi_type} locations")

            # Show first 10 as sample
            print(f"\n   Sample (first 10):")
            print(f"   {'Name':<40} {'Lat':>10} {'Lon':>10}")
            print(f"   {'-'*40} {'-'*10} {'-'*10}")
            for f in features[:10]:
                name = f["name"][:38] if len(f["name"]) > 38 else f["name"]
                print(f"   {name:<40} {f['lat']:>10.5f} {f['lon']:>10.5f}")

            if len(features) > 10:
                print(f"   ... and {len(features) - 10} more")

        except requests.RequestException as e:
            print(f"   ❌ Error fetching {poi_type}: {e}")

    # Save to JSON for inspection
    output_file = "overpass_verification.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_features, f, ensure_ascii=False, indent=2)
    print(f"\n📁 Full data saved to: {output_file}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for poi_type, features in all_features.items():
        print(f"  {poi_type.upper()}: {len(features)} locations")

    print("\n✅ Verification complete. Review the data above.")
    print("   If it looks correct, proceed with the full ingestion script.")


if __name__ == "__main__":
    main()

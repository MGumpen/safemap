#!/usr/bin/env python3
"""Quick verification - writes results to file."""
import json
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

def main():
    results = {}
    
    # Fetch hospitals
    print("Fetching hospitals...")
    query = """
[out:json][timeout:120];
area["ISO3166-1"="NO"]->.norway;
(
  node["amenity"="hospital"](area.norway);
  way["amenity"="hospital"](area.norway);
  relation["amenity"="hospital"](area.norway);
);
out center;
"""
    r = requests.post(OVERPASS_URL, data={"data": query}, timeout=180)
    data = r.json()
    hospitals = []
    for el in data.get("elements", []):
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        else:
            c = el.get("center", {})
            lat, lon = c.get("lat"), c.get("lon")
            if not lat: continue
        name = el.get("tags", {}).get("name", "Unnamed")
        hospitals.append({"name": name, "lat": lat, "lon": lon})
    results["hospitals"] = hospitals
    
    # Fetch police
    print("Fetching police...")
    query = """
[out:json][timeout:120];
area["ISO3166-1"="NO"]->.norway;
(
  node["amenity"="police"](area.norway);
  way["amenity"="police"](area.norway);
  relation["amenity"="police"](area.norway);
);
out center;
"""
    r = requests.post(OVERPASS_URL, data={"data": query}, timeout=180)
    data = r.json()
    police = []
    for el in data.get("elements", []):
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        else:
            c = el.get("center", {})
            lat, lon = c.get("lat"), c.get("lon")
            if not lat: continue
        name = el.get("tags", {}).get("name", "Unnamed")
        police.append({"name": name, "lat": lat, "lon": lon})
    results["police"] = police
    
    # Write summary
    with open("verification_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    summary = f"""
=====================================
OVERPASS DATA VERIFICATION - NORWAY
=====================================

HOSPITALS: {len(hospitals)} locations
Sample (first 5):
"""
    for h in hospitals[:5]:
        summary += f"  - {h['name']}: ({h['lat']:.4f}, {h['lon']:.4f})\n"
    
    summary += f"""
POLICE: {len(police)} locations
Sample (first 5):
"""
    for p in police[:5]:
        summary += f"  - {p['name']}: ({p['lat']:.4f}, {p['lon']:.4f})\n"
    
    summary += f"""
=====================================
Full data saved to: verification_results.json
=====================================
"""
    
    with open("verification_summary.txt", "w", encoding="utf-8") as f:
        f.write(summary)
    
    print("Done! Check verification_summary.txt")

if __name__ == "__main__":
    main()

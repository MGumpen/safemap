#!/usr/bin/env python3
"""
Script for å hente kommunale legevakter fra Brønnøysundregisteret
og geokode adressene til en GeoJSON-fil.
"""

import httpx
import json
import asyncio
from pathlib import Path
import time

# Institusjonelle sektorkoder for offentlig forvaltning
PUBLIC_SECTOR_CODES = ["6100", "6500"]  # Stats- og kommuneforvaltning

async def geocode_address(client, address, postnummer, poststed, kommune):
    """Geokod en adresse ved hjelp av Nominatim"""
    query = [address, postnummer, poststed, kommune, 'Norge']
    query_str = ', '.join(filter(None, query))
    
    try:
        response = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "format": "json",
                "q": query_str,
                "limit": 1
            },
            headers={"User-Agent": "SafeMap/1.0"}
        )
        
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                return [float(data[0]['lon']), float(data[0]['lat'])]
    except Exception as e:
        print(f"Geokoding feilet for {query_str}: {e}")
    
    return None

def is_kommunal_legevakt(enhet):
    """Sjekk om enheten er en kommunal legevakt"""
    navn = enhet.get('navn', '').upper()
    
    # Må inneholde "LEGEVAKT"
    if 'LEGEVAKT' not in navn:
        return False
    
    # Ekskluder private og nedlagte
    exclude_terms = ['PRIVAT', 'AS', 'TEST', 'NEDLAGT', 'KONKURS', 'AVVIKLET']
    if any(term in navn for term in exclude_terms):
        return False
    
    # Sjekk institusjonell sektorkode (offentlig)
    inst_sektor = enhet.get('institusjonellSektorkode', {})
    if inst_sektor and inst_sektor.get('kode') in PUBLIC_SECTOR_CODES:
        return True
    
    # Sjekk organisasjonsform (skal være kommunal)
    org_form = enhet.get('organisasjonsform', {}).get('kode', '')
    if org_form in ['KOMM', 'FYLK', 'STAT']:
        return True
    
    # Hvis navnet tydelig indikerer kommunal legevakt
    kommunal_indicators = ['KOMMUNAL', 'KOMMUNE', 'INTERKOMMUNAL', 'KF']
    if any(ind in navn for ind in kommunal_indicators):
        return True
    
    return False

async def fetch_legevakter():
    """Hent kommunale legevakter fra Brønnøysundregisteret"""
    
    legevakter = []
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("Henter legevakter fra Brønnøysundregisteret...")
        
        # Søk etter enheter med "legevakt" i navnet
        response = await client.get(
            "https://data.brreg.no/enhetsregisteret/api/enheter",
            params={
                "navn": "legevakt",
                "size": 300
            }
        )
        
        if response.status_code != 200:
            print(f"Feil ved henting: {response.status_code}")
            return []
        
        data = response.json()
        
        if "_embedded" not in data or "enheter" not in data["_embedded"]:
            print("Ingen enheter funnet")
            return []
        
        enheter = data["_embedded"]["enheter"]
        print(f"Fant {len(enheter)} enheter med 'legevakt' i navnet")
        
        # Filtrer og geokod kommunale legevakter
        kommunale = [e for e in enheter if is_kommunal_legevakt(e)]
        print(f"Filtrerte ned til {len(kommunale)} kommunale legevakter")
        
        for i, enhet in enumerate(kommunale):
            navn = enhet.get('navn')
            print(f"\n[{i+1}/{len(kommunale)}] Behandler: {navn}")
            
            # Hent adresse
            forretningsadresse = enhet.get('forretningsadresse', {})
            adresse_liste = forretningsadresse.get('adresse', [])
            adresse = ', '.join(adresse_liste) if adresse_liste else None
            postnummer = forretningsadresse.get('postnummer')
            poststed = forretningsadresse.get('poststed')
            kommune = forretningsadresse.get('kommune')
            
            if not adresse or not postnummer:
                print(f"  ⚠️  Mangler adresse, hopper over")
                continue
            
            # Geokod adresse
            print(f"  📍 Geokoder: {adresse}, {postnummer} {poststed}")
            coords = await geocode_address(client, adresse, postnummer, poststed, kommune)
            
            if coords:
                print(f"  ✓ Koordinater: {coords}")
                legevakter.append({
                    "type": "Feature",
                    "properties": {
                        "navn": navn,
                        "adresse": adresse,
                        "postnummer": postnummer,
                        "poststed": poststed,
                        "kommune": kommune,
                        "organisasjonsnummer": enhet.get('organisasjonsnummer')
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": coords
                    }
                })
            else:
                print(f"  ✗ Kunne ikke geokode")
            
            # Respekter rate limit for Nominatim (1 req/sekund)
            await asyncio.sleep(1.1)
    
    return legevakter

async def main():
    legevakter = await fetch_legevakter()
    
    if legevakter:
        geojson = {
            "type": "FeatureCollection",
            "features": legevakter
        }
        
        # Skriv til fil
        output_file = Path(__file__).parent.parent / "src" / "legevakter.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)
        
        print(f"\n✓ Skrev {len(legevakter)} kommunale legevakter til {output_file}")
    else:
        print("\n✗ Ingen legevakter funnet")

if __name__ == "__main__":
    asyncio.run(main())

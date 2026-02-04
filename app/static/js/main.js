// Initialize map centered on Norway
const map = L.map('map').setView([65.0, 13.0], 5);

// Add OpenStreetMap tiles
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors',
  maxZoom: 18
}).addTo(map);

const radiusForZoom = (zoom) => {
  const r = 2 + (zoom - 4) * 0.5;
  return Math.max(2, Math.min(6, r));
};

const apiUrl = '/api/brannstasjoner';

const parseWktPoint = (wkt) => {
  if (!wkt || typeof wkt !== 'string') return null;
  const match = wkt.match(/POINT\s*\(\s*([\d.-]+)\s+([\d.-]+)\s*\)/i);
  if (!match) return null;
  return { lng: Number(match[1]), lat: Number(match[2]) };
};

const findLatLng = (row) => {
  const latKeys = ['lat', 'latitude', 'y', 'latitud'];
  const lngKeys = ['lng', 'lon', 'longitude', 'x', 'longitud'];
  for (const latKey of latKeys) {
    for (const lngKey of lngKeys) {
      if (row[latKey] != null && row[lngKey] != null) {
        return { lat: Number(row[latKey]), lng: Number(row[lngKey]) };
      }
    }
  }

  const geo = row.geometry || row.geom || row.shape;
  if (geo) {
    if (typeof geo === 'string') {
      const point = parseWktPoint(geo);
      if (point) return point;
      try {
        const parsed = JSON.parse(geo);
        if (parsed && parsed.type && parsed.coordinates) {
          return { lng: parsed.coordinates[0], lat: parsed.coordinates[1] };
        }
      } catch (_) {}
    } else if (geo.type && geo.coordinates) {
      return { lng: geo.coordinates[0], lat: geo.coordinates[1] };
    }
  }

  return null;
};

const labelForRow = (row) => row.brannstasjon || row.navn || row.name || 'Brannstasjon';

const markers = L.featureGroup().addTo(map);

const addStationToMap = (row) => {
  const coords = findLatLng(row);
  if (!coords || Number.isNaN(coords.lat) || Number.isNaN(coords.lng)) return;
  L.circleMarker([coords.lat, coords.lng], {
    radius: radiusForZoom(map.getZoom()),
    color: '#d62828',
    weight: 2,
    fillColor: '#f77f00',
    fillOpacity: 0.8
  }).addTo(markers).bindPopup(labelForRow(row));
};

const updateMarkerSizes = () => {
  const radius = radiusForZoom(map.getZoom());
  markers.eachLayer((layer) => {
    if (layer.setRadius) {
      layer.setRadius(radius);
    }
  });
};

const loadStations = async () => {
  try {
    const res = await fetch(apiUrl);
    if (!res.ok) throw new Error(`API-feil: ${res.status}`);
    const data = await res.json();
    if (Array.isArray(data)) {
      data.forEach(addStationToMap);
      if (markers.getLayers().length > 0) {
        map.fitBounds(markers.getBounds().pad(0.2));
      }
    } else {
      console.error('Uventet svar fra API:', data);
    }
  } catch (err) {
    console.error('Klarte ikke hente brannstasjoner:', err);
  }
};

loadStations();

map.on('zoomend', updateMarkerSizes);
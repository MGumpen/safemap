console.log("Safemap landing page loaded");

// Default fallback location (UiA)
const DEFAULT_LOCATION = [58.1456, 8.0119];
const DEFAULT_ZOOM = 14;

// Initialize map - will be centered after geolocation
const map = L.map('map').setView(DEFAULT_LOCATION, DEFAULT_ZOOM);

// Variable to store user location circle
let userLocationCircle = null;

// Try to get and watch user's current location
if (navigator.geolocation) {
  navigator.geolocation.watchPosition(
    (position) => {
      const lat = position.coords.latitude;
      const lng = position.coords.longitude;
      const accuracy = position.coords.accuracy;

      console.log(`Din lokasjon: ${lat}, ${lng} (nøyaktighet: ${accuracy}m)`);

      // Center map on first location
      if (!userLocationCircle) {
        map.setView([lat, lng], DEFAULT_ZOOM);
      }

      // Remove old circle if it exists
      if (userLocationCircle) {
        map.removeLayer(userLocationCircle);
      }

      // Add new circle at current position
      userLocationCircle = L.circleMarker([lat, lng], {
        radius: 8,
        fillColor: '#4285F4',
        color: '#ffffff',
        weight: 2,
        opacity: 1,
        fillOpacity: 0.8
      }).addTo(map).bindPopup('Din nåværende lokasjon');
    },
    (error) => {
      console.log(`Kunne ikke hente din lokasjon: ${error.message}. Bruker standard lokasjon.`);
    },
    {
      enableHighAccuracy: true,
      timeout: 5000,
      maximumAge: 0
    }
  );
} else {
  console.log("Nettleseren støtter ikke geolocation");
}

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

// Custom icon for hospitals (red with S)
const hospitalIcon = L.divIcon({
  className: 'hospital-marker',
  html: '<div style="background-color: #c0392b; width: 32px; height: 32px; border-radius: 50%; border: 3px solid white; box-shadow: 0 3px 6px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 18px; font-family: Arial, sans-serif;">S</div>',
  iconSize: [32, 32],
  iconAnchor: [16, 16]
});

// Custom icon for emergency clinics (legevakter)
const legevaktIcon = L.divIcon({
  className: 'legevakt-marker',
  html: '<div style="background-color: #27ae60; width: 32px; height: 32px; border-radius: 50%; border: 3px solid white; box-shadow: 0 3px 6px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 18px; font-family: Arial, sans-serif;">L</div>',
  iconSize: [32, 32],
  iconAnchor: [16, 16]
});

// Load and display hospitals
async function loadHospitals() {
  const loadingIndicator = document.getElementById('loading');
  
  try {
    const response = await fetch('/api/health-institutions');
    const data = await response.json();
    
    const hospitalCount = data.features.length;
    console.log(`Lastet ${hospitalCount} sykehus`);
    
    if (loadingIndicator) {
      loadingIndicator.textContent = `Laster legevakter...`;
    }
    
    // Create layer group for hospitals
    const hospitalLayer = L.layerGroup().addTo(map);
    
    // Add each hospital to the map
    data.features.forEach(feature => {
      const coords = feature.geometry.coordinates;
      const props = feature.properties;
      
      // GeoJSON uses [lon, lat], Leaflet uses [lat, lon]
      const marker = L.marker([coords[1], coords[0]], { icon: hospitalIcon }).addTo(hospitalLayer);
      
      // Create popup with hospital details
      const popupContent = `
        <div style="min-width: 200px;">
          <h3 style="margin: 0 0 10px 0; font-size: 15px; font-weight: bold; color: #c0392b;">
            ${props.navn}
          </h3>
          <p style="margin: 5px 0; font-size: 12px;"><strong>Type:</strong> ${props.type}</p>
          <p style="margin: 5px 0; font-size: 12px;"><strong>Kommune:</strong> ${props.kommune}</p>
        </div>
      `;
      
      marker.bindPopup(popupContent);
    });
    
    console.log(`Viser ${hospitalCount} sykehus på kartet`);
    
    // Load legevakter
    await loadLegevakter(hospitalCount);
    
  } catch (error) {
    console.error('Feil ved lasting av sykehus:', error);
    if (loadingIndicator) {
      loadingIndicator.textContent = 'Feil ved lasting av data';
      loadingIndicator.style.backgroundColor = '#e74c3c';
      loadingIndicator.style.color = 'white';
    }
  }
}

// Load and display legevakter
async function loadLegevakter(hospitalCount) {
  const loadingIndicator = document.getElementById('loading');
  
  try {
    const response = await fetch('/api/emergency-clinics');
    const data = await response.json();
    
    const legevaktCount = data.features.length;
    console.log(`Lastet ${legevaktCount} legevakter`);
    
    // Create layer group for legevakter
    const legevaktLayer = L.layerGroup().addTo(map);
    
    // Add each legevakt to the map
    data.features.forEach(feature => {
      const coords = feature.geometry.coordinates;
      const props = feature.properties;
      
      // GeoJSON uses [lon, lat], Leaflet uses [lat, lon]
      const marker = L.marker([coords[1], coords[0]], { icon: legevaktIcon }).addTo(legevaktLayer);
      
      // Create popup with legevakt details
      const popupContent = `
        <div style="min-width: 200px;">
          <h3 style="margin: 0 0 10px 0; font-size: 15px; font-weight: bold; color: #27ae60;">
            ${props.navn}
          </h3>
          <p style="margin: 5px 0; font-size: 12px;"><strong>Adresse:</strong> ${props.adresse}</p>
          <p style="margin: 5px 0; font-size: 12px;"><strong>Poststed:</strong> ${props.postnummer} ${props.poststed}</p>
          <p style="margin: 5px 0; font-size: 12px;"><strong>Kommune:</strong> ${props.kommune}</p>
        </div>
      `;
      
      marker.bindPopup(popupContent);
    });
    
    console.log(`Viser ${legevaktCount} legevakter på kartet`);
    
    // Hide loading indicator after showing summary
    if (loadingIndicator) {
      loadingIndicator.textContent = `${hospitalCount} sykehus og ${legevaktCount} legevakter`;
      setTimeout(() => {
        loadingIndicator.style.display = 'none';
      }, 2000);
    }
    
  } catch (error) {
    console.error('Feil ved lasting av legevakter:', error);
    if (loadingIndicator) {
      loadingIndicator.textContent = `${hospitalCount} sykehus (legevakter feilet)`;
      setTimeout(() => {
        loadingIndicator.style.display = 'none';
      }, 3000);
    }
  }
}

// Load hospitals when page loads
loadHospitals();

// Load shelter data (GeoJSON in EPSG:25833) and plot on the map
proj4.defs("EPSG:25833", "+proj=utm +zone=33 +ellps=GRS80 +units=m +no_defs");

fetch("/static/Tilfluktsrom.json")
  .then((response) => response.json())
  .then((geojson) => {
    const bounds = [];

    geojson.features.forEach((feature) => {
      if (!feature.geometry || feature.geometry.type !== "Point") {
        return;
      }

      const [x, y] = feature.geometry.coordinates;
      const [lon, lat] = proj4("EPSG:25833", "EPSG:4326", [x, y]);

      const props = feature.properties || {};
      const popup = `
        <strong>Tilfluktsrom</strong><br />
        Adresse: ${props.adresse || "Ukjent"}<br />
        Plasser: ${props.plasser ?? "Ukjent"}
      `;

      const shelterIcon = L.divIcon({
        className: "shelter-icon",
        html: `
          <div style="
            width: 18px;
            height: 18px;
            background: #facc15;
            border: 2px solid #000;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 12px;
            color: #000;
          ">T</div>
        `,
        iconSize: [18, 18],
        iconAnchor: [9, 9],
        popupAnchor: [0, -9],
      });

      L.marker([lat, lon], { icon: shelterIcon })
        .addTo(map)
        .bindPopup(popup);

      bounds.push([lat, lon]);
    });

    if (bounds.length > 0) {
      map.fitBounds(bounds, { padding: [20, 20] });
    }
  })
  .catch((error) => {
    console.error("Klarte ikke a laste tilfluktsrom-data:", error);
  });

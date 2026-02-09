console.log("Safemap landing page loaded");

// Default fallback location (UiA)
const DEFAULT_LOCATION = [58.1456, 8.0119];
const DEFAULT_ZOOM = 14;

// Initialize map - will be centered after geolocation
const map = L.map('map').setView(DEFAULT_LOCATION, DEFAULT_ZOOM);
let hasUserCentered = false;

// Variable to store user location circle
let userLocationCircle = null;

const updateUserLocation = (lat, lng, accuracy, shouldCenter = false) => {
  if (shouldCenter) {
    map.setView([lat, lng], Math.max(map.getZoom(), DEFAULT_ZOOM));
    hasUserCentered = true;
  }

  if (userLocationCircle) {
    map.removeLayer(userLocationCircle);
  }

  userLocationCircle = L.circleMarker([lat, lng], {
    radius: 8,
    fillColor: '#4285F4',
    color: '#ffffff',
    weight: 2,
    opacity: 1,
    fillOpacity: 0.8
  }).addTo(map).bindPopup('Din nåværende lokasjon');
};

// Try to get and watch user's current location
if (navigator.geolocation) {
  navigator.geolocation.watchPosition(
    (position) => {
      const lat = position.coords.latitude;
      const lng = position.coords.longitude;
      const accuracy = position.coords.accuracy;

      console.log(`Din lokasjon: ${lat}, ${lng} (nøyaktighet: ${accuracy}m)`);

      // Center map on first location
      updateUserLocation(lat, lng, accuracy, !userLocationCircle);
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

const layers = {
  hospitals: L.layerGroup(),
  legevakt: L.layerGroup(),
  brannstasjoner: L.featureGroup(),
  shelters: L.layerGroup()
};

const initLayerToggle = (checkboxId, layer) => {
  const checkbox = document.getElementById(checkboxId);
  if (!checkbox) return;
  const applyState = () => {
    applyLayerVisibility();
  };
  checkbox.addEventListener('change', applyState);
  applyState();
};

const isLayerChecked = (checkboxId) => {
  const checkbox = document.getElementById(checkboxId);
  return Boolean(checkbox && checkbox.checked);
};

const applyLayerVisibility = () => {
  const zoom = map.getZoom();
  const showIcons = zoom >= 8;

  const setLayer = (id, layer) => {
    const shouldShow = showIcons && isLayerChecked(id);
    if (shouldShow) {
      map.addLayer(layer);
    } else {
      map.removeLayer(layer);
    }
  };

  setLayer('layer-hospitals', layers.hospitals);
  setLayer('layer-legevakt', layers.legevakt);
  setLayer('layer-brannstasjoner', layers.brannstasjoner);
  setLayer('layer-tilfluktsrom', layers.shelters);
};

const setLoadingState = (isLoading) => {
  document.body.classList.toggle('is-loading', isLoading);
};

const logoButton = document.getElementById('safemap-logo');
if (logoButton) {
  logoButton.addEventListener('click', () => {
    window.location.reload();
  });
}

const clamp = (minValue, maxValue, value) => Math.max(minValue, Math.min(maxValue, value));

const getMarkerSize = (zoom) => clamp(18, 32, 18 + (zoom - 6) * 2);

const getShelterSize = (zoom) => clamp(12, 18, 12 + (zoom - 8) * 1.2);

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

const markers = layers.brannstasjoner;

const fireStationIcon = (size = 32) => L.divIcon({
  className: 'fire-station-marker',
  html: `
    <div style="
      width: ${size}px;
      height: ${size}px;
      border-radius: 50%;
      background: #f77f00;
      border: 3px solid #ffffff;
      box-shadow: 0 3px 6px rgba(0,0,0,0.35);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #ffffff;
      font-weight: 800;
      font-size: ${Math.max(12, Math.round(size * 0.55))}px;
      font-family: Arial, sans-serif;
    ">B</div>
  `,
  iconSize: [size, size],
  iconAnchor: [size / 2, size / 2],
  popupAnchor: [0, -size / 2]
});

const addStationToMap = (row) => {
  const coords = findLatLng(row);
  if (!coords || Number.isNaN(coords.lat) || Number.isNaN(coords.lng)) return;
  L.marker([coords.lat, coords.lng], { icon: fireStationIcon(getMarkerSize(map.getZoom())) })
    .addTo(markers)
    .bindPopup(labelForRow(row));
};

const updateMarkerSizes = () => {
  const zoom = map.getZoom();
  const size = getMarkerSize(zoom);
  const shelterSize = getShelterSize(zoom);

  applyLayerVisibility();

  layers.brannstasjoner.eachLayer((layer) => {
    if (layer.setIcon) {
      layer.setIcon(fireStationIcon(size));
    }
  });

  layers.hospitals.eachLayer((layer) => {
    if (layer.setIcon) {
      layer.setIcon(hospitalIcon(size));
    }
  });

  layers.legevakt.eachLayer((layer) => {
    if (layer.setIcon) {
      layer.setIcon(legevaktIcon(size));
    }
  });

  layers.shelters.eachLayer((layer) => {
    if (layer.setIcon) {
      layer.setIcon(shelterIcon(shelterSize));
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
      if (!hasUserCentered && markers.getLayers().length > 0) {
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

initLayerToggle('layer-hospitals', layers.hospitals);
initLayerToggle('layer-legevakt', layers.legevakt);
initLayerToggle('layer-brannstasjoner', layers.brannstasjoner);
initLayerToggle('layer-tilfluktsrom', layers.shelters);
applyLayerVisibility();

map.on('zoomend', updateMarkerSizes);

// Beholder standard zoomkontroller

// Custom icon for hospitals (red with S)
const hospitalIcon = (size = 32) => L.divIcon({
  className: 'hospital-marker',
  html: `<div style="background-color: #c0392b; width: ${size}px; height: ${size}px; border-radius: 50%; border: 3px solid white; box-shadow: 0 3px 6px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: ${Math.max(12, Math.round(size * 0.55))}px; font-family: Arial, sans-serif;">S</div>`,
  iconSize: [size, size],
  iconAnchor: [size / 2, size / 2]
});

// Custom icon for emergency clinics (legevakter)
const legevaktIcon = (size = 32) => L.divIcon({
  className: 'legevakt-marker',
  html: `<div style="background-color: #27ae60; width: ${size}px; height: ${size}px; border-radius: 50%; border: 3px solid white; box-shadow: 0 3px 6px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: ${Math.max(12, Math.round(size * 0.55))}px; font-family: Arial, sans-serif;">L</div>`,
  iconSize: [size, size],
  iconAnchor: [size / 2, size / 2]
});

const shelterIcon = (size = 18) => L.divIcon({
  className: "shelter-icon",
  html: `
    <div style="
      width: ${size}px;
      height: ${size}px;
      background: #facc15;
      border: 2px solid #000;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: ${Math.max(9, Math.round(size * 0.6))}px;
      color: #000;
    ">T</div>
  `,
  iconSize: [size, size],
  iconAnchor: [size / 2, size / 2],
  popupAnchor: [0, -size / 2],
});

// Load and display hospitals
async function loadHospitals() {
  const loadingIndicator = document.getElementById('loading');
  if (loadingIndicator) {
    setLoadingState(true);
  }
  
  try {
    const response = await fetch('/api/health-institutions');
    const data = await response.json();
    
    const hospitalCount = data.features.length;
    console.log(`Lastet ${hospitalCount} sykehus`);
    
    if (loadingIndicator) {
      loadingIndicator.textContent = `Laster legevakter...`;
    }
    
    const hospitalLayer = layers.hospitals;
    
    // Add each hospital to the map
    data.features.forEach(feature => {
      const coords = feature.geometry.coordinates;
      const props = feature.properties;
      
      // GeoJSON uses [lon, lat], Leaflet uses [lat, lon]
      const marker = L.marker([coords[1], coords[0]], {
        icon: hospitalIcon(getMarkerSize(map.getZoom())),
        zIndexOffset: 1000
      }).addTo(hospitalLayer);
      
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
      setTimeout(() => {
        loadingIndicator.style.display = 'none';
        setLoadingState(false);
      }, 3000);
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
    
    const legevaktLayer = layers.legevakt;
    
    // Add each legevakt to the map
    data.features.forEach(feature => {
      const coords = feature.geometry.coordinates;
      const props = feature.properties;
      
      // GeoJSON uses [lon, lat], Leaflet uses [lat, lon]
      const marker = L.marker([coords[1], coords[0]], {
        icon: legevaktIcon(getMarkerSize(map.getZoom())),
        zIndexOffset: 500
      }).addTo(legevaktLayer);
      
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
        setLoadingState(false);
      }, 2000);
    }
    
  } catch (error) {
    console.error('Feil ved lasting av legevakter:', error);
    if (loadingIndicator) {
      loadingIndicator.textContent = `${hospitalCount} sykehus (legevakter feilet)`;
      setTimeout(() => {
        loadingIndicator.style.display = 'none';
        setLoadingState(false);
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

      L.marker([lat, lon], { icon: shelterIcon(getShelterSize(map.getZoom())) })
        .addTo(layers.shelters)
        .bindPopup(popup);

      bounds.push([lat, lon]);
    });

    if (!hasUserCentered && bounds.length > 0) {
      map.fitBounds(bounds, { padding: [20, 20] });
    }
  })
  .catch((error) => {
    console.error("Klarte ikke a laste tilfluktsrom-data:", error);
  });

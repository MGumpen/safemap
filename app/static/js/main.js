console.log("Safemap landing page loaded");

// Default fallback location (UiA)
const DEFAULT_LOCATION = [58.1456, 8.0119];
const DEFAULT_ZOOM = 14;

// Initialize map - will be centered after geolocation
const map = L.map('map').setView(DEFAULT_LOCATION, DEFAULT_ZOOM);
let hasUserCentered = false;

// Variable to store user location circle
let userLocationCircle = null;
let currentUserPosition = null;

const updateUserLocation = (lat, lng, accuracy, shouldCenter = false) => {
  // Update current user position for distance filtering
  currentUserPosition = { lat, lon: lng };
  
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

const addressInput = document.getElementById('address-search');
const addressSuggestions = document.getElementById('address-suggestions');
const addressToInput = null;
const addressToSuggestions = null;
const routeButton = null;
const addressLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
let addressMarker = null;
let routeLine = null;
let activeSuggestionIndex = -1;
let activeSuggestions = [];
let addressSearchTimer = null;
let activeController = null;
let fromSelection = null;

const clearSuggestions = (target) => {
  if (!target) return;
  target.innerHTML = '';
  target.classList.remove('is-visible');
  activeSuggestions = [];
  activeSuggestionIndex = -1;
};

const formatAddressLabel = (item) => {
  const navn = item.adressenavn || item.adresse || item.vegadresse || '';
  const nummer = item.nummer || '';
  const bokstav = item.bokstav || '';
  const postnummer = item.postnummer || '';
  const poststed = item.poststed || '';
  const kommunenavn = item.kommunenavn || item.kommune || '';
  const hoved = `${navn} ${nummer}${bokstav}`.trim();
  const meta = `${postnummer} ${poststed}`.trim();
  const kommune = kommunenavn ? ` • ${kommunenavn}` : '';
  return {
    title: hoved || item.tekst || item.adresse || 'Adresse',
    meta: `${meta}${kommune}`.trim()
  };
};

const extractCoordinates = (item) => {
  const point = item.representasjonspunkt || item.punkt || item.position || null;
  if (point) {
    const lat = point.lat ?? point.latitude ?? point.y;
    const lon = point.lon ?? point.lng ?? point.longitude ?? point.x;
    if (lat != null && lon != null) {
      return { lat: Number(lat), lon: Number(lon) };
    }
  }
  if (item.lat != null && item.lon != null) {
    return { lat: Number(item.lat), lon: Number(item.lon) };
  }
  if (item.latitude != null && item.longitude != null) {
    return { lat: Number(item.latitude), lon: Number(item.longitude) };
  }
  return null;
};

const setActiveSuggestion = (index, target) => {
  if (!target) return;
  const items = Array.from(target.querySelectorAll('.address-suggestions__item'));
  items.forEach((item, idx) => {
    item.classList.toggle('is-active', idx === index);
  });
  activeSuggestionIndex = index;
};

const applyAddressSelection = (item, targetInput, targetSuggestions) => {
  const coords = extractCoordinates(item);
  if (!coords) return;
  const label = formatAddressLabel(item);
  if (targetInput) {
    targetInput.value = label.title;
  }
  clearSuggestions(targetSuggestions);
  if (addressMarker) addressLayer.removeLayer(addressMarker);
  addressMarker = L.marker([coords.lat, coords.lon]).addTo(addressLayer);
  fromSelection = { coords, label };
  const popupId = `route-popup-${Date.now()}`;
  addressMarker.bindPopup(`
    <div id="${popupId}">
      <strong>${label.title}</strong><br/>
      <span style="color:#6b7280;">${label.meta}</span>
      <div style="margin-top:8px; display:flex; flex-direction:column; gap:6px;">
        <button class="route-option" data-route="hospital">Rute til nærmeste sykehus</button>
        <button class="route-option" data-route="legevakt">Rute til nærmeste legevakt</button>
        <button class="route-option" data-route="shelter">Rute til nærmeste tilfluktsrom</button>
      </div>
    </div>
  `).openPopup();
  map.setView([coords.lat, coords.lon], Math.max(map.getZoom(), 14));
};

const renderSuggestions = (items, target, targetInput) => {
  if (!target) return;
  target.innerHTML = '';
  items.forEach((item, index) => {
    const label = formatAddressLabel(item);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'address-suggestions__item';
    button.innerHTML = `${label.title}<span class="address-suggestions__meta">${label.meta}</span>`;
    button.addEventListener('click', () => applyAddressSelection(item, targetInput, target));
    target.appendChild(button);
  });
  target.classList.toggle('is-visible', items.length > 0);
  activeSuggestions = items;
  activeSuggestionIndex = -1;
};

const fetchAddressSuggestions = async (query, target, targetInput) => {
  if (!query || query.length < 3) {
    clearSuggestions(target);
    return;
  }
  if (activeController) {
    activeController.abort();
  }
  activeController = new AbortController();
  try {
    const url = `https://ws.geonorge.no/adresser/v1/sok?sok=${encodeURIComponent(query)}&treffPerSide=6&fuzzy=true&utkoordsys=4258`;
    const response = await fetch(url, { signal: activeController.signal });
    if (!response.ok) throw new Error('Adresseoppslag feilet');
    const data = await response.json();
    const results = data.adresser || data.features || [];
    renderSuggestions(results, target, targetInput);
  } catch (error) {
    if (error.name !== 'AbortError') {
      clearSuggestions(target);
    }
  }
};

const wireAddressInput = (input, suggestions) => {
  if (!input) return;
  input.addEventListener('input', (event) => {
    const value = event.target.value.trim();
    clearTimeout(addressSearchTimer);
    addressSearchTimer = setTimeout(() => fetchAddressSuggestions(value, suggestions, input), 300);
  });

  input.addEventListener('keydown', (event) => {
    if (!activeSuggestions.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      const next = Math.min(activeSuggestionIndex + 1, activeSuggestions.length - 1);
      setActiveSuggestion(next, suggestions);
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      const prev = Math.max(activeSuggestionIndex - 1, 0);
      setActiveSuggestion(prev, suggestions);
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const item = activeSuggestions[activeSuggestionIndex];
      if (item) applyAddressSelection(item, input, suggestions);
    }
    if (event.key === 'Escape') {
      clearSuggestions(suggestions);
    }
  });
};

wireAddressInput(addressInput, addressSuggestions);

document.addEventListener('click', (event) => {
  const target = event.target;
  if (addressInput && (target === addressInput || addressSuggestions.contains(target))) return;
  clearSuggestions(addressSuggestions);
});

const fetchRoute = async (from, to) => {
  if (!from || !to) return;
  const url = `https://router.project-osrm.org/route/v1/driving/${from.lon},${from.lat};${to.lon},${to.lat}?overview=full&geometries=geojson`;
  const response = await fetch(url);
  if (!response.ok) throw new Error('Ruteoppslag feilet');
  const data = await response.json();
  const route = data.routes?.[0];
  if (!route) return;
  const coords = route.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
  if (routeLine) routeLayer.removeLayer(routeLine);
  routeLine = L.polyline(coords, { color: '#2563eb', weight: 5, opacity: 0.9 }).addTo(routeLayer);
  map.fitBounds(routeLine.getBounds().pad(0.2));
};

const routeToNearest = async (type) => {
  if (!fromSelection) return;
  const from = fromSelection.coords;
  try {
    const response = await fetch(`/api/nearest?type=${type}&lat=${from.lat}&lon=${from.lon}`);
    if (!response.ok) throw new Error('Nearest-oppslag feilet');
    const target = await response.json();
    if (!target || target.error) return;
    fetchRoute(from, { lat: target.lat, lon: target.lon });
  } catch (error) {
    console.error('Kunne ikke hente nærmeste punkt', error);
  }
};

const buildRoutePopup = (title, meta) => {
  const heading = title
    ? `<strong>${title}</strong><br/><span style="color:#6b7280;">${meta || ''}</span>`
    : '<strong>Valgt punkt</strong>';
  return `
    <div>
      ${heading}
      <div style="margin-top:8px; display:flex; flex-direction:column; gap:6px;">
        <button class="route-option" data-route="hospital">Rute til nærmeste sykehus</button>
        <button class="route-option" data-route="legevakt">Rute til nærmeste legevakt</button>
        <button class="route-option" data-route="shelter">Rute til nærmeste tilfluktsrom</button>
      </div>
    </div>
  `;
};

const reverseGeocode = async (lat, lon) => {
  try {
    const url = `https://ws.geonorge.no/adresser/v1/punktsok?lat=${lat}&lon=${lon}&radius=50&treffPerSide=1`;
    const response = await fetch(url);
    if (!response.ok) return null;
    const data = await response.json();
    return (data.adresser && data.adresser[0]) || null;
  } catch (error) {
    return null;
  }
};

map.on('click', async (event) => {
  const { lat, lng } = event.latlng;
  if (addressMarker) addressLayer.removeLayer(addressMarker);
  addressMarker = L.marker([lat, lng]).addTo(addressLayer);
  fromSelection = { coords: { lat, lon: lng }, label: { title: '', meta: '' } };

  const address = await reverseGeocode(lat, lng);
  if (address) {
    const label = formatAddressLabel(address);
    fromSelection.label = label;
    if (addressInput) addressInput.value = label.title;
    addressMarker.bindPopup(buildRoutePopup(label.title, label.meta)).openPopup();
  } else {
    addressMarker.bindPopup(buildRoutePopup('', '')).openPopup();
  }
});

const mapContainer = map.getContainer();
mapContainer.addEventListener('click', (event) => {
  const button = event.target.closest('.route-option');
  if (!button) return;
  event.preventDefault();
  event.stopPropagation();
  const type = button.getAttribute('data-route');
  if (type) routeToNearest(type);
});

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

// Load shelter data from database API
async function loadShelters() {
  try {
    console.log('Laster tilfluktsrom fra database...');
    const response = await fetch('/api/tilfluktsrom');
    
    if (!response.ok) {
      throw new Error(`API feilet: ${response.status}`);
    }
    
    const data = await response.json();
    
    if (data.error) {
      throw new Error(data.error);
    }
    
    const shelterCount = data.features?.length || 0;
    console.log(`Lastet ${shelterCount} tilfluktsrom fra database`);
    
    const bounds = [];
    
    data.features.forEach((feature) => {
      if (!feature.geometry || feature.geometry.type !== "Point") {
        return;
      }
      
      // GeoJSON format: [lon, lat]
      const [lon, lat] = feature.geometry.coordinates;
      const props = feature.properties || {};
      
      const popup = `
        <div style="min-width: 200px;">
          <h3 style="margin: 0 0 10px 0; font-size: 15px; font-weight: bold; color: #000;">
            Tilfluktsrom
          </h3>
          <p style="margin: 5px 0; font-size: 12px;"><strong>Adresse:</strong> ${props.adresse || "Ukjent"}</p>
          ${props.plasser ? `<p style="margin: 5px 0; font-size: 12px;"><strong>Plasser:</strong> ${props.plasser}</p>` : ''}
        </div>
      `;
      
      L.marker([lat, lon], { icon: shelterIcon(getShelterSize(map.getZoom())) })
        .addTo(layers.shelters)
        .bindPopup(popup);
      
      bounds.push([lat, lon]);
    });
    
    console.log(`Viser ${shelterCount} tilfluktsrom på kartet`);
    
    if (!hasUserCentered && bounds.length > 0) {
      map.fitBounds(bounds, { padding: [20, 20] });
    }
    
  } catch (error) {
    console.error('Feil ved lasting av tilfluktsrom:', error);
  }
}

// Load shelters from database
loadShelters();

// ===== SPATIAL FILTERING FUNCTIONALITY =====
let distanceFilterCircle = null;
let distanceFilterActive = false;

// Update distance value display
const distanceSlider = document.getElementById('distance-radius');
const distanceValue = document.getElementById('distance-value');
const applyFilterButton = document.getElementById('apply-distance-filter');
const clearFilterButton = document.getElementById('clear-distance-filter');
const filterResults = document.getElementById('distance-filter-results');

if (distanceSlider && distanceValue) {
  distanceSlider.addEventListener('input', (e) => {
    distanceValue.textContent = e.target.value;
  });
}

// Apply distance filter
if (applyFilterButton) {
  applyFilterButton.addEventListener('click', async () => {
    if (!currentUserPosition) {
      alert('Kunne ikke finne din posisjon. Vennligst aktiver stedstjenester.');
      return;
    }

    console.log('Starter avstandsfilter med posisjon:', currentUserPosition);
    const radius = parseFloat(distanceSlider.value);
    applyFilterButton.disabled = true;
    applyFilterButton.textContent = 'Søker...';

    try {
      const response = await fetch(
        `/api/spatial-filter?lat=${currentUserPosition.lat}&lon=${currentUserPosition.lon}&radius_km=${radius}`
      );
      
      if (!response.ok) throw new Error('Feil ved romlig søk');
      
      const data = await response.json();
      console.log('Mottok data:', data);
      
      // Show radius circle on map
      if (distanceFilterCircle) {
        map.removeLayer(distanceFilterCircle);
      }
      
      console.log('Tegner sirkel på posisjon:', [currentUserPosition.lat, currentUserPosition.lon], 'med radius:', radius * 1000, 'm');
      
      distanceFilterCircle = L.circle(
        [currentUserPosition.lat, currentUserPosition.lon],
        {
          radius: radius * 1000, // Convert km to meters
          color: '#ef4444',
          fillColor: '#ef4444',
          fillOpacity: 0.15,
          weight: 3,
          dashArray: '10, 10',
          opacity: 0.8
        }
      ).addTo(map);
      
      console.log('Sirkel lagt til kartet');

      // Zoom to circle bounds
      map.fitBounds(distanceFilterCircle.getBounds().pad(0.1));

      // Display results
      displayFilterResults(data);
      
      // Show clear button
      clearFilterButton.style.display = 'block';
      distanceFilterActive = true;
      
    } catch (error) {
      console.error('Feil ved avstandsfiltrering:', error);
      alert('Kunne ikke utføre søket. Vennligst prøv igjen.');
    } finally {
      applyFilterButton.disabled = false;
      applyFilterButton.textContent = 'Søk nær min posisjon';
    }
  });
}

// Clear distance filter
if (clearFilterButton) {
  clearFilterButton.addEventListener('click', () => {
    if (distanceFilterCircle) {
      map.removeLayer(distanceFilterCircle);
      distanceFilterCircle = null;
    }
    
    filterResults.classList.remove('visible');
    filterResults.innerHTML = '';
    clearFilterButton.style.display = 'none';
    distanceFilterActive = false;
    
    // Reset map view
    if (currentUserPosition) {
      map.setView([currentUserPosition.lat, currentUserPosition.lon], DEFAULT_ZOOM);
    }
  });
}

// Display filter results
function displayFilterResults(data) {
  if (!filterResults) return;
  
  const results = data.results;
  const total = data.total_count;
  
  let html = `<div style="font-weight: 700; margin-bottom: 8px;">
    Funnet ${total} objekt${total !== 1 ? 'er' : ''} innenfor ${data.radius_km} km
  </div>`;
  
  const categories = [
    { key: 'hospitals', label: 'Sykehus', icon: 'S', color: '#c0392b' },
    { key: 'legevakter', label: 'Legevakter', icon: 'L', color: '#27ae60' },
    { key: 'brannstasjoner', label: 'Brannstasjoner', icon: 'B', color: '#f77f00' },
    { key: 'shelters', label: 'Tilfluktsrom', icon: 'T', color: '#facc15' }
  ];
  
  categories.forEach(cat => {
    const items = results[cat.key] || [];
    if (items.length > 0) {
      html += `<div class="distance-filter__results-category" style="color: ${cat.color};">
        ${cat.icon} ${cat.label} (${items.length})
      </div>`;
      
      items.slice(0, 3).forEach(item => {
        html += `<div class="distance-filter__results-item">
          ${item.label} - <strong>${item.distance_km} km</strong>
        </div>`;
      });
      
      if (items.length > 3) {
        html += `<div style="font-size: 11px; color: #6b7280; margin: 4px 0;">
          ...og ${items.length - 3} til
        </div>`;
      }
    }
  });
  
  filterResults.innerHTML = html;
  filterResults.classList.add('visible');
}


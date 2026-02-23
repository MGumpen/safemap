console.log("Safemap landing page loaded");
/*
<changeLog>
  <change date="2026-02-23" author="Codex">
    <summary>Tilfluktsrom hentes nå fra backend-endepunktet /api/shelters (Geonorge API) i stedet for lokal fil.</summary>
    <details>
      <item>Fjernet direkte fetch mot /static/Tilfluktsrom.json.</item>
      <item>Beholder transformasjon fra EPSG:25833 til EPSG:4326 før plotting i kartet.</item>
    </details>
  </change>
  <change date="2026-02-23" author="Codex">
    <summary>Rettet branch-regresjon i visning av tilfluktsrom fra API.</summary>
    <details>
      <item>Transformerer igjen koordinater fra EPSG:25833 til EPSG:4326 før plotting.</item>
      <item>La til korrekt opptelling av shelters i logg.</item>
    </details>
  </change>
  <change date="2026-02-23" author="Codex">
    <summary>Gjorde shelter-rendering mer robust.</summary>
    <details>
      <item>Validerer at proj4 finnes før EPSG-transformasjon.</item>
      <item>Håndterer både EPSG:25833 og allerede-WGS84 koordinater.</item>
    </details>
  </change>
  <change date="2026-02-23" author="Codex">
    <summary>Reetablerte avstandsfilter (radius) etter branch-regresjon.</summary>
    <details>
      <item>Implementerte slider + apply/clear + resultatvisning.</item>
      <item>Filtrerer markører mot brukerposisjon med Haversine-avstand.</item>
      <item>Oppdaterer filter ved nye data og ved oppdatert brukerposisjon.</item>
    </details>
  </change>
  <change date="2026-02-23" author="Codex">
    <summary>Gjorde radius-filteret synlig og brukbart uten geolokasjon.</summary>
    <details>
      <item>Viser alltid resultattekst ved aktivt filter.</item>
      <item>Faller tilbake til kartets sentrum når brukerposisjon mangler.</item>
    </details>
  </change>
  <change date="2026-02-23" author="Codex">
    <summary>Rettet radius-resultatliste slik at den viser faktiske treff innenfor radius.</summary>
    <details>
      <item>Legger label-metadata på markører ved lasting av alle datalag.</item>
      <item>Bygger resultatliste per kategori med sortering på avstand.</item>
      <item>Gjeninnførte detaljert visning i distance-filter-results i stedet for kun tellelinje.</item>
    </details>
  </change>
  <change date="2026-02-23" author="Codex">
    <summary>La til scroll og lukkeknapp i radius-resultatlisten.</summary>
    <details>
      <item>Resultatlisten rendres nå med header + lukkeknapp øverst til høyre.</item>
      <item>Trefflisten ligger i egen scroll-bar container for lange resultater.</item>
      <item>Skjuling av listen påvirker ikke aktivt radiusfilter på kartet.</item>
    </details>
  </change>
</changeLog>
*/

// Default fallback location (UiA)
const DEFAULT_LOCATION = [58.1456, 8.0119];
const DEFAULT_ZOOM = 14;

// Initialize map - will be centered after geolocation
const map = L.map('map').setView(DEFAULT_LOCATION, DEFAULT_ZOOM);
let hasUserCentered = false;

// Variable to store user location circle
let userLocationCircle = null;
let currentUserPosition = null;
let distanceFilterCircle = null;
let distanceFilterActive = false;
let distanceFilterRadiusKm = 5;
let distanceFilterResultsHidden = false;

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

  if (distanceFilterActive) {
    applyDistanceFilter(distanceFilterRadiusKm);
  }
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
const distanceRadiusInput = document.getElementById('distance-radius');
const distanceValueLabel = document.getElementById('distance-value');
const applyDistanceFilterButton = document.getElementById('apply-distance-filter');
const clearDistanceFilterButton = document.getElementById('clear-distance-filter');
const distanceFilterResults = document.getElementById('distance-filter-results');

const formatRouteDistance = (distanceMeters) => {
  const km = Number(distanceMeters) / 1000;
  if (!Number.isFinite(km)) return '';
  if (km >= 100) return `${km.toFixed(0)} km`;
  if (km >= 10) return `${km.toFixed(1)} km`;
  return `${km.toFixed(2)} km`;
};

const toRadians = (value) => (value * Math.PI) / 180;

const haversineKm = (from, to) => {
  const earthRadiusKm = 6371;
  const dLat = toRadians(to.lat - from.lat);
  const dLon = toRadians(to.lon - from.lon);
  const fromLat = toRadians(from.lat);
  const toLat = toRadians(to.lat);
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(fromLat) * Math.cos(toLat) * Math.sin(dLon / 2) ** 2;
  return 2 * earthRadiusKm * Math.asin(Math.sqrt(a));
};

const setMarkerVisibility = (marker, visible) => {
  if (!marker || typeof marker.setOpacity !== 'function') return;
  marker.setOpacity(visible ? 1 : 0);
  const element = marker.getElement ? marker.getElement() : null;
  if (element) {
    element.style.pointerEvents = visible ? 'auto' : 'none';
  }
  if (!visible && marker.closePopup) {
    marker.closePopup();
  }
};

const setMarkerFilterLabel = (marker, label) => {
  if (!marker) return;
  const normalized = String(label || '').trim();
  marker._safeMapFilterLabel = normalized || 'Ukjent';
};

const getMarkerFilterLabel = (marker, fallback) => {
  const markerLabel = marker?._safeMapFilterLabel;
  if (typeof markerLabel === 'string' && markerLabel.trim()) return markerLabel.trim();
  const popupContent = marker?.getPopup?.()?.getContent?.();
  if (typeof popupContent === 'string' && popupContent.trim() && !popupContent.includes('<')) {
    return popupContent.trim();
  }
  return fallback;
};

const escapeHtml = (text) => String(text ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;');

const distanceResultCategories = [
  { key: 'hospitals', label: 'Sykehus', icon: 'S', color: '#c0392b' },
  { key: 'legevakt', label: 'Legevakter', icon: 'L', color: '#27ae60' },
  { key: 'brannstasjoner', label: 'Brannstasjoner', icon: 'B', color: '#f77f00' },
  { key: 'shelters', label: 'Tilfluktsrom', icon: 'T', color: '#d97706' }
];

const formatDistanceKm = (distanceKm) => {
  if (!Number.isFinite(distanceKm)) return '';
  if (distanceKm >= 10) return distanceKm.toFixed(1);
  return distanceKm.toFixed(2);
};

const setDistanceFilterResultsVisibility = (visible) => {
  if (!distanceFilterResults) return;
  distanceFilterResults.classList.toggle('visible', visible);
};

const updateDistanceFilterResults = (matchesByCategory, radiusKm, usedMapCenterFallback) => {
  if (!distanceFilterResults) return;
  const total = distanceResultCategories.reduce(
    (sum, category) => sum + (matchesByCategory[category.key]?.length || 0),
    0
  );
  const suffix = usedMapCenterFallback ? ' (basert på kartets sentrum)' : '';
  const summary = `Funnet ${total} objekt${total !== 1 ? 'er' : ''} innenfor ${radiusKm} km${suffix}`;
  let bodyHtml = '';

  if (total === 0) {
    bodyHtml = '<div class="distance-filter__results-item">Ingen treff i valgt radius.</div>';
  } else {
    distanceResultCategories.forEach((category) => {
      const items = matchesByCategory[category.key] || [];
      if (!items.length) return;

      bodyHtml += `<div class="distance-filter__results-category" style="color: ${category.color};">${category.icon} ${category.label} (${items.length})</div>`;

      items.forEach((item) => {
        bodyHtml += `<div class="distance-filter__results-item">${escapeHtml(item.label)} - <strong>${formatDistanceKm(item.distanceKm)} km</strong></div>`;
      });
    });
  }

  distanceFilterResults.innerHTML = `
    <div class="distance-filter__results-header">
      <div class="distance-filter__results-title">${escapeHtml(summary)}</div>
      <button
        type="button"
        class="distance-filter__results-close"
        aria-label="Skjul resultatlisten"
        title="Skjul listen"
      >
        ×
      </button>
    </div>
    <div class="distance-filter__results-body">
      ${bodyHtml}
    </div>
  `;
  setDistanceFilterResultsVisibility(!distanceFilterResultsHidden);
};

const applyDistanceFilter = (radiusKm, options = {}) => {
  const { revealResults = false } = options;
  distanceFilterRadiusKm = radiusKm;
  if (revealResults) {
    distanceFilterResultsHidden = false;
  }
  const filterOrigin = currentUserPosition || { lat: map.getCenter().lat, lon: map.getCenter().lng };

  const matchesByCategory = { hospitals: [], legevakt: [], brannstasjoner: [], shelters: [] };
  const groups = [
    { key: 'hospitals', group: layers.hospitals, fallbackLabel: 'Sykehus' },
    { key: 'legevakt', group: layers.legevakt, fallbackLabel: 'Legevakt' },
    { key: 'brannstasjoner', group: layers.brannstasjoner, fallbackLabel: 'Brannstasjon' },
    { key: 'shelters', group: layers.shelters, fallbackLabel: 'Tilfluktsrom' }
  ];

  groups.forEach(({ key, group, fallbackLabel }) => {
    group.eachLayer((layer) => {
      if (!layer.getLatLng) return;
      const latLng = layer.getLatLng();
      const distanceKm = haversineKm(filterOrigin, { lat: latLng.lat, lon: latLng.lng });
      const visible = distanceKm <= radiusKm;
      setMarkerVisibility(layer, visible);
      if (!visible) return;

      matchesByCategory[key].push({
        label: getMarkerFilterLabel(layer, fallbackLabel),
        distanceKm
      });
    });
  });

  Object.values(matchesByCategory).forEach((items) => {
    items.sort((a, b) => a.distanceKm - b.distanceKm);
  });

  if (distanceFilterCircle) {
    map.removeLayer(distanceFilterCircle);
  }
  distanceFilterCircle = L.circle([filterOrigin.lat, filterOrigin.lon], {
    radius: radiusKm * 1000,
    color: '#2563eb',
    weight: 2,
    fillColor: '#60a5fa',
    fillOpacity: 0.08
  }).addTo(map);

  distanceFilterActive = true;
  if (clearDistanceFilterButton) clearDistanceFilterButton.style.display = 'inline-flex';
  updateDistanceFilterResults(matchesByCategory, radiusKm, !currentUserPosition);
};

const clearDistanceFilter = () => {
  [layers.hospitals, layers.legevakt, layers.brannstasjoner, layers.shelters].forEach((group) => {
    group.eachLayer((layer) => {
      setMarkerVisibility(layer, true);
    });
  });
  if (distanceFilterCircle) {
    map.removeLayer(distanceFilterCircle);
    distanceFilterCircle = null;
  }
  distanceFilterActive = false;
  distanceFilterResultsHidden = false;
  if (distanceFilterResults) {
    distanceFilterResults.innerHTML = '';
    setDistanceFilterResultsVisibility(false);
  }
  if (clearDistanceFilterButton) clearDistanceFilterButton.style.display = 'none';
};

const refreshDistanceFilterIfActive = () => {
  if (distanceFilterActive) {
    applyDistanceFilter(distanceFilterRadiusKm);
  }
};

const initializeDistanceFilterControls = () => {
  if (distanceRadiusInput) {
    const initialValue = Number(distanceRadiusInput.value || 5);
    if (Number.isFinite(initialValue)) {
      distanceFilterRadiusKm = initialValue;
      if (distanceValueLabel) distanceValueLabel.textContent = String(initialValue);
    }
    distanceRadiusInput.addEventListener('input', (event) => {
      const value = Number(event.target.value);
      if (!Number.isFinite(value)) return;
      distanceFilterRadiusKm = value;
      if (distanceValueLabel) distanceValueLabel.textContent = String(value);
      if (distanceFilterActive) {
        applyDistanceFilter(value, { revealResults: true });
      }
    });
  }

  if (applyDistanceFilterButton) {
    applyDistanceFilterButton.addEventListener('click', () => {
      applyDistanceFilter(distanceFilterRadiusKm, { revealResults: true });
    });
  }

  if (clearDistanceFilterButton) {
    clearDistanceFilterButton.addEventListener('click', () => {
      clearDistanceFilter();
    });
  }

  if (distanceFilterResults) {
    distanceFilterResults.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const closeButton = target.closest('.distance-filter__results-close');
      if (!closeButton) return;
      event.preventDefault();
      distanceFilterResultsHidden = true;
      setDistanceFilterResultsVisibility(false);
    });
  }
};

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
  const distanceLabel = formatRouteDistance(route.distance);
  if (distanceLabel) {
    routeLine.bindTooltip(distanceLabel, {
      permanent: true,
      direction: 'center',
      className: 'route-distance-tooltip',
      opacity: 1
    }).openTooltip();
  }
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
  const stationLabel = labelForRow(row);
  const marker = L.marker([coords.lat, coords.lng], { icon: fireStationIcon(getMarkerSize(map.getZoom())) })
    .addTo(markers)
    .bindPopup(stationLabel);
  setMarkerFilterLabel(marker, stationLabel);
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
      refreshDistanceFilterIfActive();
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
initializeDistanceFilterControls();

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
      const hospitalLabel = props.navn || props.name || 'Sykehus';
      
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
          <p style="margin: 5px 0; font-size: 12px;"><strong>Kommune:</strong> ${props.kommune}</p>
        </div>
      `;
      
      marker.bindPopup(popupContent);
      setMarkerFilterLabel(marker, hospitalLabel);
    });
    refreshDistanceFilterIfActive();
    
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
      const legevaktLabel = props.navn || props.adresse || 'Legevakt';
      
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
      setMarkerFilterLabel(marker, legevaktLabel);
    });
    refreshDistanceFilterIfActive();
    
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
const hasProj4 = typeof proj4 !== 'undefined';
if (hasProj4) {
  proj4.defs("EPSG:25833", "+proj=utm +zone=33 +ellps=GRS80 +units=m +no_defs");
}

const toLeafletLatLon = (coordinates) => {
  if (!Array.isArray(coordinates) || coordinates.length < 2) return null;
  const x = Number(coordinates[0]);
  const y = Number(coordinates[1]);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;

  // Already WGS84 [lon, lat]
  if (Math.abs(x) <= 180 && Math.abs(y) <= 90) {
    return { lat: y, lon: x };
  }

  // Projected coordinates (expected EPSG:25833)
  if (hasProj4) {
    const [lon, lat] = proj4("EPSG:25833", "EPSG:4326", [x, y]);
    return { lat, lon };
  }

  return null;
};

const loadShelters = async () => {
  try {
    const response = await fetch('/api/shelters');
    if (!response.ok) throw new Error(`API-feil: ${response.status}`);
    const geojson = await response.json();
    if (!geojson || !Array.isArray(geojson.features)) {
      throw new Error('Ugyldig GeoJSON fra /api/shelters');
    }

    let shelterCount = 0;
    const bounds = [];
    geojson.features.forEach((feature) => {
      if (!feature.geometry || feature.geometry.type !== "Point") {
        return;
      }
      
      const converted = toLeafletLatLon(feature.geometry.coordinates);
      if (!converted) {
        console.warn('Ugyldige eller ikke-konverterbare shelter-koordinater', feature.geometry.coordinates);
        return;
      }
      const { lat, lon } = converted;
      const props = feature.properties || {};
      const shelterLabel = props.adresse || props.navn || 'Tilfluktsrom';
      
      const popup = `
        <div style="min-width: 200px;">
          <h3 style="margin: 0 0 10px 0; font-size: 15px; font-weight: bold; color: #000;">
            Tilfluktsrom
          </h3>
          <p style="margin: 5px 0; font-size: 12px;"><strong>Adresse:</strong> ${props.adresse || "Ukjent"}</p>
          ${props.plasser ? `<p style="margin: 5px 0; font-size: 12px;"><strong>Plasser:</strong> ${props.plasser}</p>` : ''}
        </div>
      `;
      
      const marker = L.marker([lat, lon], { icon: shelterIcon(getShelterSize(map.getZoom())) })
        .addTo(layers.shelters)
        .bindPopup(popup);
      setMarkerFilterLabel(marker, shelterLabel);

      shelterCount += 1;
      bounds.push([lat, lon]);
    });
    refreshDistanceFilterIfActive();
    
    console.log(`Viser ${shelterCount} tilfluktsrom på kartet`);
    
    if (!hasUserCentered && bounds.length > 0) {
      map.fitBounds(bounds, { padding: [20, 20] });
    }
  } catch (error) {
    console.error("Klarte ikke å laste tilfluktsrom-data fra API:", error);
  }
};

loadShelters();

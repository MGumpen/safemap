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
let locateControlButton = null;

const showMapStatusPopup = (message, latLng = map.getCenter()) => {
  const popupContent = document.createElement('div');
  popupContent.className = 'map-status-popup__content';
  popupContent.textContent = message;

  L.popup({
    className: 'map-status-popup',
    closeButton: false,
    autoClose: true,
    closeOnClick: true,
    offset: [0, -14]
  })
    .setLatLng(latLng)
    .setContent(popupContent)
    .openOn(map);
};

const setLocateControlLoading = (isLoading) => {
  if (!locateControlButton) return;
  locateControlButton.disabled = isLoading;
  locateControlButton.classList.toggle('is-loading', isLoading);
  locateControlButton.setAttribute('aria-busy', isLoading ? 'true' : 'false');
};

const centerOnUserLocation = (lat, lng) => {
  const targetZoom = Math.max(map.getZoom(), DEFAULT_ZOOM);
  map.flyTo([lat, lng], targetZoom, {
    animate: true,
    duration: 0.8
  });

  window.setTimeout(() => {
    if (userLocationCircle) {
      userLocationCircle.openPopup();
    }
  }, 250);
};

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

map.createPane('analysisZonesPane');
const analysisZonesPane = map.getPane('analysisZonesPane');
if (analysisZonesPane) {
  analysisZonesPane.style.zIndex = '350';
}

const focusOnUserLocation = () => {
  const fallbackPosition = currentUserPosition
    ? { lat: currentUserPosition.lat, lon: currentUserPosition.lon }
    : null;

  if (fallbackPosition) {
    centerOnUserLocation(fallbackPosition.lat, fallbackPosition.lon);
  }

  if (!navigator.geolocation) {
    if (!fallbackPosition) {
      showMapStatusPopup('Nettleseren støtter ikke geolokasjon.');
    }
    return;
  }

  setLocateControlLoading(true);
  navigator.geolocation.getCurrentPosition(
    (position) => {
      const lat = position.coords.latitude;
      const lng = position.coords.longitude;
      const accuracy = position.coords.accuracy;

      updateUserLocation(lat, lng, accuracy, false);
      centerOnUserLocation(lat, lng);
      setLocateControlLoading(false);
    },
    (error) => {
      setLocateControlLoading(false);
      if (!fallbackPosition) {
        showMapStatusPopup(`Kunne ikke hente posisjon: ${error.message}`);
        return;
      }
      showMapStatusPopup('Viser sist kjente posisjon. Kunne ikke hente ny posisjon.', [fallbackPosition.lat, fallbackPosition.lon]);
    },
    {
      enableHighAccuracy: true,
      timeout: 8000,
      maximumAge: 10000
    }
  );
};

const createLocateControl = () => {
  const LocateControl = L.Control.extend({
    options: {
      position: 'topleft'
    },
    onAdd() {
      const container = L.DomUtil.create('div', 'leaflet-bar leaflet-control leaflet-control-locate');
      const button = L.DomUtil.create('button', 'leaflet-control-locate__button', container);
      locateControlButton = button;

      button.type = 'button';
      button.title = 'Finn min posisjon';
      button.setAttribute('aria-label', 'Finn min posisjon');
      button.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="4.25"></circle>
          <path d="M12 2.75v3.5M12 17.75v3.5M2.75 12h3.5M17.75 12h3.5"></path>
        </svg>
      `;

      L.DomEvent.disableClickPropagation(container);
      L.DomEvent.on(button, 'click', (event) => {
        L.DomEvent.stop(event);
        focusOnUserLocation();
      });

      return container;
    }
  });

  const locateControl = new LocateControl();
  locateControl.addTo(map);

  const topLeftControls = map.getContainer().querySelector('.leaflet-top.leaflet-left');
  const locateContainer = locateControl.getContainer();
  const zoomContainer = topLeftControls?.querySelector('.leaflet-control-zoom');

  if (topLeftControls && locateContainer && zoomContainer) {
    topLeftControls.insertBefore(locateContainer, zoomContainer);
  }
};

createLocateControl();

function getAnalysisZoneColor(score) {
  const numericScore = Number(score);
  if (!Number.isFinite(numericScore)) return '#94a3b8';
  const clampedScore = Math.max(0, Math.min(100, numericScore));

  const interpolateChannel = (start, end, ratio) => Math.round(start + ((end - start) * ratio));
  const hexToRgb = (hex) => ({
    r: Number.parseInt(hex.slice(1, 3), 16),
    g: Number.parseInt(hex.slice(3, 5), 16),
    b: Number.parseInt(hex.slice(5, 7), 16)
  });
  const rgbToHex = ({ r, g, b }) => `#${[r, g, b].map((value) => value.toString(16).padStart(2, '0')).join('')}`;

  const red = hexToRgb('#ef4444');
  const orange = hexToRgb('#f59e0b');
  const green = hexToRgb('#22c55e');

  if (clampedScore <= 50) {
    const ratio = clampedScore / 50;
    return rgbToHex({
      r: interpolateChannel(red.r, orange.r, ratio),
      g: interpolateChannel(red.g, orange.g, ratio),
      b: interpolateChannel(red.b, orange.b, ratio)
    });
  }

  const ratio = (clampedScore - 50) / 50;
  return rgbToHex({
    r: interpolateChannel(orange.r, green.r, ratio),
    g: interpolateChannel(orange.g, green.g, ratio),
    b: interpolateChannel(orange.b, green.b, ratio)
  });
}

function getAnalysisZoneLevelLabel(score) {
  const numericScore = Number(score);
  if (!Number.isFinite(numericScore)) return 'Ukjent';
  if (numericScore >= 75) return 'Høy';
  if (numericScore >= 50) return 'Middels';
  return 'Lav';
}

function getAnalysisZoneCellSize(zoom) {
  if (zoom >= 13) return 1200;
  if (zoom >= 11) return 2500;
  if (zoom >= 9) return 5000;
  if (zoom >= 7) return 10000;
  return 20000;
}

function createAnalysisZoneTooltip(properties = {}) {
  const score = Number(properties.score ?? 0);
  const maxScore = Number(properties.max_score ?? 100);
  const label = getAnalysisZoneLevelLabel(score);
  return `Beredskapsscore: ${score} / ${maxScore} (${label})`;
}

const layers = {
  hospitals: L.layerGroup(),
  legevakt: L.layerGroup(),
  brannstasjoner: L.featureGroup(),
  shelters: L.layerGroup(),
  analysisZones: L.geoJSON(null, {
    pane: 'analysisZonesPane',
    style: (feature) => {
      const properties = feature?.properties || {};
      const color = getAnalysisZoneColor(properties.score);
      return {
        color,
        weight: 1,
        opacity: 0.4,
        fillColor: color,
        fillOpacity: 0.22
      };
    },
    onEachFeature: (feature, layer) => {
      const properties = feature?.properties || {};
      const tooltip = createAnalysisZoneTooltip(properties);
      layer.bindTooltip(tooltip, { sticky: true, opacity: 0.95 });
      layer.bindPopup(`
        <div style="min-width: 180px;">
          <strong>Beredskapssone</strong><br/>
          <span style="color:#6b7280;">${escapeHtml(getAnalysisZoneLevelLabel(properties.score))}</span>
          <div style="margin-top:8px;"><strong>${Number(properties.score || 0)} / ${Number(properties.max_score || 100)} poeng</strong></div>
        </div>
      `);
    }
  })
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

  const setLayer = (id, layer, options = {}) => {
    const { requiresIconZoom = true } = options;
    const shouldShow = (requiresIconZoom ? showIcons : true) && isLayerChecked(id);
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
  setLayer('layer-analysis-zones', layers.analysisZones, { requiresIconZoom: false });
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
const routeModeSelect = document.getElementById('route-mode');
const addressToInput = null;
const addressToSuggestions = null;
const routeButton = null;
const addressLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
let addressMarker = null;
let routeLine = null;
let routeRequestToken = 0;
let activeSuggestionIndex = -1;
let activeSuggestions = [];
let addressSearchTimer = null;
let activeController = null;
let fromSelection = null;
let activeRoute = null;
const distanceRadiusInput = document.getElementById('distance-radius');
const distanceValueLabel = document.getElementById('distance-value');
const applyDistanceFilterButton = document.getElementById('apply-distance-filter');
const clearDistanceFilterButton = document.getElementById('clear-distance-filter');
const distanceFilterResults = document.getElementById('distance-filter-results');
const locationAnalysisContainer = document.getElementById('location-analysis');
const analysisZoneLegend = document.getElementById('analysis-zone-legend');
const analysisLayer = L.layerGroup().addTo(map);
let analysisRequestToken = 0;
let activeSelectionToken = 0;
let analysisZonesRequestToken = 0;
let analysisZonesRefreshTimer = null;
const analysisState = {
  loading: false,
  error: '',
  data: null,
  label: null
};

const analysisCategoryStyles = {
  hospital: { color: '#c0392b', short: 'S' },
  legevakt: { color: '#27ae60', short: 'L' },
  fire_station: { color: '#f77f00', short: 'B' },
  shelter: { color: '#d97706', short: 'T' }
};

const ROUTE_MODE_STORAGE_KEY = 'safemap:route-mode';
const routeModes = {
  driving: {
    label: 'Bilvei',
    osrmProfile: 'driving',
    lineColor: '#2563eb',
    dashArray: null
  },
  walking: {
    label: 'Gangvei',
    osrmProfile: 'walking',
    lineColor: '#16a34a',
    dashArray: '10 6'
  },
  air: {
    label: 'Luftlinje',
    osrmProfile: null,
    lineColor: '#7c3aed',
    dashArray: '8 8'
  }
};
let currentRouteMode = 'driving';

const formatRouteDistance = (distanceMeters) => {
  const km = Number(distanceMeters) / 1000;
  if (!Number.isFinite(km)) return '';
  if (km >= 100) return `${km.toFixed(0)} km`;
  if (km >= 10) return `${km.toFixed(1)} km`;
  return `${km.toFixed(2)} km`;
};

const formatRouteDuration = (durationSeconds) => {
  const seconds = Number(durationSeconds);
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (!remainingMinutes) return `${hours} t`;
  return `${hours} t ${remainingMinutes} min`;
};

const getRouteModeConfig = (mode = currentRouteMode) => routeModes[mode] || routeModes.driving;

const getRouteModeLabel = (mode = currentRouteMode) => getRouteModeConfig(mode).label;

const readStoredRouteMode = () => {
  try {
    const stored = window.localStorage.getItem(ROUTE_MODE_STORAGE_KEY);
    if (stored && routeModes[stored]) return stored;
  } catch (error) {
    // Ignore storage failures and fall back to the default profile.
  }
  return 'driving';
};

const persistRouteMode = (mode) => {
  try {
    window.localStorage.setItem(ROUTE_MODE_STORAGE_KEY, mode);
  } catch (error) {
    // Ignore storage failures and keep the mode only in memory.
  }
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

const clearRouteLine = () => {
  if (!routeLine) return;
  routeLayer.removeLayer(routeLine);
  routeLine = null;
};

const clearActiveRoute = () => {
  routeRequestToken += 1;
  activeRoute = null;
  clearRouteLine();
};

const bindRouteTooltip = (line, summary) => {
  if (!line || !summary) return;
  line.bindTooltip(summary, {
    permanent: true,
    direction: 'center',
    className: 'route-distance-tooltip',
    opacity: 1
  }).openTooltip();
};

const drawRouteLine = (latLngs, summary, mode = currentRouteMode) => {
  const config = getRouteModeConfig(mode);
  clearRouteLine();
  routeLine = L.polyline(latLngs, {
    color: config.lineColor,
    weight: mode === 'air' ? 4 : 5,
    opacity: 0.9,
    dashArray: config.dashArray || null
  }).addTo(routeLayer);
  bindRouteTooltip(routeLine, summary);
  map.fitBounds(routeLine.getBounds().pad(0.2));
};

const buildRouteSummary = (mode, distanceMeters, durationSeconds = null) => {
  const distanceLabel = formatRouteDistance(distanceMeters);
  if (!distanceLabel) return '';
  const durationLabel = formatRouteDuration(durationSeconds);
  if (durationLabel && mode !== 'air') {
    return `${getRouteModeLabel(mode)}: ${distanceLabel} • ${durationLabel}`;
  }
  return `${getRouteModeLabel(mode)}: ${distanceLabel}`;
};

const drawAirRoute = (from, to) => {
  const distanceMeters = haversineKm(from, to) * 1000;
  drawRouteLine(
    [
      [from.lat, from.lon],
      [to.lat, to.lon]
    ],
    buildRouteSummary('air', distanceMeters),
    'air'
  );
};

const fetchOsrmRoute = async (from, to, profile) => {
  const url = `https://router.project-osrm.org/route/v1/${profile}/${from.lon},${from.lat};${to.lon},${to.lat}?overview=full&geometries=geojson`;
  const response = await fetch(url);
  if (!response.ok) throw new Error('Ruteoppslag feilet');
  const data = await response.json();
  return data.routes?.[0] || null;
};

const renderRoute = async (from, to) => {
  if (!from || !to) return;

  activeRoute = { from: { ...from }, to: { ...to } };
  const requestToken = ++routeRequestToken;
  const mode = currentRouteMode;
  const config = getRouteModeConfig(mode);

  if (mode === 'air' || !config.osrmProfile) {
    drawAirRoute(from, to);
    return;
  }

  try {
    const route = await fetchOsrmRoute(from, to, config.osrmProfile);
    if (requestToken !== routeRequestToken || mode !== currentRouteMode) return;
    if (!route) {
      showMapStatusPopup(`Fant ingen ${getRouteModeLabel(mode).toLowerCase()} mellom punktene.`);
      return;
    }
    const coords = route.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
    drawRouteLine(coords, buildRouteSummary(mode, route.distance, route.duration), mode);
  } catch (error) {
    if (requestToken !== routeRequestToken) return;
    clearRouteLine();
    showMapStatusPopup(`Kunne ikke vise ${getRouteModeLabel(mode).toLowerCase()}.`);
    throw error;
  }
};

const setRouteMode = (mode) => {
  if (!routeModes[mode]) return;
  currentRouteMode = mode;
  if (routeModeSelect && routeModeSelect.value !== mode) {
    routeModeSelect.value = mode;
  }
  persistRouteMode(mode);
  if (activeRoute) {
    renderRoute(activeRoute.from, activeRoute.to).catch((error) => {
      console.error('Kunne ikke oppdatere rute for valgt modus', error);
    });
  }
};

currentRouteMode = readStoredRouteMode();
if (routeModeSelect) {
  routeModeSelect.value = currentRouteMode;
  routeModeSelect.addEventListener('change', (event) => {
    setRouteMode(event.target.value);
  });
}

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

const formatAnalysisDistance = (distanceMeters) => {
  const meters = Number(distanceMeters);
  if (!Number.isFinite(meters)) return '';
  if (meters < 1000) return `${Math.round(meters)} m`;
  const km = meters / 1000;
  if (km >= 10) return `${km.toFixed(1)} km`;
  return `${km.toFixed(2)} km`;
};

const formatAnalysisCoordinates = (point) => {
  if (!point) return '';
  const lat = Number(point.lat);
  const lon = Number(point.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return '';
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
};

const describeAnalysisScore = (score) => {
  if (score >= 80) return 'Svært god nærhet til beredskapsressurser.';
  if (score >= 60) return 'God nærhet til beredskapsressurser.';
  if (score >= 40) return 'Moderat nærhet til beredskapsressurser.';
  return 'Svak nærhet til beredskapsressurser.';
};

const buildAnalysisStatusText = (item) => {
  const distanceMeters = Number(item?.distance_meters);
  const idealDistance = Number(item?.ideal_distance_m);
  const maxDistance = Number(item?.max_distance_m);

  if (!Number.isFinite(distanceMeters) || !Number.isFinite(maxDistance)) {
    return '';
  }
  if (Number.isFinite(idealDistance) && distanceMeters <= idealDistance) {
    return `Full score ved ${formatAnalysisDistance(idealDistance)} eller nærmere.`;
  }
  if (distanceMeters <= maxDistance) {
    return `Innenfor akseptabel avstand. Poengene faller gradvis frem til ${formatAnalysisDistance(maxDistance)}.`;
  }
  return `Utenfor anbefalt avstand på ${formatAnalysisDistance(maxDistance)}.`;
};

const clearAnalysisHighlights = () => {
  analysisLayer.clearLayers();
};

const renderAnalysisHighlights = (data) => {
  clearAnalysisHighlights();
  const clickedPoint = data?.clicked_point;
  const breakdown = Array.isArray(data?.breakdown) ? data.breakdown : [];
  if (!clickedPoint || !breakdown.length) return;

  const clickedLat = Number(clickedPoint.lat);
  const clickedLon = Number(clickedPoint.lon);
  if (!Number.isFinite(clickedLat) || !Number.isFinite(clickedLon)) return;

  L.circle([clickedLat, clickedLon], {
    radius: 150,
    color: '#0f172a',
    weight: 2,
    opacity: 0.8,
    fillOpacity: 0
  }).addTo(analysisLayer);

  breakdown.forEach((item) => {
    const lat = Number(item?.lat);
    const lon = Number(item?.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

    const style = analysisCategoryStyles[item.key] || { color: '#2563eb', short: '?' };

    L.polyline([[clickedLat, clickedLon], [lat, lon]], {
      color: style.color,
      weight: 2,
      opacity: 0.8,
      dashArray: '7 6'
    }).addTo(analysisLayer);

    const marker = L.circleMarker([lat, lon], {
      radius: 10,
      color: style.color,
      weight: 3,
      fillColor: '#ffffff',
      fillOpacity: 0.96
    }).addTo(analysisLayer);

    marker.bindTooltip(`${item.label}: ${formatAnalysisDistance(item.distance_meters)}`, {
      direction: 'top',
      opacity: 0.95
    });
    marker.bindPopup(`
      <div style="min-width: 190px;">
        <strong>${escapeHtml(item.name || item.label || 'Treff')}</strong><br/>
        <span style="color:#6b7280;">${escapeHtml(item.description || '')}</span>
        <div style="margin-top:8px;">
          <strong>${Number(item.score || 0)} / ${Number(item.max_score || 0)} poeng</strong><br/>
          ${escapeHtml(formatAnalysisDistance(item.distance_meters))}
        </div>
      </div>
    `);
  });
};

const renderLocationAnalysis = () => {
  if (!locationAnalysisContainer) return;

  if (analysisState.loading) {
    locationAnalysisContainer.innerHTML = '<div class="analysis-panel__status">Analyserer punktet i databasen...</div>';
    return;
  }

  if (analysisState.error) {
    locationAnalysisContainer.innerHTML = `<div class="analysis-panel__error">${escapeHtml(analysisState.error)}</div>`;
    return;
  }

  if (!analysisState.data) {
    locationAnalysisContainer.innerHTML = `
      <div class="analysis-panel__placeholder">
        Klikk i kartet eller søk adresse for å beregne beredskapsscore.
      </div>
    `;
    return;
  }

  const score = Number(analysisState.data.score || 0);
  const maxScore = Number(analysisState.data.max_score || 100);
  const title = analysisState.label?.title || 'Valgt punkt';
  const meta = analysisState.label?.meta || formatAnalysisCoordinates(analysisState.data.clicked_point);
  const breakdown = Array.isArray(analysisState.data.breakdown) ? analysisState.data.breakdown : [];

  const breakdownHtml = breakdown.map((item) => {
    const style = analysisCategoryStyles[item.key] || { color: '#2563eb', short: '?' };
    const itemScore = Number(item.score || 0);
    const itemMaxScore = Number(item.max_score || 0);
    const ratioPercent = itemMaxScore > 0
      ? Math.max(0, Math.min(100, (itemScore / itemMaxScore) * 100))
      : 0;

    return `
      <div class="analysis-panel__item">
        <div class="analysis-panel__item-top">
          <div>
            <div class="analysis-panel__item-label" style="color: ${style.color};">
              ${escapeHtml(item.label || 'Kategori')}
            </div>
            <div class="analysis-panel__item-target">${escapeHtml(item.name || item.label || 'Treff')}</div>
          </div>
          <div class="analysis-panel__item-score">${itemScore} / ${itemMaxScore}</div>
        </div>
        <div class="analysis-panel__meter">
          <span style="width: ${ratioPercent}%; background: ${style.color};"></span>
        </div>
        <div class="analysis-panel__item-meta">${escapeHtml(buildAnalysisStatusText(item))}</div>
        <div class="analysis-panel__item-submeta">
          ${escapeHtml(formatAnalysisDistance(item.distance_meters))}
          ${item.description ? ` • ${escapeHtml(item.description)}` : ''}
        </div>
      </div>
    `;
  }).join('');

  locationAnalysisContainer.innerHTML = `
    <div class="analysis-panel__header">
      <div>
        <div class="analysis-panel__eyebrow">Punktanalyse</div>
        <div class="analysis-panel__place">${escapeHtml(title)}</div>
        <div class="analysis-panel__place-meta">${escapeHtml(meta)}</div>
      </div>
      <div class="analysis-panel__total">
        ${score}
        <span>/ ${maxScore}</span>
      </div>
    </div>
    <div class="analysis-panel__summary">${escapeHtml(describeAnalysisScore(score))}</div>
    <div class="analysis-panel__body">${breakdownHtml}</div>
  `;
};

const setLocationAnalysisState = (nextState = {}) => {
  Object.assign(analysisState, nextState);
  renderLocationAnalysis();
};

const updateLocationAnalysisLabel = (label) => {
  analysisState.label = label;
  renderLocationAnalysis();
};

const fetchLocationAnalysis = async (coords, label = null) => {
  if (!coords) return;
  const requestToken = ++analysisRequestToken;

  setLocationAnalysisState({
    loading: true,
    error: '',
    data: null,
    label: label || analysisState.label
  });
  clearAnalysisHighlights();

  try {
    const response = await fetch(`/api/location-analysis?lat=${coords.lat}&lon=${coords.lon}`);
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(payload?.error || 'Analyseoppslag feilet.');
    }
    if (requestToken !== analysisRequestToken) return;

    setLocationAnalysisState({
      loading: false,
      error: '',
      data: payload,
      label: label || analysisState.label
    });
    renderAnalysisHighlights(payload);
  } catch (error) {
    if (requestToken !== analysisRequestToken) return;
    clearAnalysisHighlights();
    setLocationAnalysisState({
      loading: false,
      data: null,
      error: error instanceof Error ? error.message : 'Klarte ikke analysere punktet.'
    });
  }
};

const setAnalysisZoneLegendVisibility = (visible) => {
  if (!analysisZoneLegend) return;
  analysisZoneLegend.classList.toggle('visible', visible);
  analysisZoneLegend.setAttribute('aria-hidden', visible ? 'false' : 'true');
};

const clearAnalysisZones = () => {
  layers.analysisZones.clearLayers();
};

const fetchAnalysisZones = async () => {
  if (!isLayerChecked('layer-analysis-zones')) {
    clearAnalysisZones();
    setAnalysisZoneLegendVisibility(false);
    return;
  }

  setAnalysisZoneLegendVisibility(true);
  applyLayerVisibility();

  const bounds = map.getBounds();
  const cellSizeM = getAnalysisZoneCellSize(map.getZoom());
  const requestToken = ++analysisZonesRequestToken;

  try {
    const response = await fetch(
      `/api/location-analysis-grid?min_lat=${bounds.getSouth()}&min_lon=${bounds.getWest()}&max_lat=${bounds.getNorth()}&max_lon=${bounds.getEast()}&cell_size_m=${cellSizeM}`
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(payload?.error || 'Kunne ikke laste beredskapssoner.');
    }
    if (requestToken !== analysisZonesRequestToken) return;

    clearAnalysisZones();
    layers.analysisZones.addData(payload);
  } catch (error) {
    if (requestToken !== analysisZonesRequestToken) return;
    clearAnalysisZones();
    console.error('Klarte ikke oppdatere beredskapssoner:', error);
  }
};

const scheduleAnalysisZoneRefresh = () => {
  clearTimeout(analysisZonesRefreshTimer);
  if (!isLayerChecked('layer-analysis-zones')) {
    clearAnalysisZones();
    setAnalysisZoneLegendVisibility(false);
    return;
  }
  analysisZonesRefreshTimer = setTimeout(() => {
    fetchAnalysisZones();
  }, 250);
};

renderLocationAnalysis();

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

const initializeAnalysisZoneControls = () => {
  const checkbox = document.getElementById('layer-analysis-zones');
  if (!checkbox) return;
  checkbox.addEventListener('change', () => {
    applyLayerVisibility();
    scheduleAnalysisZoneRefresh();
  });
  setAnalysisZoneLegendVisibility(checkbox.checked);
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
  activeSelectionToken += 1;
  clearActiveRoute();
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
  updateLocationAnalysisLabel(label);
  fetchLocationAnalysis(coords, label);
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

const routeToNearest = async (type) => {
  if (!fromSelection) return;
  const from = fromSelection.coords;
  try {
    const response = await fetch(`/api/nearest?type=${type}&lat=${from.lat}&lon=${from.lon}`);
    if (!response.ok) throw new Error('Nearest-oppslag feilet');
    const target = await response.json();
    if (!target || target.error) return;
    await renderRoute(from, { lat: target.lat, lon: target.lon });
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
  const selectionToken = ++activeSelectionToken;
  clearActiveRoute();
  if (addressMarker) addressLayer.removeLayer(addressMarker);
  addressMarker = L.marker([lat, lng]).addTo(addressLayer);
  const fallbackLabel = {
    title: 'Valgt punkt',
    meta: formatAnalysisCoordinates({ lat, lon: lng })
  };
  fromSelection = { coords: { lat, lon: lng }, label: fallbackLabel };
  updateLocationAnalysisLabel(fallbackLabel);
  fetchLocationAnalysis({ lat, lon: lng }, fallbackLabel);

  const address = await reverseGeocode(lat, lng);
  if (selectionToken !== activeSelectionToken) return;
  if (address) {
    const label = formatAddressLabel(address);
    fromSelection.label = label;
    if (addressInput) addressInput.value = label.title;
    updateLocationAnalysisLabel(label);
    addressMarker.bindPopup(buildRoutePopup(label.title, label.meta)).openPopup();
  } else {
    addressMarker.bindPopup(buildRoutePopup(fallbackLabel.title, fallbackLabel.meta)).openPopup();
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
initLayerToggle('layer-analysis-zones', layers.analysisZones);
applyLayerVisibility();
initializeAnalysisZoneControls();

map.on('zoomend', () => {
  updateMarkerSizes();
  scheduleAnalysisZoneRefresh();
});
map.on('moveend', scheduleAnalysisZoneRefresh);
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

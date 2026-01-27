console.log("Safemap landing page loaded");

// Initialize map centered on Norway
const map = L.map('map').setView([65.0, 13.0], 5);

// Add OpenStreetMap tiles
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors',
  maxZoom: 18
}).addTo(map);

// Custom icon for hospitals
const hospitalIcon = L.divIcon({
  className: 'hospital-marker',
  html: '<div style="background-color: #c0392b; width: 32px; height: 32px; border-radius: 50%; border: 3px solid white; box-shadow: 0 3px 6px rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 18px; font-family: Arial, sans-serif;">S</div>',
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
      loadingIndicator.textContent = `Viser ${hospitalCount} sykehus`;
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
    
    // Hide loading indicator after 2 seconds
    if (loadingIndicator) {
      setTimeout(() => {
        loadingIndicator.style.display = 'none';
      }, 2000);
    }
    
  } catch (error) {
    console.error('Feil ved lasting av sykehus:', error);
    if (loadingIndicator) {
      loadingIndicator.textContent = 'Feil ved lasting av data';
      loadingIndicator.style.backgroundColor = '#e74c3c';
      loadingIndicator.style.color = 'white';
    }
  }
}

// Load hospitals when page loads
loadHospitals();
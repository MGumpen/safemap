console.log("Safemap landing page loaded");

// Initialize map centered on Norway
const map = L.map('map').setView([65.0, 13.0], 5);

// Add OpenStreetMap tiles
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors',
  maxZoom: 18
}).addTo(map);
console.log("Safemap landing page loaded");

<<<<<<< HEAD
// Initialize map centered on UiA (Universitetet i Agder) in Kristiansand
const map = L.map('map').setView([58.1456, 8.0119], 14);
=======
// Initialize map centered on UiA (Universitetet i Agder) in Kristiansand
const map = L.map('map').setView([58.1456, 8.0119], 14);
>>>>>>> 092c883169b42b4063798574795edd2eaef97de8

// Add OpenStreetMap tiles
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors',
  maxZoom: 18
}).addTo(map);
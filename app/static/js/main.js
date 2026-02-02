console.log("Safemap landing page loaded");

// Initialize map centered on UiA (Universitetet i Agder) in Kristiansand
const map = L.map("map").setView([58.1456, 8.0119], 14);

// Add OpenStreetMap tiles
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "(c) OpenStreetMap contributors",
  maxZoom: 18,
}).addTo(map);

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

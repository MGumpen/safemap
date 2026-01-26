import { useState, useCallback } from 'react';
import { MapContainer, TileLayer, GeoJSON, useMapEvents, Marker, Popup } from 'react-leaflet';
import type L from 'leaflet';
import type { ScoreResponse, GridResponse } from '../types';
import { fetchScore } from '../api';

interface MapViewProps {
  onScoreChange: (score: ScoreResponse | null, loading: boolean) => void;
}

function getScoreColor(score: number): string {
  if (score >= 70) return '#22c55e';
  if (score >= 50) return '#84cc16';
  if (score >= 30) return '#f59e0b';
  return '#ef4444';
}

function MapEvents({ onMapClick }: { onMapClick: (lat: number, lng: number) => void }) {
  useMapEvents({
    click: (e) => {
      onMapClick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

export function MapView({ onScoreChange }: MapViewProps) {
  const [clickedPoint, setClickedPoint] = useState<{ lat: number; lng: number } | null>(null);
  const [gridData, _setGridData] = useState<GridResponse | null>(null);
  // Grid loading will be implemented in future iteration
  const [_isLoadingGrid, _setIsLoadingGrid] = useState(false);

  const handleMapClick = useCallback(async (lat: number, lng: number) => {
    setClickedPoint({ lat, lng });
    onScoreChange(null, true);

    try {
      const score = await fetchScore(lat, lng);
      onScoreChange(score, false);
    } catch (error) {
      console.error('Error fetching score:', error);
      onScoreChange(null, false);
    }
  }, [onScoreChange]);

  const gridStyle = useCallback((feature: GeoJSON.Feature) => {
    const score = feature.properties?.score ?? 50;
    return {
      fillColor: getScoreColor(score),
      weight: 1,
      opacity: 0.3,
      color: '#666',
      fillOpacity: 0.5,
    };
  }, []);

  const onEachGridCell = useCallback((feature: GeoJSON.Feature, layer: L.Layer) => {
    const score = feature.properties?.score ?? 0;
    layer.bindPopup(`Score: ${score.toFixed(1)}`);
  }, []);

  return (
    <MapContainer
      center={[63.4, 10.4]}
      zoom={6}
      className="h-full w-full"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.kartverket.no/">Kartverket</a>'
        url="https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
      />

      <MapEvents onMapClick={handleMapClick} />

      {gridData && (
        <GeoJSON
          key={JSON.stringify(gridData)}
          data={gridData as GeoJSON.FeatureCollection}
          style={gridStyle}
          onEachFeature={onEachGridCell}
        />
      )}

      {clickedPoint && (
        <Marker position={[clickedPoint.lat, clickedPoint.lng]}>
          <Popup>
            <div className="text-sm">
              <strong>Valgt punkt</strong><br />
              Lat: {clickedPoint.lat.toFixed(5)}<br />
              Lng: {clickedPoint.lng.toFixed(5)}
            </div>
          </Popup>
        </Marker>
      )}
    </MapContainer>
  );
}

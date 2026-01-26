import type { ScoreResponse, GridResponse, POIListResponse } from './types';

const API_BASE = '/api';

export async function fetchScore(lat: number, lng: number): Promise<ScoreResponse> {
  const res = await fetch(`${API_BASE}/score?lat=${lat}&lng=${lng}`);
  if (!res.ok) throw new Error(`Score API error: ${res.statusText}`);
  return res.json();
}

export async function fetchGrid(
  bbox: [number, number, number, number],
  resolution: number = 500
): Promise<GridResponse> {
  const bboxStr = bbox.join(',');
  const res = await fetch(`${API_BASE}/grid?bbox=${bboxStr}&resolution=${resolution}`);
  if (!res.ok) throw new Error(`Grid API error: ${res.statusText}`);
  return res.json();
}

export async function fetchPOIs(
  poiType?: string,
  bbox?: [number, number, number, number],
  limit: number = 500
): Promise<POIListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (poiType) params.set('poi_type', poiType);
  if (bbox) params.set('bbox', bbox.join(','));
  
  const res = await fetch(`${API_BASE}/pois?${params}`);
  if (!res.ok) throw new Error(`POI API error: ${res.statusText}`);
  return res.json();
}

export async function fetchHealth(): Promise<{ status: string; database: boolean; version: string }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health API error: ${res.statusText}`);
  return res.json();
}

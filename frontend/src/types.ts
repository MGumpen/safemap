export interface ScoreComponent {
  poi_type: string;
  distance_m: number;
  subscore: number;
  weight: number;
  weighted_contribution: number;
  nearest_name: string | null;
}

export interface ScoreResponse {
  score: number;
  model_version: string;
  lat: number;
  lng: number;
  components: ScoreComponent[];
}

export interface GridFeature {
  type: 'Feature';
  geometry: {
    type: 'Polygon';
    coordinates: number[][][];
  };
  properties: {
    score: number;
    resolution_m: number;
  };
}

export interface GridResponse {
  type: 'FeatureCollection';
  features: GridFeature[];
  model_version: string;
  resolution_m: number;
  cell_count: number;
}

export interface POI {
  id: number;
  type: string;
  name: string | null;
  lat: number;
  lng: number;
}

export interface POIListResponse {
  pois: POI[];
  count: number;
  poi_type: string | null;
}

"""Safety score calculation service."""

import math
from dataclasses import dataclass
from typing import Any

from backend.config import get_scoring_config
from backend.database import get_db_cursor


@dataclass
class NearestPOI:
    """Information about the nearest POI of a given type."""
    
    poi_type: str
    poi_id: int | None
    poi_name: str | None
    distance_m: float


@dataclass
class ScoreComponent:
    """Score component for one POI type."""
    
    poi_type: str
    distance_m: float
    subscore: float
    weight: float
    weighted_contribution: float
    nearest_name: str | None = None


@dataclass
class SafetyScore:
    """Complete safety score result."""
    
    score: float
    model_version: str
    components: list[ScoreComponent]
    lat: float
    lng: float


def calculate_subscore(distance_m: float, decay_m: float) -> float:
    """
    Calculate subscore using exponential decay.
    
    Score = 100 * exp(-distance / decay)
    
    Args:
        distance_m: Distance to nearest POI in meters
        decay_m: Decay constant in meters (distance at which score drops to ~37%)
    
    Returns:
        Score between 0 and 100
    """
    if distance_m <= 0:
        return 100.0
    return 100.0 * math.exp(-distance_m / decay_m)


def find_nearest_pois(lat: float, lng: float) -> list[NearestPOI]:
    """
    Find the nearest POI of each type for a given point.
    
    Uses PostGIS KNN operator (<->) for efficient spatial query.
    """
    poi_types = ["fire", "hospital", "police"]
    results = []
    
    with get_db_cursor() as cur:
        for poi_type in poi_types:
            cur.execute("""
                SELECT 
                    id,
                    name,
                    ST_Distance(
                        geom::geography,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                    ) AS distance_m
                FROM poi
                WHERE type = %s
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                LIMIT 1
            """, (lng, lat, poi_type, lng, lat))
            
            row = cur.fetchone()
            if row:
                results.append(NearestPOI(
                    poi_type=poi_type,
                    poi_id=row["id"],
                    poi_name=row["name"],
                    distance_m=row["distance_m"],
                ))
            else:
                # No POI of this type found - use very large distance
                results.append(NearestPOI(
                    poi_type=poi_type,
                    poi_id=None,
                    poi_name=None,
                    distance_m=float("inf"),
                ))
    
    return results


def calculate_safety_score(lat: float, lng: float) -> SafetyScore:
    """
    Calculate the complete safety score for a given point.
    
    Args:
        lat: Latitude (WGS84)
        lng: Longitude (WGS84)
    
    Returns:
        SafetyScore with final score and component breakdown
    """
    config = get_scoring_config()
    nearest_pois = find_nearest_pois(lat, lng)
    
    components = []
    total_score = 0.0
    
    for poi in nearest_pois:
        # Get config values for this POI type
        weight = getattr(config.weights, poi.poi_type, 0.0)
        decay = getattr(config.decay_meters, poi.poi_type, 5000.0)
        
        # Calculate subscore
        if poi.distance_m == float("inf"):
            subscore = 0.0
        else:
            subscore = calculate_subscore(poi.distance_m, decay)
        
        weighted = weight * subscore
        total_score += weighted
        
        components.append(ScoreComponent(
            poi_type=poi.poi_type,
            distance_m=poi.distance_m if poi.distance_m != float("inf") else -1,
            subscore=round(subscore, 2),
            weight=weight,
            weighted_contribution=round(weighted, 2),
            nearest_name=poi.poi_name,
        ))
    
    # Clamp final score to 0-100
    final_score = max(0.0, min(100.0, total_score))
    
    return SafetyScore(
        score=round(final_score, 2),
        model_version=config.model_version,
        components=components,
        lat=lat,
        lng=lng,
    )


def calculate_grid_scores(
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    resolution_m: int = 500,
) -> list[dict[str, Any]]:
    """
    Calculate safety scores for a grid of cells within a bounding box.
    
    Args:
        min_lng, min_lat, max_lng, max_lat: Bounding box coordinates
        resolution_m: Cell size in meters
    
    Returns:
        List of cell data with geometry and score
    """
    config = get_scoring_config()
    
    # Approximate degrees per meter at this latitude
    center_lat = (min_lat + max_lat) / 2
    lat_deg_per_m = 1.0 / 111320.0
    lng_deg_per_m = 1.0 / (111320.0 * math.cos(math.radians(center_lat)))
    
    cell_lat = resolution_m * lat_deg_per_m
    cell_lng = resolution_m * lng_deg_per_m
    
    # Calculate number of cells
    n_cols = int((max_lng - min_lng) / cell_lng) + 1
    n_rows = int((max_lat - min_lat) / cell_lat) + 1
    
    # Limit total cells
    total_cells = n_cols * n_rows
    if total_cells > config.max_grid_cells:
        # Return empty if too many cells requested
        return []
    
    cells = []
    for row in range(n_rows):
        for col in range(n_cols):
            cell_min_lng = min_lng + col * cell_lng
            cell_min_lat = min_lat + row * cell_lat
            cell_max_lng = cell_min_lng + cell_lng
            cell_max_lat = cell_min_lat + cell_lat
            
            # Calculate score at cell center
            center_lng = (cell_min_lng + cell_max_lng) / 2
            center_lat = (cell_min_lat + cell_max_lat) / 2
            
            score_result = calculate_safety_score(center_lat, center_lng)
            
            cells.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [cell_min_lng, cell_min_lat],
                        [cell_max_lng, cell_min_lat],
                        [cell_max_lng, cell_max_lat],
                        [cell_min_lng, cell_max_lat],
                        [cell_min_lng, cell_min_lat],
                    ]],
                },
                "properties": {
                    "score": score_result.score,
                    "resolution_m": resolution_m,
                },
            })
    
    return cells

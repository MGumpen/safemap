"""Pydantic schemas for API request/response models."""

from pydantic import BaseModel, Field


class ScoreComponentResponse(BaseModel):
    """Score component for one POI type."""
    
    poi_type: str = Field(..., description="Type of POI (fire, hospital, police)")
    distance_m: float = Field(..., description="Distance to nearest POI in meters (-1 if none found)")
    subscore: float = Field(..., description="Subscore for this POI type (0-100)")
    weight: float = Field(..., description="Weight of this component in final score")
    weighted_contribution: float = Field(..., description="Contribution to final score")
    nearest_name: str | None = Field(None, description="Name of the nearest POI")


class ScoreResponse(BaseModel):
    """Response for point score calculation."""
    
    score: float = Field(..., description="Final safety score (0-100)")
    model_version: str = Field(..., description="Scoring model version")
    lat: float = Field(..., description="Latitude of queried point")
    lng: float = Field(..., description="Longitude of queried point")
    components: list[ScoreComponentResponse] = Field(..., description="Score breakdown by POI type")


class GridCellProperties(BaseModel):
    """Properties for a grid cell."""
    
    score: float
    resolution_m: int


class GridGeometry(BaseModel):
    """GeoJSON geometry for a grid cell."""
    
    type: str = "Polygon"
    coordinates: list


class GridFeature(BaseModel):
    """GeoJSON feature for a grid cell."""
    
    type: str = "Feature"
    geometry: GridGeometry
    properties: GridCellProperties


class GridResponse(BaseModel):
    """GeoJSON FeatureCollection response for grid."""
    
    type: str = "FeatureCollection"
    features: list[GridFeature]
    model_version: str
    resolution_m: int
    cell_count: int


class POIResponse(BaseModel):
    """Response for a single POI."""
    
    id: int
    type: str
    name: str | None
    lat: float
    lng: float


class POIListResponse(BaseModel):
    """Response for list of POIs."""
    
    pois: list[POIResponse]
    count: int
    poi_type: str | None


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str
    database: bool
    version: str

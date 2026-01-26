"""SafeMap FastAPI Application."""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings, get_scoring_config
from backend.database import get_db_cursor, test_connection
from backend.schemas import (
    GridResponse,
    HealthResponse,
    POIListResponse,
    POIResponse,
    ScoreComponentResponse,
    ScoreResponse,
)
from backend.scoring import calculate_grid_scores, calculate_safety_score

# Create FastAPI app
settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    description="Safety score API for Norway based on proximity to emergency services",
    version="1.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Health & Info Endpoints
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Check API and database health."""
    db_ok = test_connection()
    config = get_scoring_config()
    
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        database=db_ok,
        version=config.model_version,
    )


@app.get("/", tags=["Health"])
async def root():
    """API root - basic info."""
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/health",
    }


# =============================================================================
# Score Endpoints
# =============================================================================

@app.get("/score", response_model=ScoreResponse, tags=["Scoring"])
async def get_score(
    lat: float = Query(..., ge=-90, le=90, description="Latitude (WGS84)"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude (WGS84)"),
):
    """
    Calculate safety score for a specific point.
    
    Returns a score from 0-100 based on proximity to:
    - Fire stations (40% weight)
    - Hospitals (35% weight)
    - Police stations (25% weight)
    
    Also returns detailed breakdown showing distance to nearest POI of each type.
    """
    try:
        result = calculate_safety_score(lat, lng)
        
        return ScoreResponse(
            score=result.score,
            model_version=result.model_version,
            lat=result.lat,
            lng=result.lng,
            components=[
                ScoreComponentResponse(
                    poi_type=c.poi_type,
                    distance_m=c.distance_m,
                    subscore=c.subscore,
                    weight=c.weight,
                    weighted_contribution=c.weighted_contribution,
                    nearest_name=c.nearest_name,
                )
                for c in result.components
            ],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating score: {str(e)}")


@app.get("/grid", response_model=GridResponse, tags=["Scoring"])
async def get_grid(
    bbox: str = Query(
        ...,
        description="Bounding box as 'minLng,minLat,maxLng,maxLat'",
        examples=["10.5,59.8,10.9,60.0"],
    ),
    resolution: int = Query(
        500,
        ge=100,
        le=10000,
        description="Grid cell size in meters",
    ),
):
    """
    Get safety scores for a grid of cells within a bounding box.
    
    Returns a GeoJSON FeatureCollection with polygon cells colored by score.
    
    Note: Large areas with fine resolution may be rejected to prevent overload.
    Maximum ~5000 cells per request.
    """
    try:
        parts = bbox.split(",")
        if len(parts) != 4:
            raise ValueError("bbox must have 4 comma-separated values")
        
        min_lng, min_lat, max_lng, max_lat = map(float, parts)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid bbox format: {e}")
    
    # Validate bbox is in Norway roughly
    if not (4 <= min_lng <= 32 and 57 <= min_lat <= 72):
        raise HTTPException(status_code=400, detail="Coordinates outside Norway")
    
    try:
        cells = calculate_grid_scores(min_lng, min_lat, max_lng, max_lat, resolution)
        
        if not cells:
            raise HTTPException(
                status_code=400,
                detail="Too many cells requested. Reduce bbox size or increase resolution.",
            )
        
        config = get_scoring_config()
        
        return GridResponse(
            type="FeatureCollection",
            features=cells,
            model_version=config.model_version,
            resolution_m=resolution,
            cell_count=len(cells),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating grid: {str(e)}")


# =============================================================================
# POI Endpoints
# =============================================================================

@app.get("/pois", response_model=POIListResponse, tags=["POIs"])
async def list_pois(
    poi_type: str | None = Query(None, description="Filter by type (fire, hospital, police)"),
    bbox: str | None = Query(None, description="Bounding box as 'minLng,minLat,maxLng,maxLat'"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of POIs to return"),
):
    """
    List POIs, optionally filtered by type and/or bounding box.
    """
    with get_db_cursor() as cur:
        query = "SELECT id, type, name, ST_Y(geom) as lat, ST_X(geom) as lng FROM poi WHERE 1=1"
        params = []
        
        if poi_type:
            query += " AND type = %s"
            params.append(poi_type)
        
        if bbox:
            try:
                parts = bbox.split(",")
                min_lng, min_lat, max_lng, max_lat = map(float, parts)
                query += " AND ST_Within(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
                params.extend([min_lng, min_lat, max_lng, max_lat])
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid bbox format")
        
        query += f" LIMIT {limit}"
        
        cur.execute(query, params)
        rows = cur.fetchall()
    
    pois = [
        POIResponse(
            id=row["id"],
            type=row["type"],
            name=row["name"],
            lat=row["lat"],
            lng=row["lng"],
        )
        for row in rows
    ]
    
    return POIListResponse(
        pois=pois,
        count=len(pois),
        poi_type=poi_type,
    )


@app.get("/pois/stats", tags=["POIs"])
async def poi_stats():
    """Get statistics about POIs in the database."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT type, COUNT(*) as count
            FROM poi
            GROUP BY type
            ORDER BY type
        """)
        rows = cur.fetchall()
    
    return {
        "poi_counts": {row["type"]: row["count"] for row in rows},
        "total": sum(row["count"] for row in rows),
    }


# =============================================================================
# Run with: uvicorn backend.main:app --reload
# =============================================================================

"""SafeMap configuration management."""

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """Database connection settings."""
    
    url: str = "postgresql://postgres:safemap@127.0.0.1:5433/safemap"
    
    class Config:
        env_prefix = "DATABASE_"


class ScoringWeights(BaseModel):
    """Weights for each POI type in final score."""
    
    fire: float = 0.40
    hospital: float = 0.35
    police: float = 0.25


class ScoringDecay(BaseModel):
    """Distance decay parameters (in meters)."""
    
    fire: float = 2000.0
    hospital: float = 6000.0
    police: float = 4000.0


class ScoringConfig(BaseModel):
    """Complete scoring configuration."""
    
    model_version: str = "v1.0"
    weights: ScoringWeights = ScoringWeights()
    decay_meters: ScoringDecay = ScoringDecay()
    max_grid_cells: int = 5000
    
    # Zoom level to grid resolution mapping
    grid_resolutions: dict[int, int] = {
        5: 10000,
        6: 5000,
        7: 2500,
        8: 2000,
        9: 1000,
        10: 500,
        11: 500,
        12: 250,
        13: 250,
        14: 100,
    }


class Settings(BaseSettings):
    """Application settings."""
    
    app_name: str = "SafeMap API"
    debug: bool = False
    
    # CORS settings
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


@lru_cache
def get_database_settings() -> DatabaseSettings:
    """Get cached database settings."""
    return DatabaseSettings()


@lru_cache
def get_scoring_config() -> ScoringConfig:
    """Load scoring configuration from YAML file or use defaults."""
    config_path = Path(__file__).parent.parent / "config" / "scoring_config.yaml"
    
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return ScoringConfig(**data)
    
    return ScoringConfig()

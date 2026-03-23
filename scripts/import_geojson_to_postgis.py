#!/usr/bin/env python3
"""
Mirror local GeoJSON source files into PostGIS tables.

The web map can continue to render directly from JSON, while spatial SQL can
query the same data from the database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

SCRIPT_PATH = Path(__file__).resolve()


def detect_project_root() -> Path:
    candidates = [
        SCRIPT_PATH.parent.parent,
        Path("/"),
        Path.cwd(),
    ]
    for candidate in candidates:
        if (candidate / "src").exists():
            return candidate
    return SCRIPT_PATH.parent.parent


PROJECT_ROOT = detect_project_root()
DEFAULT_DATA_DIR = PROJECT_ROOT / "src"

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class DatasetConfig:
    cli_name: str
    table_name: str
    source_path: Path
    fallback_name: str


DATASETS: dict[str, DatasetConfig] = {
    "sykehus": DatasetConfig(
        cli_name="sykehus",
        table_name="sykehus_points",
        source_path=DEFAULT_DATA_DIR / "sykehus.json",
        fallback_name="Sykehus",
    ),
    "legevakter": DatasetConfig(
        cli_name="legevakter",
        table_name="legevakt_points",
        source_path=DEFAULT_DATA_DIR / "legevakter.json",
        fallback_name="Legevakt",
    ),
}


def import_db_modules():
    try:
        import psycopg2
        from psycopg2 import sql
        from psycopg2.extras import execute_values
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "psycopg2 er ikke installert i aktivt Python-miljo. "
            "Installer avhengighetene eller kjor skriptet i Docker-miljoet."
        ) from exc
    return psycopg2, sql, execute_values


def get_db_connection():
    psycopg2, _, _ = import_db_modules()
    env = {
        "user": os.getenv("user"),
        "password": os.getenv("password"),
        "host": os.getenv("host"),
        "port": os.getenv("port"),
        "dbname": os.getenv("dbname"),
    }
    missing = [key for key, value in env.items() if not value]
    if missing:
        missing_str = ", ".join(sorted(missing))
        raise ValueError(f"Database-variabler mangler i .env: {missing_str}.")
    return psycopg2.connect(**env)


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\xa0", " ").strip()
    if not text:
        return None
    return text


def build_source_key(
    config: DatasetConfig,
    feature_index: int,
    properties: dict[str, Any],
    lon: float,
    lat: float,
) -> str:
    payload = {
        "dataset": config.cli_name,
        "feature_index": feature_index,
        "properties": properties,
        "lon": round(lon, 7),
        "lat": round(lat, 7),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def load_geojson_rows(config: DatasetConfig) -> list[tuple[Any, ...]]:
    if not config.source_path.exists():
        raise FileNotFoundError(f"Fant ikke kildefil: {config.source_path}")

    payload = json.loads(config.source_path.read_text(encoding="utf-8"))
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError(f"Ugyldig GeoJSON i {config.source_path}: mangler features-liste.")

    rows: list[tuple[Any, ...]] = []
    for feature_index, feature in enumerate(features):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue

        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue

        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except (TypeError, ValueError):
            continue

        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}

        navn = normalize_text(properties.get("navn") or properties.get("name")) or config.fallback_name
        adresse = normalize_text(properties.get("adresse"))
        postnummer = normalize_text(properties.get("postnummer"))
        poststed = normalize_text(properties.get("poststed"))
        kommune = normalize_text(properties.get("kommune"))
        source_file = str(config.source_path.relative_to(PROJECT_ROOT))
        source_key = build_source_key(config, feature_index, properties, lon, lat)

        rows.append(
            (
                source_key,
                navn,
                adresse,
                postnummer,
                poststed,
                kommune,
                source_file,
                feature_index,
                json.dumps(properties, ensure_ascii=False, sort_keys=True),
                lon,
                lat,
            )
        )

    return rows


def ensure_postgis(cursor) -> None:
    try:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    except Exception:
        cursor.connection.rollback()
        with cursor.connection.cursor() as check_cursor:
            check_cursor.execute("SELECT PostGIS_version();")


def ensure_table(cursor, table_name: str) -> None:
    _, sql, _ = import_db_modules()
    table_identifier = sql.Identifier(table_name)
    geom_index = sql.Identifier(f"{table_name}_geom_gix")
    navn_index = sql.Identifier(f"{table_name}_navn_idx")

    cursor.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {table_name} (
                id BIGSERIAL PRIMARY KEY,
                source_key TEXT NOT NULL UNIQUE,
                navn TEXT NOT NULL,
                adresse TEXT,
                postnummer TEXT,
                poststed TEXT,
                kommune TEXT,
                source_file TEXT NOT NULL,
                source_index INTEGER NOT NULL,
                properties JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                geom geometry(Point, 4326) NOT NULL
            );
            """
        ).format(table_name=table_identifier)
    )
    cursor.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} USING GIST (geom);").format(
            index_name=geom_index,
            table_name=table_identifier,
        )
    )
    cursor.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} (navn);").format(
            index_name=navn_index,
            table_name=table_identifier,
        )
    )


def refresh_table(cursor, config: DatasetConfig, rows: list[tuple[Any, ...]]) -> None:
    _, sql, execute_values = import_db_modules()
    table_identifier = sql.Identifier(config.table_name)
    cursor.execute(
        sql.SQL("TRUNCATE TABLE {table_name} RESTART IDENTITY;").format(
            table_name=table_identifier
        )
    )

    if not rows:
        return

    insert_sql = sql.SQL(
        """
        INSERT INTO {table_name} (
            source_key,
            navn,
            adresse,
            postnummer,
            poststed,
            kommune,
            source_file,
            source_index,
            properties,
            geom
        )
        VALUES %s;
        """
    ).format(table_name=table_identifier)

    execute_values(
        cursor,
        insert_sql.as_string(cursor.connection),
        rows,
        template=(
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
            "ST_SetSRID(ST_MakePoint(%s, %s), 4326))"
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Importer GeoJSON-kilder fra src/ til PostGIS-tabeller. "
            "JSON beholdes som visningskilde i kartet."
        )
    )
    parser.add_argument(
        "--dataset",
        choices=["all", *DATASETS.keys()],
        default="all",
        help="Velg hvilken kilde som skal importeres.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valider GeoJSON og skriv sammendrag uten aa koble til databasen.",
    )
    return parser.parse_args()


def selected_datasets(dataset_name: str) -> list[DatasetConfig]:
    if dataset_name == "all":
        return [DATASETS["sykehus"], DATASETS["legevakter"]]
    return [DATASETS[dataset_name]]


def main() -> None:
    args = parse_args()
    datasets = selected_datasets(args.dataset)

    rows_by_dataset: list[tuple[DatasetConfig, list[tuple[Any, ...]]]] = []
    for config in datasets:
        rows = load_geojson_rows(config)
        rows_by_dataset.append((config, rows))
        print(
            f"{config.cli_name}: klar til import fra {config.source_path} "
            f"({len(rows)} punkter -> {config.table_name})"
        )

    if args.dry_run:
        print("Dry run fullforte uten databaseendringer.")
        return

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            ensure_postgis(cursor)
            for config, rows in rows_by_dataset:
                ensure_table(cursor, config.table_name)
                refresh_table(cursor, config, rows)
                print(f"Importerte {len(rows)} rader til {config.table_name}.")

    print("Import fullfort.")


if __name__ == "__main__":
    main()

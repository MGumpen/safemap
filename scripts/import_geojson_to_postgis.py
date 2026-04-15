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
    geometry_kind: str
    fallback_name: str | None = None


@dataclass(frozen=True)
class ResolvedDatasetConfig:
    cli_name: str
    table_name: str
    source_path: Path
    geometry_kind: str
    fallback_name: str | None = None


DATASETS: dict[str, DatasetConfig] = {
    "sykehus": DatasetConfig(
        cli_name="sykehus",
        table_name="sykehus_points",
        source_path=DEFAULT_DATA_DIR / "sykehus.json",
        geometry_kind="point",
        fallback_name="Sykehus",
    ),
    "legevakter": DatasetConfig(
        cli_name="legevakter",
        table_name="legevakt_points",
        source_path=DEFAULT_DATA_DIR / "legevakter.json",
        geometry_kind="point",
        fallback_name="Legevakt",
    ),
    "vegnett_gangnett": DatasetConfig(
        cli_name="vegnett_gangnett",
        table_name="vegnett_pluss_gangnett",
        source_path=DEFAULT_DATA_DIR / "vegnett_pluss_gangnett.geojson",
        geometry_kind="line",
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


def _relative_source_label(source_path: Path) -> str:
    try:
        return str(source_path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(source_path.resolve())


def load_point_rows(config: ResolvedDatasetConfig) -> list[tuple[Any, ...]]:
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
        source_file = _relative_source_label(config.source_path)
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


def coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_line_rows(config: ResolvedDatasetConfig) -> list[tuple[Any, ...]]:
    if not config.source_path.exists():
        raise FileNotFoundError(f"Fant ikke kildefil: {config.source_path}")

    payload = json.loads(config.source_path.read_text(encoding="utf-8"))
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError(f"Ugyldig GeoJSON i {config.source_path}: mangler features-liste.")

    rows: list[tuple[Any, ...]] = []
    for feature_index, feature in enumerate(features):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue

        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue

        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}

        source_key = normalize_text(properties.get("source_key"))
        if not source_key:
            source_key = build_source_key(
                config=config,
                feature_index=feature_index,
                properties=properties,
                lon=float(coords[0][0]),
                lat=float(coords[0][1]),
            )

        source_file = _relative_source_label(config.source_path)
        rows.append(
            (
                source_key,
                normalize_text(properties.get("startnode")),
                normalize_text(properties.get("sluttnode")),
                normalize_text(properties.get("type_veg")) or "Gangnett",
                coerce_float(properties.get("lengde_meters")),
                source_file,
                feature_index,
                json.dumps(properties, ensure_ascii=False, sort_keys=True),
                json.dumps(geometry, ensure_ascii=False, sort_keys=True),
            )
        )

    return rows


def load_geojson_rows(config: ResolvedDatasetConfig) -> list[tuple[Any, ...]]:
    if config.geometry_kind == "point":
        return load_point_rows(config)
    if config.geometry_kind == "line":
        return load_line_rows(config)
    raise ValueError(f"Ustottet geometry_kind for {config.cli_name}: {config.geometry_kind}")


def ensure_postgis(cursor) -> None:
    try:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    except Exception:
        cursor.connection.rollback()
        with cursor.connection.cursor() as check_cursor:
            check_cursor.execute("SELECT PostGIS_version();")


def ensure_point_table(cursor, table_name: str) -> None:
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


def ensure_line_table(cursor, table_name: str) -> None:
    _, sql, _ = import_db_modules()
    table_identifier = sql.Identifier(table_name)
    geom_index = sql.Identifier(f"{table_name}_geom_gix")
    source_node_index = sql.Identifier(f"{table_name}_source_node_idx")
    target_node_index = sql.Identifier(f"{table_name}_target_node_idx")
    type_veg_index = sql.Identifier(f"{table_name}_type_veg_idx")

    cursor.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {table_name} (
                id BIGSERIAL PRIMARY KEY,
                source_key TEXT NOT NULL UNIQUE,
                source_node TEXT,
                target_node TEXT,
                type_veg TEXT NOT NULL,
                length_meters DOUBLE PRECISION,
                source_file TEXT NOT NULL,
                source_index INTEGER NOT NULL,
                properties JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                geom geometry(LineString, 4326) NOT NULL
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
        sql.SQL("CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} (source_node);").format(
            index_name=source_node_index,
            table_name=table_identifier,
        )
    )
    cursor.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} (target_node);").format(
            index_name=target_node_index,
            table_name=table_identifier,
        )
    )
    cursor.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} (type_veg);").format(
            index_name=type_veg_index,
            table_name=table_identifier,
        )
    )


def ensure_table(cursor, config: DatasetConfig) -> None:
    if config.geometry_kind == "point":
        ensure_point_table(cursor, config.table_name)
        return
    if config.geometry_kind == "line":
        ensure_line_table(cursor, config.table_name)
        return
    raise ValueError(f"Ustottet geometry_kind for {config.cli_name}: {config.geometry_kind}")


def refresh_point_table(cursor, config: DatasetConfig, rows: list[tuple[Any, ...]]) -> None:
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


def refresh_line_table(cursor, config: DatasetConfig, rows: list[tuple[Any, ...]]) -> None:
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
            source_node,
            target_node,
            type_veg,
            length_meters,
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
            "(%s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
            "ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))"
        ),
    )


def refresh_table(cursor, config: DatasetConfig, rows: list[tuple[Any, ...]]) -> None:
    if config.geometry_kind == "point":
        refresh_point_table(cursor, config, rows)
        return
    if config.geometry_kind == "line":
        refresh_line_table(cursor, config, rows)
        return
    raise ValueError(f"Ustottet geometry_kind for {config.cli_name}: {config.geometry_kind}")


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
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=(
            "Overstyr kildefilen for valgt dataset. Kan bare brukes sammen med "
            "ett konkret dataset, ikke --dataset all."
        ),
    )
    return parser.parse_args()


def selected_datasets(dataset_name: str) -> list[DatasetConfig]:
    if dataset_name == "all":
        return [DATASETS["sykehus"], DATASETS["legevakter"]]
    return [DATASETS[dataset_name]]


def resolve_datasets(dataset_name: str, source_override: Path | None) -> list[ResolvedDatasetConfig]:
    selected = selected_datasets(dataset_name)
    if source_override is not None and len(selected) != 1:
        raise ValueError("--source kan bare brukes sammen med ett konkret dataset.")

    resolved: list[ResolvedDatasetConfig] = []
    for config in selected:
        resolved.append(
            ResolvedDatasetConfig(
                cli_name=config.cli_name,
                table_name=config.table_name,
                source_path=source_override.resolve() if source_override is not None else config.source_path,
                geometry_kind=config.geometry_kind,
                fallback_name=config.fallback_name,
            )
        )
    return resolved


def main() -> None:
    args = parse_args()
    datasets = resolve_datasets(args.dataset, args.source)

    rows_by_dataset: list[tuple[DatasetConfig, list[tuple[Any, ...]]]] = []
    for config in datasets:
        rows = load_geojson_rows(config)
        rows_by_dataset.append((config, rows))
        object_label = "punkter" if config.geometry_kind == "point" else "linjer"
        print(
            f"{config.cli_name}: klar til import fra {config.source_path} "
            f"({len(rows)} {object_label} -> {config.table_name})"
        )

    if args.dry_run:
        print("Dry run fullforte uten databaseendringer.")
        return

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            ensure_postgis(cursor)
            for config, rows in rows_by_dataset:
                ensure_table(cursor, config)
                refresh_table(cursor, config, rows)
                print(f"Importerte {len(rows)} rader til {config.table_name}.")

    print("Import fullfort.")


if __name__ == "__main__":
    main()

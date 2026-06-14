#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import geopandas as gpd
import numpy as np
import pandas as pd

from src.core.mesh import collect_obj_paths, load_mesh_from_objs
from src.core.shadow import (
    build_building_mesh,
    estimate_terrace_origins,
    origins_in_sun,
    sample_ground_heights,
)
from src.core.sun import HELSINKI_TZ, sun_position
from src.core.terraces import (
    load_terraces,
    sample_polygon_points,
    terraces_to_local_crs,
)


DEFAULT_BUILDINGS_PATH = pathlib.Path("data/processed/buildings.parquet")
DEFAULT_TERRACES_PATH = pathlib.Path("data/terraces.geojson")
DEFAULT_POLYGONS_PATH = pathlib.Path("data/terrace_polygons.geojson")
DEFAULT_OUTPUT_PATH = pathlib.Path("data/shadows/terrace_shadows.parquet")
DEFAULT_MESH_ROOT = pathlib.Path("data/raw/mesh")


def _date_range(start: date, end: date, day_step: int) -> list[date]:
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current = current + timedelta(days=day_step)
    return dates


def _time_grid(hours: list[int]) -> list[time]:
    return [time(hour=hour, minute=0) for hour in hours]


def _build_datetimes(
    start_date: date,
    end_date: date,
    day_step: int,
    hours: list[int],
    tz: ZoneInfo,
) -> list[datetime]:
    dates = _date_range(start_date, end_date, day_step)
    times = _time_grid(hours)
    datetimes = []
    for day in dates:
        for hour in times:
            datetimes.append(datetime.combine(day, hour, tzinfo=tz))
    return datetimes


def _load_buildings(path: pathlib.Path) -> gpd.GeoDataFrame:
    return gpd.read_parquet(path)


def _validate_sun(latitude: float, longitude: float) -> None:
    midsummer = datetime(2026, 6, 21, 12, 0, tzinfo=HELSINKI_TZ)
    midwinter = datetime(2026, 12, 21, 12, 0, tzinfo=HELSINKI_TZ)
    summer_pos = sun_position(latitude, longitude, midsummer)
    winter_pos = sun_position(latitude, longitude, midwinter)
    print(
        "Sun altitude check:",
        f"midsummer={summer_pos.altitude_deg:.2f}deg",
        f"midwinter={winter_pos.altitude_deg:.2f}deg",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Precompute sun/shade table for terraces.",
    )
    parser.add_argument(
        "--buildings",
        default=str(DEFAULT_BUILDINGS_PATH),
        help="Path to buildings parquet file.",
    )
    parser.add_argument(
        "--terraces",
        default=str(DEFAULT_TERRACES_PATH),
        help="Path to terraces GeoJSON.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Output parquet path for sun/shade table.",
    )
    parser.add_argument(
        "--polygons",
        default=str(DEFAULT_POLYGONS_PATH),
        help="Terrace permit polygons GeoJSON (from fetch_terrace_polygons).",
    )
    parser.add_argument(
        "--mesh-root",
        default=str(DEFAULT_MESH_ROOT),
        help="Root directory for Helsinki 3D mesh tiles (OBJ).",
    )
    parser.add_argument(
        "--mesh-lod",
        default="L13",
        help="Mesh level of detail to load (default: L13).",
    )
    parser.add_argument(
        "--start-date",
        default="2026-01-01",
        help="Start date for time grid (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        default="2026-12-31",
        help="End date for time grid (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--day-step",
        type=int,
        default=14,
        help="Day step for sampling (default: 14).",
    )
    parser.add_argument(
        "--hours",
        default="8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23",
        help="Comma-separated hours for sampling (default: hourly 8..23).",
    )
    parser.add_argument(
        "--latitude",
        type=float,
        default=60.1695,
        help="Latitude for sun position calculations (default: Helsinki center).",
    )
    parser.add_argument(
        "--longitude",
        type=float,
        default=24.9417,
        help="Longitude for sun position calculations (default: Helsinki center).",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Print sun altitude sanity checks.",
    )
    args = parser.parse_args()

    if args.validate:
        _validate_sun(args.latitude, args.longitude)

    buildings_path = pathlib.Path(args.buildings)
    terraces_path = pathlib.Path(args.terraces)
    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    terraces = load_terraces(terraces_path)
    mesh_root = pathlib.Path(args.mesh_root)
    obj_paths = collect_obj_paths(mesh_root, args.mesh_lod) if mesh_root.exists() else []

    if obj_paths:
        print(f"Loading {len(obj_paths)} mesh tiles ({args.mesh_lod}) from {mesh_root}")
        mesh = load_mesh_from_objs(obj_paths)
        terraces_local = terraces_to_local_crs(terraces, target_crs="EPSG:3879")
        mesh_includes_terrain = True
    else:
        print(f"No mesh tiles under {mesh_root}; falling back to {buildings_path}")
        buildings = _load_buildings(buildings_path)
        terraces_local = terraces_to_local_crs(
            terraces, target_crs=buildings.crs or "EPSG:3879"
        )
        mesh = build_building_mesh(buildings)
        mesh_includes_terrain = False

    polygons_path = pathlib.Path(args.polygons)
    polygons_by_id: dict[str, object] = {}
    if polygons_path.exists():
        polygons = gpd.read_file(polygons_path).to_crs(terraces_local.crs)
        polygons_by_id = dict(
            zip(polygons["terrace_id"].astype(str), polygons.geometry)
        )

    terrace_points = []
    terrace_ids = []
    id_series = terraces_local.get("id")
    for idx, geom in enumerate(terraces_local.geometry):
        if geom is None or geom.geom_type != "Point":
            continue
        terrace_points.append((geom.x, geom.y))
        if id_series is not None:
            terrace_ids.append(str(id_series.iloc[idx]))
        else:
            terrace_ids.append(str(idx))

    if not terrace_points:
        print("No terrace points found; nothing to compute.")
        return 1

    # Build ray origins. Terraces with a real permit polygon are sampled on a
    # grid across the polygon (origins at street level + 1.5 m). The rest use
    # the single POI point, relocated out of the building footprint if needed.
    polygon_origins: list[np.ndarray | None] = []
    fallback_indices = []
    for index, (terrace_id, point) in enumerate(zip(terrace_ids, terrace_points)):
        polygon = polygons_by_id.get(terrace_id)
        if polygon is None:
            polygon_origins.append(None)
            fallback_indices.append(index)
            continue
        samples = sample_polygon_points(polygon)
        if mesh_includes_terrain:
            ground = sample_ground_heights(mesh, samples, probe_radii=(0.0, 3.0))
        else:
            ground = np.zeros(len(samples))
        polygon_origins.append(
            np.array([[x, y, z + 1.5] for (x, y), z in zip(samples, ground)])
        )

    fallback_origins = estimate_terrace_origins(
        mesh,
        [terrace_points[i] for i in fallback_indices],
        terrain=mesh_includes_terrain,
    )

    origin_rows: list[np.ndarray] = []
    origin_terrace = []
    fallback_cursor = 0
    for index in range(len(terrace_ids)):
        if polygon_origins[index] is not None:
            block = polygon_origins[index]
        else:
            block = fallback_origins[fallback_cursor : fallback_cursor + 1]
            fallback_cursor += 1
        origin_rows.append(block)
        origin_terrace.extend([index] * len(block))

    origins = np.vstack(origin_rows)
    origin_terrace = np.asarray(origin_terrace)
    sample_counts = np.bincount(origin_terrace, minlength=len(terrace_ids))
    print(
        f"{len(polygons_by_id)} terraces use permit polygons "
        f"({int(sample_counts[sample_counts > 1].sum())} sampled points), "
        f"{len(fallback_indices)} use single-point fallback"
    )

    start_date = datetime.fromisoformat(args.start_date).date()
    end_date = datetime.fromisoformat(args.end_date).date()
    hours = [int(value.strip()) for value in args.hours.split(",") if value.strip()]
    datetimes = _build_datetimes(
        start_date=start_date,
        end_date=end_date,
        day_step=args.day_step,
        hours=hours,
        tz=HELSINKI_TZ,
    )

    records = []
    for current in datetimes:
        position = sun_position(args.latitude, args.longitude, current)
        if position.altitude_deg <= 0:
            fraction = np.zeros(len(terrace_ids), dtype=float)
        else:
            sunny = origins_in_sun(mesh, origins, position.direction)
            fraction = (
                np.bincount(origin_terrace, weights=sunny, minlength=len(terrace_ids))
                / sample_counts
            )
        for terrace_id, value in zip(terrace_ids, fraction, strict=True):
            records.append(
                {
                    "terrace_id": terrace_id,
                    "datetime": current,
                    "in_sun": bool(value >= 0.5),
                    "sun_fraction": float(value),
                }
            )

    table = pd.DataFrame.from_records(records)
    table.to_parquet(output_path, index=False)
    print(f"Wrote {len(table)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

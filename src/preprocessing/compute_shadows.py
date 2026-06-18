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


def _time_grid(start_hour: int, end_hour: int, minute_step: int) -> list[time]:
    """Times from start_hour:00 to end_hour:00 inclusive, every minute_step minutes."""
    grid = []
    minute = start_hour * 60
    end = end_hour * 60
    while minute <= end:
        grid.append(time(hour=minute // 60, minute=minute % 60))
        minute += minute_step
    return grid


def _build_datetimes(
    start_date: date,
    end_date: date,
    day_step: int,
    times: list[time],
    tz: ZoneInfo,
) -> list[datetime]:
    dates = _date_range(start_date, end_date, day_step)
    datetimes = []
    for day in dates:
        for t in times:
            datetimes.append(datetime.combine(day, t, tzinfo=tz))
    return datetimes


def _load_buildings(path: pathlib.Path) -> gpd.GeoDataFrame:
    return gpd.read_parquet(path)


def _street_cluster(
    mesh,
    origin: np.ndarray,
    terrain: bool,
    half: float = 2.5,
    step: float = 1.6,
    tol: float = 1.2,
    max_points: int = 10,
) -> np.ndarray:
    """A small cluster of street-level ray origins around a relocated bar point.

    Single-point bars have no terrace geometry, so to draw a per-point sun map we
    approximate the terrace as a patch of sidewalk: sample a grid around the
    relocated street origin and keep points whose ground sits at the same street
    level (rejecting ones that fall onto a building). Returns (n, 3) ray origins
    `origin_height` (1.5 m) above ground; falls back to the single origin.
    """
    ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])
    ground0 = oz - 1.5
    xs = np.arange(ox - half, ox + half + 1e-6, step)
    ys = np.arange(oy - half, oy + half + 1e-6, step)
    cand = [(float(x), float(y)) for x in xs for y in ys]
    if terrain:
        heights = sample_ground_heights(mesh, cand, probe_radii=(0.0,))
    else:
        heights = np.zeros(len(cand))
    pts = []
    for (x, y), gz in zip(cand, heights):
        if terrain and abs(float(gz) - ground0) > tol:
            continue  # not street level (roof / different level) -> skip
        pts.append((x, y, (float(gz) if terrain else 0.0) + 1.5))
    if not pts:
        return np.array([[ox, oy, oz]], dtype=float)
    if len(pts) > max_points:
        keep = np.linspace(0, len(pts) - 1, max_points).round().astype(int)
        pts = [pts[i] for i in keep]
    return np.array(pts, dtype=float)


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
        "--start-hour",
        type=int,
        default=8,
        help="First hour of the daily time grid (default: 8).",
    )
    parser.add_argument(
        "--end-hour",
        type=int,
        default=23,
        help="Last hour of the daily time grid, inclusive (default: 23).",
    )
    parser.add_argument(
        "--minute-step",
        type=int,
        default=30,
        help="Minutes between samples within the day (default: 30 = half-hour).",
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
    # dense grid across the polygon; single-point bars approximate the terrace
    # with a street-level cluster around the relocated point. Both yield several
    # per-point origins so a per-point sun map can show which parts are lit.
    polygon_origins: list[np.ndarray | None] = []
    fallback_indices = []
    for index, (terrace_id, point) in enumerate(zip(terrace_ids, terrace_points)):
        polygon = polygons_by_id.get(terrace_id)
        if polygon is None:
            polygon_origins.append(None)
            fallback_indices.append(index)
            continue
        samples = sample_polygon_points(polygon, spacing=1.4, max_points=20)
        if mesh_includes_terrain:
            ground = sample_ground_heights(mesh, samples, probe_radii=(0.0, 3.0))
        else:
            ground = np.zeros(len(samples))
        polygon_origins.append(
            np.array([[x, y, z + 1.5] for (x, y), z in zip(samples, ground)])
        )

    relocated = estimate_terrace_origins(
        mesh,
        [terrace_points[i] for i in fallback_indices],
        terrain=mesh_includes_terrain,
    )
    fallback_clusters = [
        _street_cluster(mesh, origin, mesh_includes_terrain) for origin in relocated
    ]

    origin_rows: list[np.ndarray] = []
    origin_terrace = []
    point_idx_rows = []
    fallback_cursor = 0
    for index in range(len(terrace_ids)):
        if polygon_origins[index] is not None:
            block = polygon_origins[index]
        else:
            block = fallback_clusters[fallback_cursor]
            fallback_cursor += 1
        origin_rows.append(block)
        origin_terrace.extend([index] * len(block))
        point_idx_rows.append(np.arange(len(block)))

    origins = np.vstack(origin_rows)
    origin_terrace = np.asarray(origin_terrace)
    point_idx = np.concatenate(point_idx_rows)
    sample_counts = np.bincount(origin_terrace, minlength=len(terrace_ids))
    print(
        f"{len(polygons_by_id)} terraces use permit polygons, "
        f"{len(fallback_indices)} use street-cluster fallback; "
        f"{len(origins)} sample points total"
    )

    start_date = datetime.fromisoformat(args.start_date).date()
    end_date = datetime.fromisoformat(args.end_date).date()
    times = _time_grid(args.start_hour, args.end_hour, args.minute_step)
    datetimes = _build_datetimes(
        start_date=start_date,
        end_date=end_date,
        day_step=args.day_step,
        times=times,
        tz=HELSINKI_TZ,
    )

    n_dt, n_or = len(datetimes), len(origins)
    sun_matrix = np.zeros((n_dt, n_or), dtype=bool)  # per-datetime, per-point
    records = []
    for di, current in enumerate(datetimes):
        position = sun_position(args.latitude, args.longitude, current)
        if position.altitude_deg <= 0:
            sunny = np.zeros(n_or, dtype=bool)
        else:
            sunny = origins_in_sun(mesh, origins, position.direction).astype(bool)
        sun_matrix[di] = sunny
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

    # --- Per-point outputs for the terrace sun-map infographic ---
    out_dir = output_path.parent
    lonlat = gpd.GeoSeries(
        gpd.points_from_xy(origins[:, 0], origins[:, 1]), crs=terraces_local.crs
    ).to_crs("EPSG:4326")
    origin_terrace_ids = np.array([terrace_ids[t] for t in origin_terrace])
    points_df = pd.DataFrame(
        {
            "terrace_id": origin_terrace_ids,
            "point_idx": point_idx,
            "lon": lonlat.x.to_numpy(),
            "lat": lonlat.y.to_numpy(),
        }
    )
    points_df.to_parquet(out_dir / "terrace_points.parquet", index=False)

    point_sun = pd.DataFrame(
        {
            "terrace_id": np.tile(origin_terrace_ids, n_dt),
            "datetime": np.repeat(datetimes, n_or),
            "point_idx": np.tile(point_idx, n_dt),
            "in_sun": sun_matrix.reshape(-1),
        }
    )
    point_sun.to_parquet(out_dir / "point_shadows.parquet", index=False)
    print(
        f"Wrote {len(points_df)} sample points and {len(point_sun)} point-sun rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

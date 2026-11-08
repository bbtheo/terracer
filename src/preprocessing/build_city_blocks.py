#!/usr/bin/env python3
"""Build the footprints the app's shadow map draws.

Footprints come from the City of Helsinki WFS (full coverage of the terrace
area). Heights are measured from the same 3D mesh the sun/shade table is ray
cast against, so the map's shadows follow the geometry behind the terrace
results. Where the mesh is missing, the CityGML height is used instead.
"""

from __future__ import annotations

import argparse
import pathlib

import geopandas as gpd
import httpx
import numpy as np
import shapely
import trimesh

from src.core.mesh import _find_metadata_root, _read_origin, collect_obj_paths
from src.core.terraces import load_terraces

WFS_URL = "https://kartta.hel.fi/ws/geoserver/avoindata/wfs"
LAYER = "avoindata:Rakennukset_alue"
CRS = "EPSG:3879"
PAGE_SIZE = 5000

DEFAULT_OUTPUT = pathlib.Path("data/processed/city_blocks.parquet")
DEFAULT_CITYGML = pathlib.Path("data/processed/buildings.parquet")
DEFAULT_MESH_ROOT = pathlib.Path("data/raw/mesh")

MARGIN_M = 320  # around the terrace bbox; long evening shadows reach this far
RASTER_M = 1.5
MIN_AREA_M2 = 20.0
SIMPLIFY_M = 0.8
GROUND_RING_M = 12.0
MIN_MESH_COVERAGE = 0.6
FALLBACK_HEIGHT_M = 18.0


def map_bounds() -> tuple[float, float, float, float]:
    """The area the app's map covers, in EPSG:3879."""
    minx, miny, maxx, maxy = load_terraces().to_crs(CRS).total_bounds
    return (minx - MARGIN_M, miny - MARGIN_M, maxx + MARGIN_M, maxy + MARGIN_M)


def fetch_layer(
    layer: str, bounds: tuple[float, float, float, float], sort_by: str | None = None
) -> gpd.GeoDataFrame:
    """Download every feature of a city WFS layer intersecting `bounds`.
    Paging needs a stable order, so pass `sort_by` for layers that can exceed a page."""
    frames = []
    start = 0
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        while True:
            params = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeNames": layer,
                "outputFormat": "application/json",
                "srsName": CRS,
                "bbox": ",".join(map(str, bounds)) + f",{CRS}",
                "count": PAGE_SIZE,
                "startIndex": start,
            }
            if sort_by:
                params["sortBy"] = sort_by
            response = client.get(WFS_URL, params=params)
            response.raise_for_status()
            features = response.json().get("features", [])
            if features:
                frames.append(gpd.GeoDataFrame.from_features(features, crs=CRS))
            if len(features) < PAGE_SIZE:
                break
            start += PAGE_SIZE
    if not frames:
        raise ValueError(f"WFS returned no features for {layer}.")
    result = gpd.GeoDataFrame(gpd.pd.concat(frames, ignore_index=True), geometry="geometry", crs=CRS)
    result["geometry"] = shapely.force_2d(result.geometry.values)  # some layers carry Z
    return result


def _load_triangles(
    root: pathlib.Path, bounds: tuple[float, float, float, float], lod: str
) -> np.ndarray:
    """Triangles (n, 3, 3) of every mesh tile overlapping `bounds`."""
    x0, y0, x1, y1 = bounds
    triangles = []
    for coarse in collect_obj_paths(root, "L13"):
        origin = _read_origin(_find_metadata_root(coarse.parent) / "metadata.xml")
        tile = trimesh.load(coarse, force="mesh", process=False)
        if tile.is_empty:
            continue
        low, high = tile.bounds + origin
        if high[0] < x0 or low[0] > x1 or high[1] < y0 or low[1] > y1:
            continue
        stem = coarse.name.split("_L13")[0]
        for path in sorted(coarse.parent.glob(f"{stem}_{lod}*.obj")) or [coarse]:
            mesh = trimesh.load(path, force="mesh", process=False)
            if not mesh.is_empty:
                triangles.append(mesh.vertices[mesh.faces] + origin)
    if not triangles:
        raise ValueError(f"No mesh tiles overlap {bounds} under {root}.")
    return np.concatenate(triangles)


def rasterize_surface(
    triangles: np.ndarray, bounds: tuple[float, float, float, float], cell: float
) -> np.ndarray:
    """Highest surface per grid cell; NaN where the mesh has no coverage."""
    x0, y0, x1, y1 = bounds
    width = int((x1 - x0) / cell) + 1
    height = int((y1 - y0) / cell) + 1
    surface = np.full((height, width), -np.inf)
    xs = (triangles[:, :, 0] - x0) / cell
    ys = (triangles[:, :, 1] - y0) / cell
    zs = triangles[:, :, 2]

    for x, y, z in zip(xs, ys, zs):
        left, right = int(max(np.floor(x.min()), 0)), int(min(np.ceil(x.max()), width - 1))
        low, high = int(max(np.floor(y.min()), 0)), int(min(np.ceil(y.max()), height - 1))
        if left > right or low > high:
            continue
        area = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(area) < 1e-9:
            continue
        grid_x, grid_y = np.meshgrid(np.arange(left, right + 1), np.arange(low, high + 1))
        w0 = ((y[1] - y[2]) * (grid_x - x[2]) + (x[2] - x[1]) * (grid_y - y[2])) / area
        w1 = ((y[2] - y[0]) * (grid_x - x[2]) + (x[0] - x[2]) * (grid_y - y[2])) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= -0.02) & (w1 >= -0.02) & (w2 >= -0.02)
        if inside.any():
            window = surface[low : high + 1, left : right + 1]
            window[inside] = np.maximum(window[inside], (w0 * z[0] + w1 * z[1] + w2 * z[2])[inside])

    surface[np.isinf(surface)] = np.nan
    return surface


def _cells_in(
    geometry, surface: np.ndarray, bounds: tuple[float, float, float, float], cell: float
) -> np.ndarray:
    """Surface heights of the grid cells inside `geometry` (NaN where uncovered)."""
    x0, y0, _, _ = bounds
    minx, miny, maxx, maxy = geometry.bounds
    left, right = max(int((minx - x0) / cell), 0), min(int((maxx - x0) / cell) + 1, surface.shape[1] - 1)
    low, high = max(int((miny - y0) / cell), 0), min(int((maxy - y0) / cell) + 1, surface.shape[0] - 1)
    if left > right or low > high:
        return np.empty(0)
    grid_x, grid_y = np.meshgrid(np.arange(left, right + 1), np.arange(low, high + 1))
    mask = shapely.contains_xy(geometry, x0 + grid_x * cell, y0 + grid_y * cell)
    return surface[low : high + 1, left : right + 1][mask]


def measure_height(
    geometry, surface: np.ndarray, bounds: tuple[float, float, float, float], cell: float
) -> float | None:
    """Roof height above the surrounding street, or None if the mesh can't tell."""
    roof = _cells_in(geometry, surface, bounds, cell)
    if roof.size == 0 or np.isfinite(roof).mean() < MIN_MESH_COVERAGE:
        return None
    ring = _cells_in(geometry.buffer(GROUND_RING_M).difference(geometry), surface, bounds, cell)
    ring = ring[np.isfinite(ring)]
    if ring.size == 0:
        return None
    # The 85th percentile ignores chimneys; the ring's low end is street level.
    return float(np.nanpercentile(roof, 85) - np.percentile(ring, 10))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build shadow-map building footprints.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--citygml", default=str(DEFAULT_CITYGML))
    parser.add_argument("--mesh-root", default=str(DEFAULT_MESH_ROOT))
    parser.add_argument("--mesh-lod", default="L15")
    args = parser.parse_args()

    bounds = map_bounds()

    print("Downloading footprints")
    footprints = fetch_layer(LAYER, bounds, sort_by="id")[["geometry"]].explode(ignore_index=True)
    footprints = footprints[footprints.area >= MIN_AREA_M2].reset_index(drop=True)
    print(f"{len(footprints)} footprints")

    print(f"Rasterizing mesh ({args.mesh_lod})")
    surface = rasterize_surface(
        _load_triangles(pathlib.Path(args.mesh_root), bounds, args.mesh_lod), bounds, RASTER_M
    )

    citygml = gpd.read_parquet(args.citygml).to_crs(CRS)
    citygml_height = (citygml["height_max"] - citygml["height_min"]).clip(lower=0)
    citygml_index = citygml.sindex

    heights = []
    measured = 0
    for geometry in footprints.geometry:
        height = measure_height(geometry, surface, bounds, RASTER_M)
        if height is not None:
            measured += 1
        else:
            hits = citygml_index.query(geometry.representative_point(), predicate="intersects")
            height = float(citygml_height.iloc[hits[0]]) if len(hits) else FALLBACK_HEIGHT_M
        heights.append(round(max(height, 3.0), 1))

    result = gpd.GeoDataFrame(
        {"height": heights},
        geometry=footprints.geometry.simplify(SIMPLIFY_M, preserve_topology=True),
        crs=CRS,
    )
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output)
    print(f"Wrote {output}: {len(result)} blocks, {measured} heights measured from the mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

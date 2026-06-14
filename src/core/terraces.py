#!/usr/bin/env python3
from __future__ import annotations

import pathlib

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import Point


DEFAULT_TERRACES_PATH = pathlib.Path("data/terraces.geojson")


def load_terraces(path: pathlib.Path | str = DEFAULT_TERRACES_PATH) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf


def terraces_to_local_crs(
    terraces: gpd.GeoDataFrame, target_crs: str = "EPSG:3879"
) -> gpd.GeoDataFrame:
    if terraces.crs is None:
        terraces = terraces.set_crs("EPSG:4326")
    return terraces.to_crs(target_crs)


def sample_polygon_points(
    polygon: shapely.geometry.base.BaseGeometry,
    spacing: float = 2.0,
    max_points: int = 16,
) -> list[tuple[float, float]]:
    """Sample (x, y) points covering a terrace polygon on a regular grid.

    Always returns at least one point (the representative point for slivers
    smaller than the grid spacing). The grid is subsampled evenly if it
    exceeds max_points.
    """
    min_x, min_y, max_x, max_y = polygon.bounds
    xs = np.arange(min_x + spacing / 2.0, max_x, spacing)
    ys = np.arange(min_y + spacing / 2.0, max_y, spacing)
    points = [
        (float(x), float(y))
        for x in xs
        for y in ys
        if polygon.contains(Point(x, y))
    ]
    if not points:
        rep = polygon.representative_point()
        return [(float(rep.x), float(rep.y))]
    if len(points) > max_points:
        stride = np.linspace(0, len(points) - 1, max_points).round().astype(int)
        points = [points[i] for i in stride]
    return points

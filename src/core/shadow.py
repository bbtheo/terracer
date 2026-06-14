#!/usr/bin/env python3
from __future__ import annotations

from typing import Iterable

import geopandas as gpd
import numpy as np
import shapely
import trimesh


def _extrude_building(
    geometry: shapely.geometry.base.BaseGeometry, height: float
) -> trimesh.Trimesh | None:
    if geometry.is_empty or height <= 0:
        return None
    if geometry.geom_type == "MultiPolygon":
        polygons = list(geometry.geoms)
    elif geometry.geom_type == "Polygon":
        polygons = [geometry]
    else:
        return None

    meshes = []
    for polygon in polygons:
        try:
            # Proper polygon triangulation: respects concave footprints and
            # interior rings, unlike a Delaunay over the vertices.
            mesh = trimesh.creation.extrude_polygon(polygon, height)
        except (ValueError, IndexError):
            continue
        if mesh is not None and not mesh.is_empty:
            meshes.append(mesh)
    if not meshes:
        return None
    return trimesh.util.concatenate(meshes)


def build_building_mesh(
    buildings: gpd.GeoDataFrame,
    default_height: float = 12.0,
) -> trimesh.Trimesh:
    """Extrude building footprints into a single occluder mesh.

    All buildings are extruded from z=0, i.e. the mesh lives in a
    "local ground = 0" frame. Ray origins for this mesh must therefore
    use ground height 0 (see terrace_in_sun).
    """
    meshes: list[trimesh.Trimesh] = []
    for _, row in buildings.iterrows():
        height_min = row.get("height_min")
        height_max = row.get("height_max")
        height = None
        if height_min is not None and height_max is not None:
            height = float(height_max) - float(height_min)
        if height is None or not np.isfinite(height) or height <= 0:
            height = default_height

        mesh = _extrude_building(row.geometry, height)
        if mesh is None:
            continue
        meshes.append(mesh)

    if not meshes:
        raise ValueError("No building meshes could be created from input geometries.")

    return trimesh.util.concatenate(meshes)


def sample_ground_heights(
    mesh: trimesh.Trimesh,
    points: Iterable[tuple[float, float]],
    probe_radii: tuple[float, ...] = (0.0, 4.0, 8.0, 12.0),
    n_angles: int = 8,
) -> np.ndarray:
    """Estimate the street-level elevation of `mesh` at each (x, y) point.

    Terrace points often geocode to the building address, which lies inside
    the building "bump" of the photogrammetric surface mesh — a single
    vertical ray there returns the roof, not the street. So each point is
    probed with downward rays at the point itself plus rings around it, and
    the lowest surface hit is taken as ground (streets are lower than roofs).
    Points with no hits at all (outside tile coverage) fall back to the
    median of the other points' heights.
    """
    points = list(points)
    if not points:
        return np.empty(0, dtype=float)

    angles = np.linspace(0.0, 2.0 * np.pi, n_angles, endpoint=False)
    probes: list[tuple[float, float]] = []
    probe_point_index: list[int] = []
    for point_index, (x, y) in enumerate(points):
        for radius in probe_radii:
            if radius == 0.0:
                probes.append((x, y))
                probe_point_index.append(point_index)
                continue
            for angle in angles:
                probes.append((x + radius * np.cos(angle), y + radius * np.sin(angle)))
                probe_point_index.append(point_index)

    top = float(mesh.bounds[1][2]) + 10.0
    origins = np.array([[px, py, top] for px, py in probes], dtype=float)
    directions = np.tile([0.0, 0.0, -1.0], (len(origins), 1))

    locations, ray_indices, _ = mesh.ray.intersects_location(
        origins, directions, multiple_hits=False
    )

    heights = np.full(len(points), np.nan, dtype=float)
    for location, ray_index in zip(locations, ray_indices, strict=True):
        point_index = probe_point_index[int(ray_index)]
        z = float(location[2])
        if np.isnan(heights[point_index]) or z < heights[point_index]:
            heights[point_index] = z

    if np.isnan(heights).any():
        fallback = float(np.nanmedian(heights)) if not np.isnan(heights).all() else 0.0
        heights = np.where(np.isnan(heights), fallback, heights)
    return heights


def estimate_terrace_origins(
    mesh: trimesh.Trimesh,
    points: Iterable[tuple[float, float]],
    origin_height: float = 1.5,
    terrain: bool = True,
    probe_radii: tuple[float, ...] = (0.0, 4.0, 8.0, 12.0, 16.0, 20.0),
    n_angles: int = 8,
    street_tolerance: float = 1.5,
) -> np.ndarray:
    """Build ray origins for terrace points, relocating points stuck inside buildings.

    POI coordinates (e.g. from OSM) usually sit inside the building footprint.
    In the photogrammetric city mesh the surface there is the roof, so a ray
    cast from that xy starts inside the building volume and always reports
    shade. Each point is probed with downward rays (centre + rings); ground is
    the lowest hit, and if the centre probe lands well above ground the origin
    is moved to the nearest street-level probe — i.e. the sidewalk in front of
    the bar. With terrain=False (extruded-buildings mesh in a ground=0 frame)
    "street level" means no hit at all.

    Returns an (n, 3) array of ray origins, origin_height metres above ground.
    """
    points = list(points)
    if not points:
        return np.empty((0, 3), dtype=float)

    angles = np.linspace(0.0, 2.0 * np.pi, n_angles, endpoint=False)
    offsets = [(0.0, 0.0)] + [
        (radius * np.cos(angle), radius * np.sin(angle))
        for radius in probe_radii
        if radius > 0.0
        for angle in angles
    ]
    probes = np.array(
        [[x + dx, y + dy] for x, y in points for dx, dy in offsets], dtype=float
    )
    per_point = len(offsets)

    top = float(mesh.bounds[1][2]) + 10.0
    origins = np.column_stack([probes, np.full(len(probes), top)])
    directions = np.tile([0.0, 0.0, -1.0], (len(probes), 1))
    locations, ray_indices, _ = mesh.ray.intersects_location(
        origins, directions, multiple_hits=False
    )

    surface = np.full(len(probes), np.nan, dtype=float)
    if len(locations):
        surface[ray_indices.astype(int)] = locations[:, 2]

    result = np.empty((len(points), 3), dtype=float)
    for point_index, (x, y) in enumerate(points):
        zs = surface[point_index * per_point : (point_index + 1) * per_point]
        if terrain:
            hits = zs[~np.isnan(zs)]
            ground = float(hits.min()) if len(hits) else 0.0
            street_like = ~np.isnan(zs) & (zs <= ground + street_tolerance)
        else:
            ground = 0.0
            street_like = np.isnan(zs)

        if street_like[0]:
            chosen = 0
        else:
            # offsets are ordered by ring radius, so the first street-like
            # probe is the closest one.
            candidates = np.flatnonzero(street_like)
            chosen = int(candidates[0]) if len(candidates) else 0

        dx, dy = offsets[chosen]
        result[point_index] = (x + dx, y + dy, ground + origin_height)
    return result


def origins_in_sun(
    mesh: trimesh.Trimesh,
    origins: np.ndarray,
    direction: np.ndarray,
    standoff: float = 2.0,
) -> np.ndarray:
    """True where the ray from each origin toward the sun is unobstructed."""
    shifted = origins + direction.reshape(1, 3) * standoff
    return ~ray_occluded(mesh, shifted, direction)


def ray_occluded(
    mesh: trimesh.Trimesh,
    origins: np.ndarray,
    direction: np.ndarray,
) -> np.ndarray:
    directions = np.repeat(direction.reshape(1, 3), len(origins), axis=0)
    return mesh.ray.intersects_any(origins, directions)


def terrace_in_sun(
    mesh: trimesh.Trimesh,
    points: Iterable[tuple[float, float]],
    direction: np.ndarray,
    ground_heights: np.ndarray | None = None,
    origin_height: float = 1.5,
    standoff: float = 2.0,
) -> np.ndarray:
    """Return a boolean array: True where the ray toward the sun is unobstructed.

    `ground_heights` gives the terrain elevation at each point (same order);
    ray origins are placed `origin_height` metres above it. Omit it only for
    meshes built in a ground=0 frame (build_building_mesh). `standoff` moves
    each origin along the ray so that a slightly-too-low ground estimate
    cannot make the ray graze the terrain skin right at its start.
    """
    points = list(points)
    if ground_heights is None:
        ground_heights = np.zeros(len(points), dtype=float)
    origins = np.array(
        [[x, y, float(z) + origin_height] for (x, y), z in zip(points, ground_heights, strict=True)],
        dtype=float,
    )
    return origins_in_sun(mesh, origins, direction, standoff=standoff)

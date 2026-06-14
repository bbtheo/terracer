from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import shapely
import trimesh
from shapely.geometry import Polygon

from src.core.mesh import collect_obj_paths
from src.core.shadow import (
    build_building_mesh,
    estimate_terrace_origins,
    origins_in_sun,
    sample_ground_heights,
    terrace_in_sun,
)
from src.core.sun import sun_position

import geopandas as gpd

HELSINKI = (60.1695, 24.9417)
TZ = ZoneInfo("Europe/Helsinki")


def test_noon_sun_is_in_the_south():
    # At solar noon in Helsinki the sun is due south: the direction vector
    # (x=east, y=north, z=up) must point south (negative y) and up.
    pos = sun_position(*HELSINKI, datetime(2024, 6, 21, 13, 20, tzinfo=TZ))
    assert 170 < pos.azimuth_deg < 190
    x, y, z = pos.direction
    assert y < -0.5
    assert abs(x) < 0.3
    assert z > 0.5


def test_morning_sun_is_in_the_east():
    pos = sun_position(*HELSINKI, datetime(2024, 6, 21, 8, 0, tzinfo=TZ))
    x, y, z = pos.direction
    assert x > 0.5  # east
    assert z > 0


def test_collect_obj_paths_matches_tile_names(tmp_path):
    (tmp_path / "Tile_+017_+000_L13.obj").touch()
    (tmp_path / "Tile_+017_+000_L14_0.obj").touch()
    (tmp_path / "Tile_+017_+000_L15_00.obj").touch()
    assert [p.name for p in collect_obj_paths(tmp_path, "L13")] == [
        "Tile_+017_+000_L13.obj"
    ]
    assert [p.name for p in collect_obj_paths(tmp_path, "L14")] == [
        "Tile_+017_+000_L14_0.obj"
    ]


def _wall_mesh():
    # A 20 m tall wall along the x (east) axis, 1 m thick, centred at y=0.
    footprint = Polygon([(-10, -0.5), (10, -0.5), (10, 0.5), (-10, 0.5)])
    gdf = gpd.GeoDataFrame(
        {"height_min": [0.0], "height_max": [20.0]}, geometry=[footprint]
    )
    return build_building_mesh(gdf)


def test_wall_shades_point_opposite_the_sun():
    mesh = _wall_mesh()
    # Sun low in the south: a point just north of the wall is shaded,
    # a point south of the wall is in sun.
    sun_from_south = np.array([0.0, -np.cos(np.deg2rad(20)), np.sin(np.deg2rad(20))])
    north_point, south_point = (0.0, 5.0), (0.0, -5.0)
    result = terrace_in_sun(mesh, [north_point, south_point], sun_from_south)
    assert not result[0]
    assert result[1]


def test_high_sun_clears_the_wall():
    mesh = _wall_mesh()
    sun_steep = np.array([0.0, -np.cos(np.deg2rad(80)), np.sin(np.deg2rad(80))])
    result = terrace_in_sun(mesh, [(0.0, 5.0)], sun_steep)
    assert result[0]


def test_concave_footprint_does_not_overshadow():
    # L-shaped building; a point inside the concave notch with the sun
    # directly overhead-ish from the open side must be in sun. The old
    # Delaunay triangulation filled the notch with phantom roof.
    footprint = Polygon([(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)])
    gdf = gpd.GeoDataFrame(
        {"height_min": [0.0], "height_max": [10.0]}, geometry=[footprint]
    )
    mesh = build_building_mesh(gdf)
    straight_up = np.array([0.0, 0.0, 1.0])
    result = terrace_in_sun(mesh, [(7.0, 7.0)], straight_up)
    assert result[0]


def test_sample_ground_heights_on_box():
    box = trimesh.creation.box(bounds=[[-5, -5, 0], [5, 5, 3]])
    heights = sample_ground_heights(box, [(0.0, 0.0)])
    assert np.isclose(heights[0], 3.0)


def _city_scene():
    # Flat ground with one 20 m building in the middle, like a mesh tile.
    ground = trimesh.creation.box(bounds=[[-50, -50, -1], [50, 50, 0]])
    building = trimesh.creation.box(bounds=[[-5, -5, 0], [5, 5, 20]])
    return trimesh.util.concatenate([ground, building])


def test_point_inside_building_is_relocated_to_street():
    # A POI geocoded inside the building footprint must not read as
    # permanently shaded: its ray origin moves to the nearest street spot.
    mesh = _city_scene()
    origins = estimate_terrace_origins(mesh, [(0.0, 0.0)])
    x, y, z = origins[0]
    assert np.hypot(x, y) > 5.0  # outside the footprint
    assert np.isclose(z, 1.5, atol=0.1)  # street level + origin height
    straight_up = np.array([0.0, 0.0, 1.0])
    assert origins_in_sun(mesh, origins, straight_up)[0]


def test_sample_polygon_points_covers_polygon():
    from src.core.terraces import sample_polygon_points

    terrace = Polygon([(0, 0), (8, 0), (8, 4), (0, 4)])
    points = sample_polygon_points(terrace, spacing=2.0, max_points=16)
    assert 4 <= len(points) <= 16
    assert all(terrace.contains(shapely.geometry.Point(x, y)) for x, y in points)

    sliver = Polygon([(0, 0), (0.5, 0), (0.5, 0.5), (0, 0.5)])
    assert len(sample_polygon_points(sliver, spacing=2.0)) == 1


def test_point_on_street_is_not_relocated():
    mesh = _city_scene()
    origins = estimate_terrace_origins(mesh, [(20.0, 20.0)])
    assert np.allclose(origins[0], [20.0, 20.0, 1.5], atol=0.1)

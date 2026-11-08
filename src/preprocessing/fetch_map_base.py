#!/usr/bin/env python3
"""Fetch the streets and water the app's map draws under the buildings."""

from __future__ import annotations

import argparse
import pathlib

import geopandas as gpd
import shapely
from shapely.geometry import box

from src.preprocessing.build_city_blocks import CRS, fetch_layer, map_bounds

ROADS_LAYER = "avoindata:Liikennevaylat"
SEA_LAYER = "avoindata:Maavesi_merialue"
INLAND_WATER_LAYER = "avoindata:Maavesi_muut_vesialueet"

DEFAULT_ROADS = pathlib.Path("data/processed/map_roads.parquet")
DEFAULT_WATER = pathlib.Path("data/processed/map_water.parquet")

# Drawn width in metres by street type. Sidewalks, crossings and cycle lanes
# are left out: they run alongside the streets and only add noise at map scale.
ROAD_WIDTH_M = {
    "Päätie": 13,
    "Alueellinen kokoojakatu": 13,
    "Paikallinen kokoojakatu": 8,
    "Asuntokatu": 8,
    "Tonttikatu": 8,
    "Puistotie- tai väylä": 3,
    "Piha- ja/tai kävelykatu": 3,
    "Kulkuväylä aukiolla": 3,
}
TUNNEL = "Alikulku, tunneli"
SIMPLIFY_ROAD_M = 1.0
SIMPLIFY_WATER_M = 1.5
MIN_WATER_AREA_M2 = 50.0


def build_roads(raw: gpd.GeoDataFrame, area) -> gpd.GeoDataFrame:
    """One merged, clipped line set per drawn width."""
    roads = raw[raw["alatyyppi"].isin(ROAD_WIDTH_M) & (raw["silta_alikulku"] != TUNNEL)]
    widths = roads["alatyyppi"].map(ROAD_WIDTH_M)
    rows = []
    for width, group in roads.groupby(widths):
        merged = shapely.line_merge(shapely.union_all(group.geometry.values))
        clipped = merged.intersection(area).simplify(SIMPLIFY_ROAD_M)
        for line in getattr(clipped, "geoms", [clipped]):
            if line.geom_type == "LineString" and not line.is_empty:
                rows.append({"width": int(width), "geometry": line})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=CRS)


def build_water(layers: list[gpd.GeoDataFrame], area) -> gpd.GeoDataFrame:
    """Sea and inland water as clipped polygons."""
    shapes = [geom for layer in layers for geom in layer.geometry]
    water = shapely.union_all(shapes).intersection(area).simplify(SIMPLIFY_WATER_M)
    parts = [p for p in getattr(water, "geoms", [water]) if p.geom_type == "Polygon" and p.area >= MIN_WATER_AREA_M2]
    return gpd.GeoDataFrame(geometry=parts, crs=CRS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch map streets and water.")
    parser.add_argument("--roads", default=str(DEFAULT_ROADS))
    parser.add_argument("--water", default=str(DEFAULT_WATER))
    args = parser.parse_args()

    bounds = map_bounds()
    area = box(*bounds)
    roads = build_roads(fetch_layer(ROADS_LAYER, bounds, sort_by="id"), area)
    water = build_water([fetch_layer(SEA_LAYER, bounds), fetch_layer(INLAND_WATER_LAYER, bounds)], area)

    pathlib.Path(args.roads).parent.mkdir(parents=True, exist_ok=True)
    roads.to_parquet(args.roads)
    water.to_parquet(args.water)
    print(f"Wrote {len(roads)} road lines to {args.roads} and {len(water)} water areas to {args.water}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

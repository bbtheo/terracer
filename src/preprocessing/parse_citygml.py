#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Iterable, Optional

import geopandas as gpd
from lxml import etree
from shapely.geometry import Polygon


DEFAULT_INPUT_DIR = pathlib.Path("data/raw")
DEFAULT_OUTPUT_PATH = pathlib.Path("data/processed/buildings.parquet")


def _parse_pos_list(text: str) -> tuple[list[tuple[float, float]], list[float]]:
    values = [float(value) for value in text.split() if value.strip()]
    if len(values) % 3 == 0:
        coords = list(zip(values[0::3], values[1::3]))
        zs = values[2::3]
    elif len(values) % 2 == 0:
        coords = list(zip(values[0::2], values[1::2]))
        zs = []
    else:
        return [], []
    return coords, zs


def _polygon_from_poslist(poslists: Iterable[str]) -> tuple[Optional[Polygon], list[float]]:
    for poslist in poslists:
        coords, zs = _parse_pos_list(poslist)
        if len(coords) < 3:
            continue
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        polygon = Polygon(coords)
        if polygon.is_valid and not polygon.is_empty:
            return polygon, zs
    return None, []


def _extract_buildings(file_path: pathlib.Path, max_buildings: Optional[int]) -> list[dict]:
    buildings = []
    count = 0

    context = etree.iterparse(str(file_path), events=("end",), recover=True)
    for _, element in context:
        if etree.QName(element).localname != "Building":
            continue

        if max_buildings is not None and count >= max_buildings:
            element.clear()
            break

        all_poslists = element.xpath(".//*[local-name()='posList']/text()")

        ground_surfaces = element.xpath(".//*[local-name()='GroundSurface']")
        poslists = []
        for surface in ground_surfaces:
            poslists.extend(surface.xpath(".//*[local-name()='posList']/text()"))

        if not poslists:
            poslists = all_poslists

        polygon, _ = _polygon_from_poslist(poslists)
        if polygon is None:
            element.clear()
            continue

        # Height range must span the whole building (walls + roof), not just
        # the ground surface used for the footprint.
        zs: list[float] = []
        for poslist in all_poslists:
            _, surface_zs = _parse_pos_list(poslist)
            zs.extend(surface_zs)

        building_id = element.get("{http://www.opengis.net/gml}id") or f"building_{count}"
        height_min = min(zs) if zs else None
        height_max = max(zs) if zs else None

        buildings.append(
            {
                "building_id": building_id,
                "height_min": height_min,
                "height_max": height_max,
                "geometry": polygon,
            }
        )
        count += 1
        element.clear()

    del context
    return buildings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse CityGML files into simplified building footprints.",
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_DIR),
        help="Directory containing CityGML files (default: data/raw).",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Parquet output path (default: data/processed/buildings.parquet).",
    )
    parser.add_argument(
        "--max-buildings",
        type=int,
        help="Optional cap on buildings parsed (for quick runs).",
    )
    args = parser.parse_args()

    input_dir = pathlib.Path(args.input)
    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    citygml_files = [
        path
        for path in input_dir.rglob("*")
        if path.suffix.lower() in {".gml", ".xml"}
    ]
    if not citygml_files:
        print(
            f"No CityGML files found in {input_dir.resolve()}",
            file=sys.stderr,
        )
        return 2

    records = []
    for file_path in citygml_files:
        records.extend(_extract_buildings(file_path, args.max_buildings))
        if args.max_buildings is not None and len(records) >= args.max_buildings:
            records = records[: args.max_buildings]
            break

    if not records:
        print("No buildings extracted from CityGML files.", file=sys.stderr)
        return 3

    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:3879")
    gdf.to_parquet(output_path, index=False)
    print(f"Wrote {len(gdf)} buildings to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

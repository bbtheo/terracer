#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import re
import ssl
from dataclasses import dataclass
from typing import Iterable

import geopandas as gpd
import httpx


MAPPING_URL = (
    "http://www.hel.fi/hel2/tietokeskus/data/helsinki/kaupunginkanslia/3D-malli/"
    "Helsinki_Mesh_2017_CorrespondingNames.txt"
)
TILE_BASE_URL = (
    "https://3d.hel.ninja/data/mesh/"
    "Helsinki3D-MESH_2017_OBJ_2km-250m_ZIP"
)


@dataclass(frozen=True)
class MeshOrigin:
    x: float
    y: float


DEFAULT_ORIGIN = MeshOrigin(25490000.0, 6668000.0)


def _fetch_mapping(path: pathlib.Path) -> dict[str, str]:
    if not path.exists():
        context = ssl._create_unverified_context()
        with httpx.Client(verify=False, follow_redirects=True) as client:
            response = client.get(MAPPING_URL, timeout=30.0)
            response.raise_for_status()
            path.write_text(response.text, encoding="utf-8")

    mapping: dict[str, str] = {}
    pattern = re.compile(r"^(\S+)\s+Tile_(\+\d+_\+\d+)\s+(\d+x2)$")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        tile_name = f"Tile_{match.group(2)}"
        mapping[tile_name] = match.group(3)
    return mapping


def _load_terraces(path: pathlib.Path) -> gpd.GeoDataFrame:
    terraces = gpd.read_file(path)
    if terraces.crs is None:
        terraces = terraces.set_crs("EPSG:4326")
    return terraces.to_crs("EPSG:3879")


def _tile_labels(
    x: float, y: float, origin: MeshOrigin, tile_size: float = 250.0
) -> tuple[int, int]:
    local_x = x - origin.x
    local_y = y - origin.y
    x_label = int(local_x // tile_size) + 7
    y_label = int(local_y // tile_size) + 1
    return x_label, y_label


def _tile_name(x_label: int, y_label: int) -> str:
    return f"Tile_+{x_label:03d}_+{y_label:03d}"


def _unique_tiles(
    terraces: gpd.GeoDataFrame, origin: MeshOrigin
) -> set[str]:
    tiles: set[str] = set()
    for geom in terraces.geometry:
        if geom is None or geom.is_empty:
            continue
        x_label, y_label = _tile_labels(geom.x, geom.y, origin)
        tiles.add(_tile_name(x_label, y_label))
    return tiles


def _download_tiles(
    tiles: Iterable[str],
    mapping: dict[str, str],
    output_dir: pathlib.Path,
    insecure: bool,
) -> list[pathlib.Path]:
    downloaded = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for tile_name in tiles:
        tile_code = mapping.get(tile_name)
        if tile_code is None:
            print(f"Tile {tile_name} not found in mapping file.")
            continue
        zip_name = f"Helsinki3D_2017_OBJ_{tile_code}.zip"
        url = f"{TILE_BASE_URL}/{zip_name}"
        target = output_dir / zip_name
        if target.exists():
            downloaded.append(target)
            continue
        with httpx.Client(verify=not insecure, follow_redirects=True) as client:
            response = client.get(url, timeout=60.0)
            response.raise_for_status()
            target.write_bytes(response.content)
        downloaded.append(target)
    return downloaded


def _unzip_archives(archives: Iterable[pathlib.Path], output_dir: pathlib.Path) -> None:
    import zipfile

    for archive in archives:
        target_dir = output_dir / archive.stem
        if target_dir.exists() and any(target_dir.iterdir()):
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "r") as zip_handle:
            zip_handle.extractall(target_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Helsinki 3D mesh tiles covering the terrace points.",
    )
    parser.add_argument(
        "--terraces",
        default="data/terraces.geojson",
        help="Path to terraces GeoJSON (default: data/terraces.geojson).",
    )
    parser.add_argument(
        "--output",
        default="data/raw/mesh",
        help="Directory to store mesh tiles (default: data/raw/mesh).",
    )
    parser.add_argument(
        "--mapping",
        default="data/raw/mesh/mesh_tile_map.txt",
        help="Path to cache the mesh mapping file.",
    )
    parser.add_argument(
        "--origin-x",
        type=float,
        default=DEFAULT_ORIGIN.x,
        help="Mesh origin easting (default: 25490000).",
    )
    parser.add_argument(
        "--origin-y",
        type=float,
        default=DEFAULT_ORIGIN.y,
        help="Mesh origin northing (default: 6668000).",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verification for mesh downloads (host cert is expired).",
    )
    parser.add_argument(
        "--skip-unzip",
        action="store_true",
        help="Skip unzipping downloaded archives.",
    )
    args = parser.parse_args()

    output_dir = pathlib.Path(args.output)
    mapping_path = pathlib.Path(args.mapping)

    mapping = _fetch_mapping(mapping_path)
    terraces = _load_terraces(pathlib.Path(args.terraces))
    origin = MeshOrigin(args.origin_x, args.origin_y)
    tiles = _unique_tiles(terraces, origin)

    archives = _download_tiles(tiles, mapping, output_dir, insecure=args.insecure)
    if not args.skip_unzip:
        _unzip_archives(archives, output_dir)
    print(f"Prepared {len(archives)} mesh tile archives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

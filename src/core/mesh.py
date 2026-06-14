#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import re
from typing import Iterable

import numpy as np
import trimesh
from lxml import etree


def _find_metadata_root(path: pathlib.Path) -> pathlib.Path | None:
    for parent in [path] + list(path.parents):
        if (parent / "metadata.xml").exists():
            return parent
    return None


def _read_origin(metadata_path: pathlib.Path) -> np.ndarray:
    tree = etree.parse(str(metadata_path))
    origin_text = tree.findtext(".//SRSOrigin")
    if not origin_text:
        raise ValueError(f"Missing SRSOrigin in {metadata_path}")
    parts = [float(value.strip()) for value in origin_text.split(",")]
    if len(parts) < 3:
        raise ValueError(f"Invalid SRSOrigin in {metadata_path}")
    return np.array(parts[:3], dtype=float)


def collect_obj_paths(root: pathlib.Path, lod: str) -> list[pathlib.Path]:
    # Tile names look like Tile_+017_+000_L13.obj or Tile_+017_+000_L14_0.obj
    # (higher LODs are split into numbered sub-tiles).
    pattern = re.compile(rf"_{re.escape(lod)}(_\d+)?\.obj$", re.IGNORECASE)
    return [path for path in root.rglob("*.obj") if pattern.search(path.name)]


def load_mesh_from_objs(obj_paths: Iterable[pathlib.Path]) -> trimesh.Trimesh:
    meshes: list[trimesh.Trimesh] = []
    for obj_path in obj_paths:
        mesh_root = _find_metadata_root(obj_path.parent)
        if mesh_root is None:
            continue
        origin = _read_origin(mesh_root / "metadata.xml")

        # force='mesh' flattens OBJ files that load as multi-object scenes.
        mesh = trimesh.load(obj_path, force="mesh", process=False)
        if mesh.is_empty:
            continue
        mesh.apply_translation(origin)
        meshes.append(mesh)

    if not meshes:
        raise ValueError("No mesh geometry loaded from OBJ files.")

    return trimesh.util.concatenate(meshes)

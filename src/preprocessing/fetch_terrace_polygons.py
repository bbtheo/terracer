#!/usr/bin/env python3
"""Fetch summer-terrace permit polygons and match them to the terrace list.

The City of Helsinki publishes short-term land rental permits (including
"Kesäterassi" summer terraces) as WFS polygons. Each permit carries the
establishment name ("Terassialue: <name>"), so polygons can be matched to
the bars in data/terraces.geojson by name similarity plus proximity.

Only terraces on rented public land appear in the permit data; unmatched
bars keep the point-based fallback in compute_shadows.
"""
from __future__ import annotations

import argparse
import difflib
import json
import pathlib
import re
import unicodedata

import geopandas as gpd
import httpx
from shapely.geometry import shape

from src.core.terraces import load_terraces


WFS_URL = "https://kartta.hel.fi/ws/geoserver/avoindata/wfs"
LAYER = "avoindata:Lyhyt_maanvuokraus_alue"
DEFAULT_TERRACES_PATH = pathlib.Path("data/terraces.geojson")
DEFAULT_OUTPUT_PATH = pathlib.Path("data/terrace_polygons.geojson")

MAX_MATCH_DISTANCE_M = 60.0
MIN_NAME_SIMILARITY = 0.55


def _normalize(name: str) -> str:
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    norm = norm.lower()
    norm = re.sub(r"\b(terassialue|ravintola|bar|baari|pub|cafe|kahvila)\b", " ", norm)
    return re.sub(r"[^a-z0-9]+", " ", norm).strip()


def _name_similarity(a: str, b: str) -> float:
    a, b = _normalize(a), _normalize(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def fetch_terrace_permits(district: str | None) -> gpd.GeoDataFrame:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": LAYER,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "count": "5000",
        "cql_filter": "hakemuksen_laji='Kesäterassi'",
    }
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(WFS_URL, params=params)
        response.raise_for_status()
        collection = response.json()

    records = []
    for feature in collection.get("features", []):
        props = feature.get("properties", {})
        geometry = feature.get("geometry")
        if geometry is None:
            continue
        if district and district.lower() not in (props.get("kaupunginosa") or "").lower():
            continue
        name = (props.get("nimi") or "").removeprefix("Terassialue:").strip()
        records.append(
            {
                "permit_id": props.get("hakemustunnus"),
                "permit_name": name,
                "address": props.get("osoite"),
                "status": props.get("status"),
                "rental_ends": props.get("vuokraus_paattyy"),
                "geometry": shape(geometry),
            }
        )
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def match_to_terraces(
    permits: gpd.GeoDataFrame, terraces: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    permits_local = permits.to_crs("EPSG:3879")
    terraces_local = terraces.to_crs("EPSG:3879")

    matches = []
    for _, bar in terraces_local.iterrows():
        best = None
        for permit_index, permit in permits_local.iterrows():
            distance = float(bar.geometry.distance(permit.geometry))
            if distance > MAX_MATCH_DISTANCE_M:
                continue
            similarity = _name_similarity(bar["name"], permit["permit_name"] or "")
            if similarity < MIN_NAME_SIMILARITY:
                continue
            score = similarity - distance / 1000.0
            if best is None or score > best[0]:
                best = (score, permit_index, distance, similarity)
        if best is not None:
            _, permit_index, distance, similarity = best
            matches.append(
                {
                    "terrace_id": bar["id"],
                    "bar_name": bar["name"],
                    "permit_name": permits.loc[permit_index, "permit_name"],
                    "permit_id": permits.loc[permit_index, "permit_id"],
                    "distance_m": round(distance, 1),
                    "similarity": round(similarity, 2),
                    "geometry": permits.loc[permit_index, "geometry"],
                }
            )

    return gpd.GeoDataFrame(matches, geometry="geometry", crs="EPSG:4326")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terraces", default=str(DEFAULT_TERRACES_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument(
        "--district",
        default="KALLIO",
        help="Filter permits to this district name (empty string for all).",
    )
    args = parser.parse_args()

    terraces = load_terraces(pathlib.Path(args.terraces))
    permits = fetch_terrace_permits(args.district or None)
    print(f"Fetched {len(permits)} terrace permits"
          + (f" in {args.district}" if args.district else ""))

    matched = match_to_terraces(permits, terraces)
    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(matched.to_json(indent=2), encoding="utf-8")

    print(f"Matched {len(matched)}/{len(terraces)} bars to permit polygons:")
    for _, row in matched.iterrows():
        print(
            f"  {row['terrace_id']:30s} <- {row['permit_name']!r}"
            f" ({row['distance_m']} m, sim {row['similarity']})"
        )
    unmatched = set(terraces["id"].astype(str)) - set(matched["terrace_id"].astype(str))
    if unmatched:
        print(f"Unmatched ({len(unmatched)}): {', '.join(sorted(unmatched))}")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

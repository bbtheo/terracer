"""Pure, importable data layer for Terracer.

Zero Shiny imports so every function here is unit-testable without launching a
server. All data paths resolve relative to this file (robust to the cwd).

The app is one client-side page: everything it needs is bundled once by
`payload_json` and all interaction then happens in the browser.
"""

from __future__ import annotations

import json
import warnings
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
import pandas as pd
from pysolar.solar import get_altitude, get_azimuth

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
HELSINKI_TZ = ZoneInfo("Europe/Helsinki")

# Sampling grid: half-hourly, 08:00..23:00 inclusive (minutes from midnight).
SLOT_START_MIN = 8 * 60
SLOT_END_MIN = 23 * 60
SLOT_STEP_MIN = 30
SLOT_MINUTES = tuple(range(SLOT_START_MIN, SLOT_END_MIN + 1, SLOT_STEP_MIN))  # 31 slots

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # index = Mon=0..Sun=6

# Cluster centroid (verified): lon 24.9515 / lat 60.1836.
CENTER_LON = 24.9515
CENTER_LAT = 60.1836

# The projected CRS the map geometry is expressed in (GK25FIN).
MAP_CRS = "EPSG:3879"

# Search window for the day's highest sun, in minutes from midnight.
_PEAK_SEARCH = range(10 * 60, 16 * 60, 10)

# Sun fractions are sent as one base-11 digit per slot (tenths, rounded down).
_FRACTION_DIGITS = "0123456789a"


def load_terraces() -> gpd.GeoDataFrame:
    """All terraces (EPSG:4326) with `week_hours` parsed from `hours_json`:
    {weekday Mon=0..Sun=6: (open_min, close_min) or None}."""
    gdf = gpd.read_file(DATA_DIR / "terraces.geojson")
    gdf = gdf.set_crs("EPSG:4326") if gdf.crs is None else gdf.to_crs("EPSG:4326")
    gdf["id"] = gdf["id"].astype(str)
    raw = gdf["hours_json"] if "hours_json" in gdf else pd.Series([""] * len(gdf))
    gdf["week_hours"] = raw.fillna("").apply(_parse_week_hours)
    return gdf


def load_shadows() -> pd.DataFrame:
    """Shadow table with a tz-aware Europe/Helsinki datetime column."""
    df = pd.read_parquet(DATA_DIR / "shadows" / "terrace_shadows.parquet")
    df["datetime"] = pd.to_datetime(df["datetime"])
    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize(HELSINKI_TZ)
    else:
        df["datetime"] = df["datetime"].dt.tz_convert(HELSINKI_TZ)
    df["terrace_id"] = df["terrace_id"].astype(str)
    df["sun_fraction"] = df["sun_fraction"].astype(float)
    return df


def load_blocks() -> gpd.GeoDataFrame:
    """Building footprints with mesh-measured heights (see build_city_blocks)."""
    return gpd.read_parquet(DATA_DIR / "processed" / "city_blocks.parquet").to_crs(MAP_CRS)


def load_roads() -> gpd.GeoDataFrame:
    """Street centrelines with a drawn width in metres (see fetch_map_base)."""
    return gpd.read_parquet(DATA_DIR / "processed" / "map_roads.parquet").to_crs(MAP_CRS)


def load_water() -> gpd.GeoDataFrame:
    """Sea and inland water polygons (see fetch_map_base)."""
    return gpd.read_parquet(DATA_DIR / "processed" / "map_water.parquet").to_crs(MAP_CRS)


def load_terrace_centres() -> pd.DataFrame:
    """Mean position (EPSG:3879) of the points each terrace was ray cast from.
    These sit on the terrace itself, while the bar's own point is often on the roof."""
    points = pd.read_parquet(DATA_DIR / "shadows" / "terrace_points.parquet")
    projected = gpd.GeoSeries(gpd.points_from_xy(points["lon"], points["lat"]), crs="EPSG:4326").to_crs(MAP_CRS)
    points = points.assign(x=projected.x, y=projected.y, terrace_id=points["terrace_id"].astype(str))
    return points.groupby("terrace_id")[["x", "y"]].mean()


def _parse_week_hours(value) -> dict:
    """JSON string {"Mon": [open_min, close_min] or null, ...} ->
    {weekday_idx: (open_min, close_min) or None}. Missing/invalid -> all None."""
    out = {i: None for i in range(7)}
    if not value or not isinstance(value, str):
        return out
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        return out
    for i, day in enumerate(_WEEKDAYS):
        v = data.get(day)
        if isinstance(v, (list, tuple)) and len(v) == 2 and v[0] is not None:
            close = int(v[1]) if v[1] is not None else None
            out[i] = (int(v[0]), close)
    return out


def _effective_close(opens_min: int, closes_min: int | None) -> int:
    """Closing minute clamped into a same-day frame for our 08:00–23:00 window.

    A close that is <= open means it crosses midnight (e.g. opens 16:00, closes
    02:00) -> treat as open through end of day. Unknown close -> end of day.
    """
    if closes_min is None or closes_min < 0 or closes_min <= opens_min:
        return 24 * 60
    return closes_min


def sun_az_alt(dt: datetime) -> tuple[float, float]:
    """(azimuth, altitude) of the sun over the terrace cluster at `dt`, in
    degrees. Azimuth is clockwise from north, altitude is negative when the sun
    is down: the same convention used to compute the shadow data."""
    with warnings.catch_warnings():
        # pysolar warns about leap seconds after 2023; irrelevant here.
        warnings.simplefilter("ignore")
        az = float(get_azimuth(CENTER_LAT, CENTER_LON, dt))
        alt = float(get_altitude(CENTER_LAT, CENTER_LON, dt))
    return az % 360.0, alt


def _at(day: date, minutes: int) -> datetime:
    return datetime(day.year, day.month, day.day, minutes // 60, minutes % 60, tzinfo=HELSINKI_TZ)


def peak_sun(day: date) -> tuple[float, int]:
    """(altitude, minutes from midnight) of the day's highest sun. The app's
    colours are scaled to this, so every season gets its full range."""
    altitude, minutes = max((sun_az_alt(_at(day, m))[1], m) for m in _PEAK_SEARCH)
    return round(altitude, 2), minutes


def _encode_fractions(values) -> str:
    return "".join(_FRACTION_DIGITS[int(float(v) * 10 + 1e-6)] for v in values)


def _local(x: float, y: float, origin: tuple[float, float]) -> list[int]:
    return [round(x - origin[0]), round(y - origin[1])]


@lru_cache(maxsize=1)
def build_payload() -> dict:
    """Everything the page needs, in metres from the terraces' south-west corner."""
    terraces = load_terraces().to_crs(MAP_CRS)
    origin = tuple(terraces.total_bounds[:2])
    shadows = load_shadows()
    shadows["day"] = shadows["datetime"].dt.date
    shadows["minutes"] = shadows["datetime"].dt.hour * 60 + shadows["datetime"].dt.minute

    centres = load_terrace_centres()
    bars = []
    for _, row in terraces.iterrows():
        centre = centres.loc[row["id"]]
        x, y = _local(centre["x"], centre["y"], origin)
        hours = []
        for weekday in range(7):
            span = row["week_hours"][weekday]
            hours.append(None if span is None else [span[0], _effective_close(*span)])
        bars.append({"id": row["id"], "n": row["name"], "x": x, "y": y, "h": hours})

    dates = []
    for day, group in shadows.groupby("day"):
        table = group.pivot(index="terrace_id", columns="minutes", values="sun_fraction")
        altitude, minutes = peak_sun(day)
        dates.append(
            {
                "doy": day.timetuple().tm_yday,
                "noon": altitude,
                "noonT": minutes,
                "sun": [[round(v, 1) for v in sun_az_alt(_at(day, m))] for m in SLOT_MINUTES],
                "s": {b["id"]: _encode_fractions(table.loc[b["id"]].values) for b in bars},
            }
        )

    footprints = load_blocks()
    blocks = []
    for height, geometry in zip(footprints["height"], footprints.geometry):
        for part in getattr(geometry, "geoms", [geometry]):
            ring = [_local(x, y, origin) for x, y in part.exterior.coords[:-1]]
            blocks.append([round(float(height)), ring])

    roads_gdf = load_roads()
    roads = [
        [int(width), [_local(x, y, origin) for x, y in line.coords]]
        for width, line in zip(roads_gdf["width"], roads_gdf.geometry)
    ]
    water = [
        [[_local(x, y, origin) for x, y in ring.coords[:-1]] for ring in [polygon.exterior, *polygon.interiors]]
        for polygon in load_water().geometry
    ]

    xs = [p[0] for _, ring in blocks for p in ring]
    ys = [p[1] for _, ring in blocks for p in ring]
    return {
        "slots": list(SLOT_MINUTES),
        "bounds": [min(xs), min(ys), max(xs), max(ys)],
        "bars": bars,
        "dates": dates,
        "blocks": blocks,
        "roads": roads,
        "water": water,
    }


def payload_json() -> str:
    """The payload as JSON that is safe to place inside a <script> tag."""
    text = json.dumps(build_payload(), separators=(",", ":"), ensure_ascii=False)
    return text.replace("</", "<\\/")

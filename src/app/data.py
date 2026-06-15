"""Pure, importable data layer for Terracer.

Zero Shiny imports so every function here is unit-testable without launching a
server. All data paths resolve relative to this file (robust to the cwd).
"""

from __future__ import annotations

import json
import math
import warnings
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
import pandas as pd
from pysolar.solar import get_altitude, get_azimuth
from shapely.geometry import box

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
HELSINKI_TZ = ZoneInfo("Europe/Helsinki")

# Sampling grid: half-hourly, 08:00..23:00 inclusive (minutes from midnight).
SLOT_START_MIN = 8 * 60
SLOT_END_MIN = 23 * 60
SLOT_STEP_MIN = 30
SLOT_MINUTES = tuple(range(SLOT_START_MIN, SLOT_END_MIN + 1, SLOT_STEP_MIN))  # 31 slots
SLOT_HOURS = SLOT_STEP_MIN / 60.0  # 0.5 h represented by each lit slot
HOURS = tuple(range(8, 24))  # whole clock hours the grid spans (axis labels)

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # index = Mon=0..Sun=6

# Cluster centroid (verified): lon 24.9515 / lat 60.1836.
CENTER_LON = 24.9515
CENTER_LAT = 60.1836

# Building clip margin around the terrace bbox, in metres.
BUILDING_MARGIN_M = 150

def _today_ref() -> date:
    """Real today mapped onto the 2026 sample grid (by month/day) so the
    default keeps tracking the calendar on any future run. Feb 29 on a
    leap real year falls back to the 28th (2026 is not a leap year)."""
    t = date.today()
    try:
        return date(2026, t.month, t.day)
    except ValueError:
        return date(2026, t.month, 28)

# Shade -> sun colour ramp (5 stops). Used identically by grid cells, the day
# timeline and the map markers. RGB tuples.
_RAMP = [
    (0.00, (0x5B, 0x64, 0x70)),  # shade, cool grey
    (0.25, (0x8A, 0x7E, 0x63)),
    (0.50, (0xE9, 0xB9, 0x49)),
    (0.75, (0xFF, 0xB7, 0x03)),
    (1.00, (0xFB, 0x85, 0x00)),  # full sun, vivid orange
]
# Dark mode lifts the shade end so unlit dots stay visible.
_DARK_SHADE_END = (0x51, 0x5A, 0x6B)


# ---------------------------------------------------------------------------
# Loaders (cached once)
# ---------------------------------------------------------------------------
def load_terraces() -> gpd.GeoDataFrame:
    """All terraces with lon/lat + parsed opening-hours columns (EPSG:4326).

    Opening-hours columns: week_hours (dict {weekday Mon=0..Sun=6: (open_min,
    close_min) or None}) parsed from the `hours_json` property, and hours_text
    (human-readable weekly schedule).
    """
    gdf = gpd.read_file(DATA_DIR / "terraces.geojson")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")
    gdf["id"] = gdf["id"].astype(str)
    gdf["lon"] = gdf.geometry.x
    gdf["lat"] = gdf.geometry.y

    gdf["hours_text"] = gdf["hours_text"].fillna("") if "hours_text" in gdf else ""
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
    df["in_sun"] = df["in_sun"].astype(bool)
    df["sun_fraction"] = df["sun_fraction"].astype(float)
    return df


@lru_cache(maxsize=1)
def load_buildings_clipped() -> list[dict]:
    """Building footprints clipped to terraces bbox + margin, reprojected to
    4326, as a list of pydeck-ready ring dicts. Computed once per process.

    Each entry: {"polygon": [[lon, lat], ...], "elevation": float}.
    """
    terraces = load_terraces()
    buildings = gpd.read_parquet(DATA_DIR / "processed" / "buildings.parquet")

    # Clip in the projected CRS so the margin is metres, then reproject.
    t_proj = terraces.to_crs(buildings.crs)
    minx, miny, maxx, maxy = t_proj.total_bounds
    m = BUILDING_MARGIN_M
    clip = box(minx - m, miny - m, maxx + m, maxy + m)
    sub = buildings[buildings.intersects(clip)].copy()
    sub = sub.to_crs("EPSG:4326")

    out: list[dict] = []
    for _, row in sub.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        elev = float(max(0.0, (row["height_max"] or 0.0) - (row["height_min"] or 0.0)))
        parts = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for part in parts:
            ring = [[float(x), float(y)] for x, y in part.exterior.coords]
            out.append({"polygon": ring, "elevation": elev})
    return out


def load_permit_polygons() -> gpd.GeoDataFrame:
    """The (up to 12) matched permit polygons, EPSG:4326. Empty-safe."""
    path = DATA_DIR / "terrace_polygons.geojson"
    if not path.exists():
        return gpd.GeoDataFrame(
            {"terrace_id": []}, geometry=[], crs="EPSG:4326"
        )
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")
    if "terrace_id" in gdf.columns:
        gdf["terrace_id"] = gdf["terrace_id"].astype(str)
    return gdf


# ---------------------------------------------------------------------------
# Date / time grid helpers
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def sample_dates() -> list[date]:
    """The 27 biweekly sample dates, sorted ascending."""
    df = load_shadows()
    dates = sorted({d for d in df["datetime"].dt.date.unique()})
    return dates


def default_date() -> date:
    """Today's date mapped onto the 2026 data year — the date to default the
    picker to when the app is opened. Deliberately NOT pre-snapped: the UI snaps
    it to the nearest sample and shows the "nearest sample" note, so the picker
    still reflects the actual day the app was opened."""
    return _today_ref()


def snap_date(d: date) -> tuple[date, bool]:
    """Snap an arbitrary date to the nearest sample date.

    Returns (snapped_date, was_snapped). Ties resolve to the earlier date.
    """
    samples = sample_dates()
    if d in samples:
        return d, False
    # Min by absolute day-difference; ties -> earlier date (samples is sorted).
    best = min(samples, key=lambda s: abs((s - d).days))
    return best, True


def make_datetime(d: date, minutes: int) -> datetime:
    """Combine a date + minutes-from-midnight into a tz-aware Helsinki datetime."""
    minutes = int(minutes)
    return datetime(d.year, d.month, d.day, minutes // 60, minutes % 60, tzinfo=HELSINKI_TZ)


# ---------------------------------------------------------------------------
# Time / opening-hours helpers
# ---------------------------------------------------------------------------
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


def day_hours(week_hours, weekday: int):
    """(open_min, close_min) for the given weekday, or None if closed/unknown."""
    if not week_hours:
        return None
    return week_hours.get(int(weekday))


def fmt_day_hours(hours) -> str:
    """(open_min, close_min) -> '16:00–02:00'; None -> 'Closed'."""
    if not hours or hours[0] is None:
        return "Closed"
    o, c = hours
    return f"{fmt_minutes(o)}–{fmt_minutes(c if c is not None else o)}"


def fmt_minutes(minutes: int) -> str:
    """990 -> '16:30'. Minutes past 24:00 wrap (1560 -> '02:00')."""
    minutes = int(minutes) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def fmt_duration(slots: int) -> str:
    """A count of half-hour slots -> '3h 30m' / '2h' / '30m' / 'none'."""
    total = int(slots) * SLOT_STEP_MIN
    if total <= 0:
        return "none"
    h, m = divmod(total, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def _effective_close(opens_min: int, closes_min: int) -> int:
    """Closing minute clamped into a same-day frame for our 08:00–23:00 window.

    A close that is <= open means it crosses midnight (e.g. opens 16:00, closes
    02:00) -> treat as open through end of day. Unknown close -> end of day.
    """
    if closes_min is None or closes_min < 0 or closes_min <= opens_min:
        return 24 * 60
    return closes_min


def is_open_at(week_hours, dt: datetime) -> bool:
    """Whether a venue is open at datetime `dt` given its per-weekday schedule."""
    hrs = day_hours(week_hours, dt.weekday())
    if hrs is None or hrs[0] is None:
        return False
    o, c = hrs
    minutes = dt.hour * 60 + dt.minute
    return o <= minutes < _effective_close(o, c)


# ---------------------------------------------------------------------------
# Colour ramp
# ---------------------------------------------------------------------------
def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_color(frac: float, dark: bool = False, alpha: int = 230) -> list[int]:
    """Map a 0..1 sun fraction onto the 5-stop ramp -> [r, g, b, a]."""
    try:
        f = float(frac)
    except (TypeError, ValueError):
        f = 0.0
    if f != f:  # NaN
        f = 0.0
    f = max(0.0, min(1.0, f))

    stops = list(_RAMP)
    if dark:
        stops[0] = (0.00, _DARK_SHADE_END)

    for i in range(len(stops) - 1):
        x0, c0 = stops[i]
        x1, c1 = stops[i + 1]
        if f <= x1 or i == len(stops) - 2:
            span = (x1 - x0) or 1.0
            t = (f - x0) / span
            t = max(0.0, min(1.0, t))
            r = round(_lerp(c0[0], c1[0], t))
            g = round(_lerp(c0[1], c1[1], t))
            b = round(_lerp(c0[2], c1[2], t))
            return [int(r), int(g), int(b), int(alpha)]
    # Fallback (unreachable): full sun.
    c = stops[-1][1]
    return [c[0], c[1], c[2], int(alpha)]


def hex_color(frac: float, dark: bool = False) -> str:
    """The ramp colour as a #RRGGBB hex string (for CSS / matplotlib)."""
    r, g, b, _ = lerp_color(frac, dark=dark)
    return f"#{r:02X}{g:02X}{b:02X}"


def _relative_luminance(r: int, g: int, b: int) -> float:
    """WCAG relative luminance of an sRGB colour in 0..1."""
    def _lin(c: int) -> float:
        cs = c / 255.0
        return cs / 12.92 if cs <= 0.03928 else ((cs + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def readable_fg(frac: float, dark: bool = False) -> str:
    """Black or white ink chosen from the ramp background's *luminance* (not a
    fixed sun_fraction threshold) so the text stays readable on every cell.

    The 0.20 cutoff was tuned across the whole ramp in both modes to maximise
    the minimum contrast: the common shade cells (frac==0) jump from a failing
    ~2.6:1 to a strong pass, and every realistic data fraction clears WCAG AA
    Large (>= 3:1); only a single muddy mid-olive stop (frac~0.2, 40/6993 data
    rows) lands at ~4.3:1, just shy of full AA text but far above the prior
    code's ~2.6-3.9:1 failures.
    """
    r, g, b, _ = lerp_color(frac, dark=dark)
    return "#111111" if _relative_luminance(r, g, b) > 0.20 else "#FFFFFF"


# ---------------------------------------------------------------------------
# Snapshot / ranking / day profile
# ---------------------------------------------------------------------------
def snapshot_for(
    shadows: pd.DataFrame, terraces: gpd.GeoDataFrame, dt: datetime
) -> pd.DataFrame:
    """All 37 terraces at the (already snapped) datetime `dt`.

    Columns: terrace_id, name, amenity, address, maps_url, lon, lat,
    in_sun, sun_fraction, pct, color (RGBA list). Missing rows -> shade.
    """
    snap = shadows[shadows["datetime"] == dt][
        ["terrace_id", "in_sun", "sun_fraction"]
    ]
    base = terraces[["id", "name", "amenity", "address", "maps_url", "lon", "lat"]].copy()
    base = base.rename(columns={"id": "terrace_id"})
    merged = base.merge(snap, on="terrace_id", how="left")
    merged["in_sun"] = merged["in_sun"].fillna(False).astype(bool)
    merged["sun_fraction"] = merged["sun_fraction"].fillna(0.0).astype(float)
    merged["pct"] = (merged["sun_fraction"] * 100).round().astype(int)
    merged["color"] = merged["sun_fraction"].apply(lambda f: lerp_color(f))
    return merged.reset_index(drop=True)


def rank(snapshot_df: pd.DataFrame) -> pd.DataFrame:
    """Sort by sun_fraction desc, then name asc; assign Rank = 1..N."""
    ranked = snapshot_df.sort_values(
        ["sun_fraction", "name"], ascending=[False, True]
    ).reset_index(drop=True)
    ranked["Rank"] = range(1, len(ranked) + 1)
    return ranked


def day_profile(
    shadows: pd.DataFrame, terrace_id: str, d: date
) -> pd.DataFrame:
    """Half-hourly frame (minutes, hour, in_sun, sun_fraction) for terrace/date.

    Always returns exactly the SLOT_MINUTES grid (08:00..23:00 every 30 min);
    missing slots -> shade. `hour` is a float (e.g. 14.5) for axis labelling.
    """
    sub = shadows[
        (shadows["terrace_id"] == str(terrace_id))
        & (shadows["datetime"].dt.date == d)
    ].copy()
    sub["minutes"] = sub["datetime"].dt.hour * 60 + sub["datetime"].dt.minute
    sub = sub[["minutes", "in_sun", "sun_fraction"]]
    grid = pd.DataFrame({"minutes": list(SLOT_MINUTES)})
    out = grid.merge(sub, on="minutes", how="left")
    out["in_sun"] = out["in_sun"].fillna(False).astype(bool)
    out["sun_fraction"] = out["sun_fraction"].fillna(0.0).astype(float)
    out["hour"] = out["minutes"] / 60.0
    return out.reset_index(drop=True)


def sun_hours_left(profile_df: pd.DataFrame, from_minutes: int) -> float:
    """Sunlit hours remaining from `from_minutes` onward (0.5 h per lit slot)."""
    rest = profile_df[profile_df["minutes"] >= int(from_minutes)]
    return int(rest["in_sun"].sum()) * SLOT_HOURS


def best_hour(profile_df: pd.DataFrame) -> tuple[int | None, float]:
    """(minutes-from-midnight, fraction) of the sunniest slot; (None, 0.0) if none."""
    if profile_df.empty or float(profile_df["sun_fraction"].max()) <= 0.0:
        return None, 0.0
    idx = int(profile_df["sun_fraction"].idxmax())
    row = profile_df.loc[idx]
    return int(row["minutes"]), float(row["sun_fraction"])


def open_sun_left_table(
    shadows: pd.DataFrame,
    terraces: gpd.GeoDataFrame,
    sun_date: date,
    from_minutes: int,
    weekday: int,
) -> pd.Series:
    """Series indexed by terrace_id: remaining half-hour slots that are BOTH in
    sun AND within opening hours, from `from_minutes` onward.

    Sun is read from `sun_date` (the nearest sampled date), but the open/closed
    test uses `weekday` (the weekday of the date the user actually picked).
    """
    ids = terraces["id"].astype(str)
    sub = shadows[shadows["datetime"].dt.date == sun_date]
    if sub.empty:
        return pd.Series(0, index=ids.values, dtype=int)
    sub = sub[sub["in_sun"]].copy()
    sub["minutes"] = sub["datetime"].dt.hour * 60 + sub["datetime"].dt.minute
    sub = sub[sub["minutes"] >= int(from_minutes)]
    # Resolve each terrace's open/close for the requested weekday.
    info = terraces[["id", "week_hours"]].copy()
    info["terrace_id"] = info["id"].astype(str)
    today = info["week_hours"].apply(lambda wh: day_hours(wh, weekday))
    info["t_open"] = [h[0] if (h and h[0] is not None) else None for h in today]
    info["t_close"] = [h[1] if (h and h[0] is not None) else None for h in today]
    m = sub.merge(info[["terrace_id", "t_open", "t_close"]], on="terrace_id", how="left")
    if len(m):
        o = pd.to_numeric(m["t_open"], errors="coerce")
        c = pd.to_numeric(m["t_close"], errors="coerce")
        eff_close = c.where(c.notna() & (c > o), 24 * 60)
        keep = o.notna() & (m["minutes"] >= o) & (m["minutes"] < eff_close)
        counts = m[keep].groupby("terrace_id").size()
    else:
        counts = pd.Series(dtype=int)
    return counts.reindex(ids.values, fill_value=0).astype(int)


def ranked_for(
    shadows: pd.DataFrame,
    terraces: gpd.GeoDataFrame,
    sun_date: date,
    from_minutes: int,
    req_date: date | None = None,
) -> pd.DataFrame:
    """Terraces ranked by remaining OPEN-AND-SUNNY time today (descending).

    Sun comes from `sun_date` (nearest sampled date); opening hours use
    `req_date` (the date the user actually picked, default = sun_date). Adds:
      osl_slots   - remaining open+sunny half-hour slots from from_minutes
      osl_hours   - that as hours (0.5 each)
      open_now    - whether the bar is open at the requested date + selected time
      today_hours - "HH:MM–HH:MM" / "Closed" for the requested weekday
      hours_text  - full weekly schedule (display)
    Sort: osl_slots desc, then current sun_fraction desc, then name.
    """
    if req_date is None:
        req_date = sun_date
    wd = req_date.weekday()
    dt_sun = make_datetime(sun_date, from_minutes)
    dt_open = make_datetime(req_date, from_minutes)
    snap = snapshot_for(shadows, terraces, dt_sun)
    osl = open_sun_left_table(shadows, terraces, sun_date, from_minutes, wd)
    meta = terraces[["id", "week_hours", "hours_text"]].rename(
        columns={"id": "terrace_id"}
    )
    meta["terrace_id"] = meta["terrace_id"].astype(str)
    out = snap.merge(meta, on="terrace_id", how="left")
    out["osl_slots"] = out["terrace_id"].map(osl).fillna(0).astype(int)
    out["osl_hours"] = out["osl_slots"] * SLOT_HOURS
    out["open_now"] = out["week_hours"].apply(lambda wh: is_open_at(wh, dt_open))
    out["today_hours"] = out["week_hours"].apply(
        lambda wh: fmt_day_hours(day_hours(wh, wd))
    )
    out = out.sort_values(
        ["osl_slots", "sun_fraction", "name"], ascending=[False, False, True]
    ).reset_index(drop=True)
    out["Rank"] = range(1, len(out) + 1)
    return out


# ---------------------------------------------------------------------------
# Sun position + map indicator
# ---------------------------------------------------------------------------
_COMPASS_8 = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def sun_az_alt(dt: datetime) -> tuple[float, float]:
    """(azimuth, altitude) of the sun over the terrace cluster at `dt`, in
    degrees. Azimuth is clockwise from north (0=N, 90=E, 180=S, 270=W) and
    altitude is degrees above the horizon (negative when the sun is down) —
    the same convention used to compute the shadow data (src/core/sun.py)."""
    with warnings.catch_warnings():
        # pysolar warns about leap seconds after 2023; irrelevant here.
        warnings.simplefilter("ignore")
        az = float(get_azimuth(CENTER_LAT, CENTER_LON, dt))
        alt = float(get_altitude(CENTER_LAT, CENTER_LON, dt))
    return az % 360.0, alt


def compass_dir(az: float) -> str:
    """8-point compass label for an azimuth in degrees."""
    return _COMPASS_8[int((az % 360) / 45 + 0.5) % 8]


def sun_indicator_html(az: float, alt: float, is_dark: bool) -> str:
    """An absolutely-positioned SVG "sun compass" to overlay on the deck map.

    North-up (the deck is rendered with bearing=0): a needle points toward the
    sun's azimuth with a rayed sun glyph at the tip, and the label gives the
    8-point direction + elevation, or "below horizon" when the sun is down.
    """
    above = alt > 0
    cx, cy, r = 47.0, 49.0, 31.0
    a = math.radians(az)
    tx = cx + r * math.sin(a)
    ty = cy - r * math.cos(a)

    if is_dark:
        bg, ring, ink, muted = "rgba(28,24,18,.82)", "#5b5346", "#F4ECDD", "#9A8F7C"
    else:
        bg, ring, ink, muted = "rgba(255,255,255,.90)", "#E2D7BE", "#2B2118", "#8A7E6E"
    sun_col = "#FB8500" if above else "#9aa0a6"

    rays = ""
    if above:
        for k in range(8):
            ra = math.radians(k * 45)
            rays += (
                f'<line x1="{tx + 8.5 * math.cos(ra):.1f}" y1="{ty + 8.5 * math.sin(ra):.1f}" '
                f'x2="{tx + 12.5 * math.cos(ra):.1f}" y2="{ty + 12.5 * math.sin(ra):.1f}" '
                f'stroke="#FB8500" stroke-width="2" stroke-linecap="round"/>'
            )
    glyph_r = 6.5 if above else 5.5
    label = f"{compass_dir(az)} · {round(alt)}&#176;&#8593;" if above else "below horizon"
    title = (
        f"Sun {compass_dir(az)} — azimuth {round(az)}°, "
        f"elevation {round(alt)}°"
    )

    return (
        f'<div title="{title}" style="position:absolute;top:12px;right:12px;z-index:9999;'
        f"background:{bg};border:1px solid {ring};border-radius:13px;padding:7px 9px 5px;"
        f"backdrop-filter:blur(3px);text-align:center;"
        f"font-family:Inter,system-ui,-apple-system,sans-serif;"
        f'box-shadow:0 2px 12px rgba(0,0,0,.20)">'
        f'<div style="font-size:9px;letter-spacing:.6px;text-transform:uppercase;'
        f'color:{muted};font-weight:700">Sun</div>'
        f'<svg width="94" height="94" viewBox="0 0 94 94">'
        f'<circle cx="{cx}" cy="{cy}" r="{r + 6:.0f}" fill="none" stroke="{ring}" stroke-width="1.5"/>'
        f'<text x="{cx}" y="12" text-anchor="middle" font-size="10" font-weight="700" fill="{muted}">N</text>'
        f'<text x="{cx}" y="92" text-anchor="middle" font-size="8" fill="{muted}">S</text>'
        f'<line x1="{cx}" y1="{cy}" x2="{tx:.1f}" y2="{ty:.1f}" stroke="{sun_col}" stroke-width="3" stroke-linecap="round"/>'
        f"{rays}"
        f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="{glyph_r}" fill="{sun_col}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="2.6" fill="{ink}"/>'
        f"</svg>"
        f'<div style="font-size:11px;color:{ink};font-weight:700;margin-top:-4px">{label}</div>'
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Map (pydeck) builder
# ---------------------------------------------------------------------------
_DARK_BASEMAP = (
    "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
)


def _permit_features(permits: gpd.GeoDataFrame) -> dict:
    """A FeatureCollection of permit polygons for a GeoJsonLayer."""
    features = []
    if permits is None or len(permits) == 0:
        return {"type": "FeatureCollection", "features": features}
    for _, row in permits.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {"terrace_id": str(row.get("terrace_id", ""))},
                "geometry": geom.__geo_interface__,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def build_deck_html(
    snapshot_df: pd.DataFrame,
    selected_id: str | None,
    buildings: list[dict],
    permits: gpd.GeoDataFrame,
    is_dark: bool,
    dt: datetime | None = None,
    zoom: float = 13.7,
) -> str:
    """Build the pydeck Deck and return a standalone HTML string.

    Colour logic is entirely Python-side (precomputed RGBA per marker); no JS
    colour functions. Buildings are passed pre-clipped/cached. When `dt` is
    given, a sun-direction compass for that time is overlaid on the map.
    """
    import pydeck as pdk

    df = snapshot_df.copy()
    # Recompute colour for the active theme (shade end differs in dark mode).
    df["color"] = df["sun_fraction"].apply(lambda f: lerp_color(f, dark=is_dark))
    df["radius"] = 6.0 + df["sun_fraction"] * 6.0
    df["pct_label"] = df["pct"].astype(str) + "%"

    # pydeck's serializer cannot handle a pandas DataFrame directly (it trips
    # on internal `_flags`); feed plain records instead.
    cols = ["terrace_id", "name", "lon", "lat", "color", "radius", "pct_label"]
    records = df[cols].to_dict("records")

    layers = []

    # 1. Building context (recedes into the background).
    if buildings:
        fill = [60, 56, 48, 120] if is_dark else [210, 205, 196, 90]
        layers.append(
            pdk.Layer(
                "PolygonLayer",
                data=buildings,
                get_polygon="polygon",
                get_elevation="elevation",
                extruded=True,
                wireframe=False,
                get_fill_color=fill,
                pickable=False,
            )
        )

    # 2. Permit polygons (optional nicety) — thin orange outline.
    fc = _permit_features(permits)
    if fc["features"]:
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                data=fc,
                filled=False,
                stroked=True,
                get_line_color=[251, 133, 0, 160],
                line_width_min_pixels=1,
                pickable=False,
            )
        )

    # 3. Terrace markers.
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=records,
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius",
            radius_min_pixels=7,
            radius_max_pixels=16,
            stroked=True,
            get_line_color=[255, 255, 255, 200],
            line_width_min_pixels=1,
            pickable=True,
        )
    )

    # 4. Selected emphasis — a glowing halo ring.
    if selected_id is not None:
        sel = [r for r in records if r["terrace_id"] == str(selected_id)]
        if sel:
            ring = [255, 209, 102, 255] if is_dark else [255, 255, 255, 255]
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=sel,
                    get_position="[lon, lat]",
                    get_fill_color=[0, 0, 0, 0],
                    get_radius="radius",
                    radius_min_pixels=14,
                    radius_max_pixels=22,
                    stroked=True,
                    get_line_color=ring,
                    line_width_min_pixels=3,
                    pickable=False,
                )
            )

    view_state = pdk.ViewState(
        latitude=CENTER_LAT,
        longitude=CENTER_LON,
        zoom=zoom,
        pitch=40,
        bearing=0,
    )

    deck_kwargs = dict(
        layers=layers,
        initial_view_state=view_state,
        tooltip={
            "html": "<b>{name}</b><br/>{pct_label} in sun",
            "style": {"backgroundColor": "#2B2118", "color": "#FFD166"},
        },
    )
    if is_dark:
        deck_kwargs["map_style"] = _DARK_BASEMAP
    else:
        deck_kwargs["map_style"] = "road"

    deck = pdk.Deck(**deck_kwargs)
    html_str = deck.to_html(as_string=True)

    # Overlay the sun-direction compass (HTML/SVG, so it needs no WebGL and
    # sits above the canvas in the corner).
    if dt is not None:
        az, alt = sun_az_alt(dt)
        overlay = sun_indicator_html(az, alt, is_dark)
        if "</body>" in html_str:
            html_str = html_str.replace("</body>", overlay + "</body>", 1)
        else:
            html_str += overlay
    return html_str

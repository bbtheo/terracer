"""Pure, importable data layer for Terracer.

Zero Shiny imports so every function here is unit-testable without launching a
server. All data paths resolve relative to this file (robust to the cwd).
"""

from __future__ import annotations

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

# The reachable hours on the slider (hourly, 8:00..23:00).
HOURS = tuple(range(8, 24))

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
    """37 terraces with lon/lat columns added (EPSG:4326)."""
    gdf = gpd.read_file(DATA_DIR / "terraces.geojson")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")
    gdf["id"] = gdf["id"].astype(str)
    gdf["lon"] = gdf.geometry.x
    gdf["lat"] = gdf.geometry.y
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


def make_datetime(d: date, hour: int) -> datetime:
    """Combine a date + hour into a tz-aware Europe/Helsinki datetime."""
    return datetime.combine(d, time(hour=int(hour)), tzinfo=HELSINKI_TZ)


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
    """7-row frame (hour, in_sun, sun_fraction) for the given terrace/date.

    Always returns exactly the 7 grid hours; missing hours -> shade.
    """
    sub = shadows[
        (shadows["terrace_id"] == str(terrace_id))
        & (shadows["datetime"].dt.date == d)
    ].copy()
    sub["hour"] = sub["datetime"].dt.hour
    sub = sub[["hour", "in_sun", "sun_fraction"]]
    grid = pd.DataFrame({"hour": list(HOURS)})
    out = grid.merge(sub, on="hour", how="left")
    out["in_sun"] = out["in_sun"].fillna(False).astype(bool)
    out["sun_fraction"] = out["sun_fraction"].fillna(0.0).astype(float)
    return out.reset_index(drop=True)


def sun_hours_left(profile_df: pd.DataFrame, current_hour: int) -> int:
    """Sunlit hours remaining from current_hour onward (1h per lit sample)."""
    rest = profile_df[profile_df["hour"] >= int(current_hour)]
    return int(rest["in_sun"].sum())


def best_hour(profile_df: pd.DataFrame) -> tuple[int | None, float]:
    """(hour, fraction) of the sunniest sample; (None, 0.0) if no sun."""
    if profile_df.empty or float(profile_df["sun_fraction"].max()) <= 0.0:
        return None, 0.0
    idx = int(profile_df["sun_fraction"].idxmax())
    row = profile_df.loc[idx]
    return int(row["hour"]), float(row["sun_fraction"])


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

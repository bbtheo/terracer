"""Tests for the Terracer Shiny app's pure data layer.

The app module is imported BY FILE PATH (no assumed package import path) so the
tests run regardless of how `src/app` is laid out on sys.path.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP_PATH = REPO / "src" / "app" / "app.py"
DATA_PATH = REPO / "src" / "app" / "data.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _data():
    return _load("terracer_data", DATA_PATH)


def test_loaders_return_expected_shapes():
    D = _data()
    terraces = D.load_terraces()
    assert len(terraces) == 37
    assert {"id", "name", "amenity", "lon", "lat"}.issubset(terraces.columns)

    shadows = D.load_shadows()
    assert len(shadows) > 6000
    assert {"terrace_id", "datetime", "in_sun", "sun_fraction"}.issubset(shadows.columns)
    assert str(shadows["datetime"].dt.tz) == "Europe/Helsinki"


def test_sample_dates_and_default():
    D = _data()
    dates = D.sample_dates()
    assert len(dates) == 27
    assert all(d.year == 2026 for d in dates)
    # Default is the OPEN date (today mapped onto the 2026 data year), in-bounds
    # and NOT pre-snapped — the UI snaps it for display.
    default = D.default_date()
    assert default == D._today_ref()
    assert default.year == 2026
    assert dates[0] <= default <= dates[-1]


def test_snap_date_off_grid_and_exact():
    D = _data()
    samples = D.sample_dates()
    off_grid = date(2026, 6, 13)
    snapped, was = D.snap_date(off_grid)
    assert snapped in samples
    assert was is True
    # The snapped date is the nearest sample.
    assert snapped == min(samples, key=lambda s: abs((s - off_grid).days))

    exact = samples[10]
    snapped2, was2 = D.snap_date(exact)
    assert snapped2 == exact
    assert was2 is False


def test_snapshot_for_returns_37_rows():
    D = _data()
    terraces = D.load_terraces()
    shadows = D.load_shadows()
    sample = date(2026, 6, 18)  # a real 2026 summer sample date
    dt = D.make_datetime(sample, 14)
    snap = D.snapshot_for(shadows, terraces, dt)
    assert len(snap) == 37
    assert {"in_sun", "sun_fraction", "pct", "color"}.issubset(snap.columns)
    assert snap["in_sun"].dtype == bool
    assert snap["sun_fraction"].between(0.0, 1.0).all()
    # At a summer afternoon at least one terrace is lit.
    assert int(snap["in_sun"].sum()) >= 1


def test_day_profile_returns_hourly_rows():
    D = _data()
    shadows = D.load_shadows()
    terrace_id = shadows["terrace_id"].iloc[0]
    prof = D.day_profile(shadows, terrace_id, date(2026, 6, 18))
    assert len(prof) == 16
    assert prof["hour"].tolist() == list(range(8, 24))
    assert prof["sun_fraction"].between(0.0, 1.0).all()


def test_rank_orders_by_fraction_desc():
    D = _data()
    terraces = D.load_terraces()
    shadows = D.load_shadows()
    dt = D.make_datetime(date(2026, 6, 18), 14)
    ranked = D.rank(D.snapshot_for(shadows, terraces, dt))
    assert ranked["Rank"].tolist() == list(range(1, 38))
    fracs = ranked["sun_fraction"].tolist()
    assert fracs == sorted(fracs, reverse=True)


def test_sun_hours_left_and_best_hour():
    D = _data()
    shadows = D.load_shadows()
    terrace_id = shadows["terrace_id"].iloc[0]
    prof = D.day_profile(shadows, terrace_id, date(2026, 6, 18))
    left = D.sun_hours_left(prof, 14)
    assert isinstance(left, int) and 0 <= left <= 16  # 1h per lit sample
    hour, frac = D.best_hour(prof)
    assert hour is None or hour in range(8, 24)
    assert 0.0 <= frac <= 1.0


def test_sun_az_alt_and_compass():
    D = _data()
    # Summer afternoon: sun high and to the south-ish.
    az, alt = D.sun_az_alt(D.make_datetime(date(2026, 6, 17), 14))
    assert 0.0 <= az < 360.0
    assert alt > 40.0
    assert D.compass_dir(az) == "S"
    # Morning sun in the east.
    az_am, _ = D.sun_az_alt(D.make_datetime(date(2026, 6, 17), 8))
    assert D.compass_dir(az_am) == "E"
    # Winter evening: sun below the horizon.
    _, alt_night = D.sun_az_alt(D.make_datetime(date(2026, 12, 30), 20))
    assert alt_night < 0.0
    # Compass wraps correctly at the cardinal boundaries.
    assert D.compass_dir(0) == "N" and D.compass_dir(359) == "N"
    assert D.compass_dir(90) == "E" and D.compass_dir(270) == "W"


def test_build_deck_html_injects_sun_indicator():
    D = _data()
    terraces = D.load_terraces()
    shadows = D.load_shadows()
    buildings = D.load_buildings_clipped()
    permits = D.load_permit_polygons()
    dt = D.make_datetime(date(2026, 6, 18), 14)
    snap = D.snapshot_for(shadows, terraces, dt)
    html_with = D.build_deck_html(snap, None, buildings, permits, False, dt=dt)
    assert "</body>" in html_with  # the injection anchor exists
    assert html_with.count("</body>") == 1
    assert "Sun" in html_with and "azimuth" in html_with
    # Omitting dt yields no indicator (back-compatible).
    html_without = D.build_deck_html(snap, None, buildings, permits, False)
    assert "azimuth" not in html_without


def test_lerp_color_endpoints():
    D = _data()
    assert D.lerp_color(0.0)[:3] == [0x5B, 0x64, 0x70]
    assert D.lerp_color(1.0)[:3] == [0xFB, 0x85, 0x00]
    # Dark mode lifts the shade end.
    assert D.lerp_color(0.0, dark=True)[:3] != [0x5B, 0x64, 0x70]


def test_app_module_defines_app():
    m = _load("terracer_app", APP_PATH)
    assert hasattr(m, "app")
    from shiny import App

    assert isinstance(m.app, App)

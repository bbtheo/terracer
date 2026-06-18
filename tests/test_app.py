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

# A real 2026 summer sample date (biweekly grid, day 168 from 2026-01-01).
SAMPLE = date(2026, 6, 18)
NOON = 14 * 60  # minutes from midnight


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
    assert len(terraces) == 43
    assert {"id", "name", "amenity", "lon", "lat"}.issubset(terraces.columns)
    # Opening-hours parsed into a per-weekday schedule.
    assert {"week_hours", "hours_text"}.issubset(terraces.columns)
    for wh in terraces["week_hours"]:
        assert set(wh.keys()) == set(range(7))  # Mon..Sun present
        for v in wh.values():
            assert v is None or (len(v) == 2 and v[0] is not None)

    shadows = D.load_shadows()
    assert len(shadows) > 30000
    assert {"terrace_id", "datetime", "in_sun", "sun_fraction"}.issubset(shadows.columns)
    assert str(shadows["datetime"].dt.tz) == "Europe/Helsinki"


def test_half_hour_grid():
    D = _data()
    assert len(D.SLOT_MINUTES) == 31
    assert D.SLOT_MINUTES[0] == 8 * 60 and D.SLOT_MINUTES[-1] == 23 * 60
    assert D.SLOT_STEP_MIN == 30 and D.SLOT_HOURS == 0.5
    # Data really is sampled half-hourly.
    s = D.load_shadows()
    mins = sorted({int(h) * 60 + int(m) for h, m in zip(s["datetime"].dt.hour, s["datetime"].dt.minute)})
    assert mins == list(D.SLOT_MINUTES)


def test_sample_dates_and_default():
    D = _data()
    dates = D.sample_dates()
    assert len(dates) == 27
    assert all(d.year == 2026 for d in dates)
    default = D.default_date()
    assert default == D._today_ref()  # the open date
    assert dates[0] <= default <= dates[-1]


def test_snap_date_off_grid_and_exact():
    D = _data()
    samples = D.sample_dates()
    off = date(2026, 6, 13)
    snapped, was = D.snap_date(off)
    assert was is True and snapped in samples
    assert snapped == min(samples, key=lambda s: abs((s - off).days))
    snapped2, was2 = D.snap_date(samples[10])
    assert snapped2 == samples[10] and was2 is False


def test_make_datetime_and_fmt():
    D = _data()
    dt = D.make_datetime(SAMPLE, 14 * 60 + 30)
    assert (dt.hour, dt.minute) == (14, 30)
    assert D.fmt_minutes(14 * 60 + 30) == "14:30"
    assert D.fmt_minutes(8 * 60) == "08:00"
    assert D.fmt_duration(7) == "3h 30m"  # 7 half-hour slots
    assert D.fmt_duration(4) == "2h"
    assert D.fmt_duration(1) == "30m"
    assert D.fmt_duration(0) == "none"


def test_snapshot_for_returns_all_terraces():
    D = _data()
    terraces = D.load_terraces()
    shadows = D.load_shadows()
    snap = D.snapshot_for(shadows, terraces, D.make_datetime(SAMPLE, NOON))
    assert len(snap) == len(terraces) == 43
    assert {"in_sun", "sun_fraction", "pct", "color"}.issubset(snap.columns)
    assert snap["sun_fraction"].between(0.0, 1.0).all()
    assert int(snap["in_sun"].sum()) >= 1


def test_day_profile_is_half_hourly():
    D = _data()
    shadows = D.load_shadows()
    tid = shadows["terrace_id"].iloc[0]
    prof = D.day_profile(shadows, tid, SAMPLE)
    assert len(prof) == 31
    assert prof["minutes"].tolist() == list(D.SLOT_MINUTES)
    assert prof["sun_fraction"].between(0.0, 1.0).all()


def test_sun_hours_left_and_best_hour():
    D = _data()
    shadows = D.load_shadows()
    tid = shadows["terrace_id"].iloc[0]
    prof = D.day_profile(shadows, tid, SAMPLE)
    left = D.sun_hours_left(prof, NOON)
    assert isinstance(left, float) and 0.0 <= left <= 15.0
    assert (left / D.SLOT_HOURS).is_integer()  # whole half-hour slots
    minutes, frac = D.best_hour(prof)
    assert minutes is None or minutes in D.SLOT_MINUTES
    assert 0.0 <= frac <= 1.0


def test_week_hours_and_is_open():
    D = _data()
    t = D.load_terraces().set_index("id")
    mon = date(2026, 6, 15)  # Monday
    thu = date(2026, 6, 18)  # Thursday
    assert mon.weekday() == 0 and thu.weekday() == 3

    # Brooke is closed Mondays, open Thursday evening.
    brooke = t.loc["brooke"]["week_hours"]
    assert brooke[0] is None  # Mon closed
    assert D.is_open_at(brooke, D.make_datetime(mon, 18 * 60)) is False
    assert D.is_open_at(brooke, D.make_datetime(thu, 18 * 60)) is True

    # William K. Kurvi is closed every day (seasonal closure).
    william = t.loc["william_k_kurvi"]["week_hours"]
    assert all(william[d] is None for d in range(7))
    for d in (mon, thu):
        assert D.is_open_at(william, D.make_datetime(d, 18 * 60)) is False

    # Day-hours formatting.
    assert D.fmt_day_hours(None) == "Closed"
    assert D.fmt_day_hours((16 * 60, 2 * 60)) == "16:00–02:00"


def test_ranked_for_orders_by_open_sun_and_respects_closed_days():
    D = _data()
    terraces = D.load_terraces()
    shadows = D.load_shadows()
    mon = date(2026, 6, 15)  # request a Monday
    r = D.ranked_for(shadows, terraces, SAMPLE, NOON, req_date=mon)
    assert len(r) == 43
    assert r["Rank"].tolist() == list(range(1, 44))
    # Ordered by remaining open+sunny slots, descending.
    assert r["osl_slots"].tolist() == sorted(r["osl_slots"].tolist(), reverse=True)
    assert {"open_now", "osl_hours", "hours_text"}.issubset(r.columns)
    # A Monday-closed bar must be closed and contribute zero open-sun time.
    brooke = r[r["terrace_id"] == "brooke"].iloc[0]
    assert bool(brooke["open_now"]) is False
    assert int(brooke["osl_slots"]) == 0


def test_new_bars_present():
    D = _data()
    ids = set(D.load_terraces()["id"])
    assert {"toveri", "alkuviini", "mamas_empanadas", "way_bakery", "fat_tonys"}.issubset(ids)
    assert "barbers_beer_company" not in ids


def test_multi_side_permit_polygons():
    """Bars with a terrace on more than one side of the building are stored as a
    multi-part polygon so the sun fraction integrates across all sides."""
    D = _data()
    permits = D.load_permit_polygons().set_index("terrace_id")
    for tid in ("sivukirjasto", "toveri"):
        assert tid in permits.index
        assert permits.loc[tid].geometry.geom_type == "MultiPolygon"
        assert len(permits.loc[tid].geometry.geoms) >= 2


def test_sun_map_points():
    """Per-point sun data drives the terrace sun-map infographic."""
    D = _data()
    tp = D.load_terrace_points()
    ps = D.load_point_shadows()
    assert len(tp) > 0 and len(ps) > 0
    assert str(ps["datetime"].dt.tz) == "Europe/Helsinki"
    # A multi-side polygon terrace has several mapped points.
    sm = D.sun_map_points(ps, tp, "sivukirjasto", D.make_datetime(SAMPLE, NOON))
    assert len(sm) >= 5
    assert {"lon", "lat", "in_sun"}.issubset(sm.columns)
    assert sm["in_sun"].dtype == bool
    # Every terrace has at least one sample point (single-point bars approximated).
    assert tp.groupby("terrace_id").size().min() >= 1
    assert tp["terrace_id"].nunique() >= 43


def test_sun_az_alt_and_compass():
    D = _data()
    az, alt = D.sun_az_alt(D.make_datetime(date(2026, 6, 17), NOON))
    assert 0.0 <= az < 360.0 and alt > 40.0
    assert D.compass_dir(az) == "S"
    az_am, _ = D.sun_az_alt(D.make_datetime(date(2026, 6, 17), 8 * 60))
    assert D.compass_dir(az_am) == "E"
    _, alt_night = D.sun_az_alt(D.make_datetime(date(2026, 12, 30), 20 * 60))
    assert alt_night < 0.0
    assert D.compass_dir(0) == "N" and D.compass_dir(90) == "E" and D.compass_dir(270) == "W"


def test_build_deck_html_injects_sun_indicator():
    D = _data()
    terraces = D.load_terraces()
    shadows = D.load_shadows()
    buildings = D.load_buildings_clipped()
    permits = D.load_permit_polygons()
    dt = D.make_datetime(SAMPLE, NOON)
    snap = D.snapshot_for(shadows, terraces, dt)
    html_with = D.build_deck_html(snap, None, buildings, permits, False, dt=dt)
    assert html_with.count("</body>") == 1
    assert "Sun" in html_with and "azimuth" in html_with
    assert "azimuth" not in D.build_deck_html(snap, None, buildings, permits, False)


def test_lerp_color_endpoints():
    D = _data()
    assert D.lerp_color(0.0)[:3] == [0x5B, 0x64, 0x70]
    assert D.lerp_color(1.0)[:3] == [0xFB, 0x85, 0x00]
    assert D.lerp_color(0.0, dark=True)[:3] != [0x5B, 0x64, 0x70]


def test_app_module_defines_app():
    m = _load("terracer_app", APP_PATH)
    assert hasattr(m, "app")
    from shiny import App

    assert isinstance(m.app, App)

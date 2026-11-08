"""Tests for the Terracer app's pure data layer and page shell.

The app module is imported BY FILE PATH (no assumed package import path) so the
tests run regardless of how `src/app` is laid out on sys.path.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP_PATH = REPO / "src" / "app" / "app.py"
DATA_PATH = REPO / "src" / "app" / "data.py"
WWW = REPO / "src" / "app" / "www"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _data():
    return _load("terracer_data", DATA_PATH)


def _payload():
    return _data().build_payload()


def test_loaders_return_expected_shapes():
    D = _data()
    terraces = D.load_terraces()
    assert len(terraces) == 43
    assert {"id", "name", "week_hours"}.issubset(terraces.columns)
    for week in terraces["week_hours"]:
        assert set(week.keys()) == set(range(7))

    shadows = D.load_shadows()
    assert len(shadows) > 30000
    assert str(shadows["datetime"].dt.tz) == "Europe/Helsinki"

    blocks = D.load_blocks()
    assert len(blocks) > 1000
    assert (blocks["height"] >= 3).all()


def test_half_hour_grid():
    D = _data()
    assert len(D.SLOT_MINUTES) == 31
    assert D.SLOT_MINUTES[0] == 8 * 60 and D.SLOT_MINUTES[-1] == 23 * 60


def test_week_hours_parsing():
    D = _data()
    week = D._parse_week_hours('{"Mon":[900,1380],"Tue":null}')
    assert week[0] == (900, 1380) and week[1] is None and week[6] is None
    assert D._parse_week_hours("not json") == {i: None for i in range(7)}


def test_effective_close_handles_past_midnight():
    D = _data()
    assert D._effective_close(16 * 60, 2 * 60) == 24 * 60
    assert D._effective_close(16 * 60, None) == 24 * 60
    assert D._effective_close(16 * 60, 22 * 60) == 22 * 60


def test_peak_sun_tracks_the_season():
    D = _data()
    summer, summer_time = D.peak_sun(date(2026, 6, 18))
    winter, _ = D.peak_sun(date(2026, 12, 17))
    assert 50 < summer < 56 and 4 < winter < 9
    assert 12 * 60 < summer_time < 15 * 60


def test_fraction_encoding_keeps_the_sunny_threshold():
    D = _data()
    assert D._encode_fractions([0.0, 0.49, 0.5, 1.0]) == "045a"


def test_payload_shape():
    payload = _payload()
    assert len(payload["slots"]) == 31
    assert len(payload["bars"]) == 43
    assert len(payload["dates"]) == 27
    for bar in payload["bars"]:
        assert len(bar["h"]) == 7
        for span in bar["h"]:
            assert span is None or span[0] < span[1]
    for row in payload["dates"]:
        assert len(row["sun"]) == 31
        assert set(row["s"]) == {b["id"] for b in payload["bars"]}
        assert all(len(digits) == 31 for digits in row["s"].values())


def test_map_covers_every_bar():
    # The western bars used to fall outside the building data.
    payload = _payload()
    x0, y0, x1, y1 = payload["bounds"]
    blocks = payload["blocks"]
    for bar in payload["bars"]:
        assert x0 < bar["x"] < x1 and y0 < bar["y"] < y1
        nearby = sum(
            1
            for _, ring in blocks
            if abs(ring[0][0] - bar["x"]) < 150 and abs(ring[0][1] - bar["y"]) < 150
        )
        assert nearby > 0, bar["n"]


def test_dots_sit_on_terraces_not_rooftops():
    from shapely import STRtree, Point
    from shapely.geometry import Polygon

    payload = _payload()
    tree = STRtree([Polygon(ring).buffer(0) for _, ring in payload["blocks"] if len(ring) >= 3])
    on_roof = sum(len(tree.query(Point(b["x"], b["y"]), predicate="within")) > 0 for b in payload["bars"])
    assert on_roof < len(payload["bars"]) / 4


def test_payload_json_is_safe_in_a_script_tag():
    D = _data()
    text = D.payload_json()
    assert "</" not in text
    assert len(json.loads(text)["bars"]) == 43


def test_app_module_defines_app():
    m = _load("terracer_app", APP_PATH)
    from shiny import App

    assert isinstance(m.app, App)
    assert (WWW / "terracer.js").exists() and (WWW / "terracer.css").exists()

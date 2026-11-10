"""Tests for measured sunshine storage. No network: FMI responses are stubbed."""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _sunshine():
    spec = importlib.util.spec_from_file_location("terracer_sunshine", REPO / "src" / "app" / "sunshine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _xml(stamp: str, value: str) -> str:
    return (
        f"<BsWfs:Time>{stamp}</BsWfs:Time>"
        "<BsWfs:ParameterName>SUND_1MIN</BsWfs:ParameterName>"
        f"<BsWfs:ParameterValue>{value}</BsWfs:ParameterValue>"
    )


def test_observations_land_on_the_helsinki_day_and_slot():
    S = _sunshine()
    # 22:15 UTC in January is already 00:15 the next day in Helsinki.
    days = S.parse_observations(_xml("2026-01-05T22:15:00Z", "60") + _xml("2026-06-10T09:00:00Z", "30"))
    assert days[date(2026, 1, 6)][0][0] == 60
    assert days[date(2026, 6, 10)][0][24] == 30  # 12:00 summer time
    assert S.parse_observations(_xml("2026-06-10T09:00:00Z", "NaN")) == {}


def test_encode_day_keeps_the_slot_grid():
    S = _sunshine()
    seconds = [0.0] * 48
    seconds[16] = 1800  # 08:00, all sun
    seconds[17] = 900  # 08:30, half
    seconds[46] = 5000  # 23:00, capped
    encoded = S.encode_day(seconds)
    assert len(encoded) == S.SLOT_COUNT
    assert encoded[0] == "a" and encoded[1] == "5" and encoded[30] == "a"


def _stub(S, days):
    S.fetch_observations = lambda first, last: {d: v for d, v in days.items() if first <= d <= last}


def test_extend_history_adds_only_finished_days(tmp_path):
    S = _sunshine()
    yesterday = S.today() - timedelta(days=1)
    path = tmp_path / "sunshine.csv"
    path.write_text(f"{yesterday - timedelta(days=2)},{'0' * 31}\n")
    full = ([0.0] * 48, 1440)
    _stub(S, {yesterday - timedelta(days=1): full, yesterday: full, S.today(): full})
    assert S.extend_history(path) == 2
    assert max(S.read_history(path)) == yesterday.isoformat()
    assert S.extend_history(path) == 0


def test_extend_history_retries_after_an_outage(tmp_path):
    S = _sunshine()
    yesterday = S.today() - timedelta(days=1)
    path = tmp_path / "sunshine.csv"
    path.write_text(f"{yesterday - timedelta(days=3)},{'0' * 31}\n")
    _stub(S, {
        yesterday - timedelta(days=2): ([0.0] * 48, 1440),
        yesterday - timedelta(days=1): ([0.0] * 48, 200),  # station outage
        yesterday: ([0.0] * 48, 1440),
    })
    assert S.extend_history(path) == 1
    assert max(S.read_history(path)) == (yesterday - timedelta(days=2)).isoformat()


def test_stored_history_is_complete():
    S = _sunshine()
    history = S.read_history()
    days = sorted(date.fromisoformat(d) for d in history)
    assert days[0] == date(2026, 1, 1)
    assert all(b - a == timedelta(days=1) for a, b in zip(days, days[1:]))
    assert all(len(v) == S.SLOT_COUNT for v in history.values())

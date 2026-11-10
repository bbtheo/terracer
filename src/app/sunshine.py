"""Measured sunshine from the Finnish Meteorological Institute (FMI).

Kept free of the rest of the app's imports so the nightly job only needs httpx.
Each day is stored as one base-11 digit per half-hour slot, 08:00 to 23:00: the
share of that slot with sun, in tenths.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

HISTORY_PATH = Path(__file__).resolve().parents[2] / "data" / "weather" / "sunshine.csv"
HELSINKI_TZ = ZoneInfo("Europe/Helsinki")

WFS_URL = "https://opendata.fmi.fi/wfs"
STORED_QUERY = "fmi::observations::radiation::simple"
KUMPULA_STATION = 101004
CHUNK_DAYS = 6  # FMI allows 168 hours per request; a Helsinki day spills into the UTC day before

SLOT_COUNT = 31
FIRST_SLOT = 16  # index of 08:00 among the day's 48 half hours
SLOT_SECONDS = 1800
DIGITS = "0123456789a"
COMPLETE_DAY_MINUTES = 1200  # fewer minutes than this means the station had an outage

_OBSERVATION = re.compile(
    r"<BsWfs:Time>([^<]*)</BsWfs:Time>\s*"
    r"<BsWfs:ParameterName>SUND_1MIN</BsWfs:ParameterName>\s*"
    r"<BsWfs:ParameterValue>([^<]*)<"
)


def today() -> date:
    return datetime.now(HELSINKI_TZ).date()


def parse_observations(xml: str) -> dict[date, tuple[list[float], int]]:
    """Per Helsinki day: sunny seconds in each of 48 half hours, and minutes seen."""
    days: dict[date, tuple[list[float], int]] = {}
    for stamp, value in _OBSERVATION.findall(xml):
        if value == "NaN":
            continue
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(HELSINKI_TZ)
        seconds, minutes = days.get(moment.date(), ([0.0] * 48, 0))
        seconds[moment.hour * 2 + (moment.minute >= 30)] += float(value)
        days[moment.date()] = (seconds, minutes + 1)
    return days


def encode_day(seconds: list[float]) -> str:
    slots = seconds[FIRST_SLOT : FIRST_SLOT + SLOT_COUNT]
    return "".join(DIGITS[round(min(s / SLOT_SECONDS, 1.0) * 10)] for s in slots)


def fetch_observations(first: date, last: date) -> dict[date, tuple[list[float], int]]:
    """Observations for the Helsinki days first..last, inclusive."""
    found: dict[date, tuple[list[float], int]] = {}
    with httpx.Client(timeout=240.0, follow_redirects=True) as client:
        start = first
        while start <= last:
            end = min(start + timedelta(days=CHUNK_DAYS - 1), last)
            response = client.get(
                WFS_URL,
                params={
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "getFeature",
                    "storedquery_id": STORED_QUERY,
                    "fmisid": KUMPULA_STATION,
                    "parameters": "SUND_1MIN",
                    # A Helsinki day begins on the previous UTC date.
                    "starttime": f"{start - timedelta(days=1)}T21:00:00Z",
                    "endtime": f"{end}T23:59:00Z",
                },
            )
            response.raise_for_status()
            for day, observed in parse_observations(response.text).items():
                if start <= day <= end:  # the request's edges hold slivers of other days
                    found[day] = observed
            start = end + timedelta(days=1)
    return found


def read_history(path: Path = HISTORY_PATH) -> dict[str, str]:
    """{ISO date: slot digits} for every stored day."""
    if not path.exists():
        return {}
    return dict(line.split(",") for line in path.read_text().split())


def first_missing_day(history: dict[str, str]) -> date:
    if history:
        return date.fromisoformat(max(history)) + timedelta(days=1)
    return date(today().year, 1, 1)


def recent_days(history: dict[str, str]) -> dict[str, str]:
    """Every day after the stored history, including today so far."""
    first = first_missing_day(history)
    if first > today():
        return {}
    return {
        day.isoformat(): encode_day(seconds)
        for day, (seconds, _) in fetch_observations(first, today()).items()
    }


def extend_history(path: Path = HISTORY_PATH) -> int:
    """Append finished days to the history and return how many were added.

    Stops at the first incomplete day, so an outage is retried on the next run
    instead of being stored as a day without sun.
    """
    history = read_history(path)
    first = first_missing_day(history)
    last = today() - timedelta(days=1)
    if first > last:
        return 0
    observed = fetch_observations(first, last)
    added = 0
    day = first
    while day <= last and day in observed and observed[day][1] >= COMPLETE_DAY_MINUTES:
        history[day.isoformat()] = encode_day(observed[day][0])
        added += 1
        day += timedelta(days=1)
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{k},{history[k]}\n" for k in sorted(history)))
    return added

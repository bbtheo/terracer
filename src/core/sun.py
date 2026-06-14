#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from pysolar.solar import get_altitude, get_azimuth


HELSINKI_TZ = ZoneInfo("Europe/Helsinki")


@dataclass(frozen=True)
class SunPosition:
    altitude_deg: float
    azimuth_deg: float
    direction: np.ndarray


def _ensure_timezone(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=HELSINKI_TZ)
    return dt.astimezone(HELSINKI_TZ)


def sun_position(latitude: float, longitude: float, dt: datetime) -> SunPosition:
    localized = _ensure_timezone(dt)
    altitude = float(get_altitude(latitude, longitude, localized))
    azimuth = float(get_azimuth(latitude, longitude, localized))

    altitude_rad = np.deg2rad(altitude)
    azimuth_rad = np.deg2rad(azimuth)
    # Unit vector pointing from the ground toward the sun, in the same axis
    # order the project's geometry uses (geopandas/OBJ tiles): x=Easting,
    # y=Northing, z=Up. Azimuth is clockwise from north: 0°=N, 90°=E, 180°=S.
    direction = np.array(
        [
            np.sin(azimuth_rad) * np.cos(altitude_rad),  # X = Easting component
            np.cos(azimuth_rad) * np.cos(altitude_rad),  # Y = Northing component
            np.sin(altitude_rad),                        # Z = Up component
        ],
        dtype=float,
    )
    return SunPosition(altitude_deg=altitude, azimuth_deg=azimuth, direction=direction)

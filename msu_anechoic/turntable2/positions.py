"""Coordinate types used by the threaded turntable controller."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class YawPitch:
    """The turntable firmware's relative, internal position in degrees."""

    yaw: float
    pitch: float


@dataclasses.dataclass(frozen=True)
class PanTilt:
    """The regime-compensated physical position in degrees."""

    pan: float
    tilt: float

"""Conversions between turntable pan/tilt and antenna azimuth/elevation."""

import math
from typing import Literal

import pydantic

__all__ = ["Coordinate"]


def _turntable_to_antenna(
    *,
    turn_elevation_deg: float,
    turn_azimuth_deg: float,
) -> tuple[float, float]:
    """Convert absolute turntable pan/tilt to traditional azimuth/elevation."""
    turn_elevation_rad = math.radians(turn_elevation_deg)
    turn_azimuth_rad = math.radians(turn_azimuth_deg)
    x = math.cos(turn_elevation_rad) * math.cos(turn_azimuth_rad)
    y = math.sin(turn_azimuth_rad)
    z = math.sin(turn_elevation_rad) * math.cos(turn_azimuth_rad)
    return math.degrees(math.atan2(y, x)), math.degrees(math.asin(z))


def _antenna_to_turntable(
    trad_azimuth_deg: float,
    trad_elevation_deg: float,
) -> tuple[float, float]:
    """Convert traditional azimuth/elevation to absolute turntable pan/tilt."""
    theta = math.radians(trad_azimuth_deg)
    phi = math.radians(trad_elevation_deg)
    turntable_elevation = math.atan2(math.tan(phi), math.cos(theta))
    turntable_azimuth = math.atan2(
        math.sin(theta),
        math.cos(theta) / math.cos(turntable_elevation),
    )
    return math.degrees(turntable_azimuth), math.degrees(turntable_elevation)


class Coordinate(pydantic.BaseModel):
    """One physical direction represented in both supported reference frames.

    Turntable elevation is always the absolute tilt sent to the positioner.
    """

    antenna_azimuth: float
    antenna_elevation: float
    turntable_azimuth: float
    turntable_elevation: float
    kind: Literal["antenna", "turntable"]

    def __repr__(self) -> str:
        method = (
            self.__class__.__name__ + ".from_antenna"
            if self.kind == "antenna"
            else self.__class__.__name__ + ".from_turntable"
        )
        return f"{method}(azimuth={self.azimuth}, elevation={self.elevation})"

    def __str__(self) -> str:
        return f"<az={self.azimuth:+.1f}, el={self.elevation:+.1f} ({self.kind.capitalize()})>"

    @property
    def pan(self) -> float:
        return self.turntable_azimuth

    @property
    def tilt(self) -> float:
        return self.turntable_elevation

    @property
    def azimuth(self) -> float:
        return self.antenna_azimuth if self.kind == "antenna" else self.turntable_azimuth

    @property
    def elevation(self) -> float:
        return self.antenna_elevation if self.kind == "antenna" else self.turntable_elevation

    @property
    def azimuth_radians(self) -> float:
        return math.radians(self.azimuth)

    @property
    def elevation_radians(self) -> float:
        return math.radians(self.elevation)

    @property
    def azimuth_degrees(self) -> float:
        return self.azimuth

    @property
    def elevation_degrees(self) -> float:
        return self.elevation

    def as_kind(self, kind: Literal["antenna", "turntable"]) -> "Coordinate":
        return self.model_copy(update={"kind": kind})

    @classmethod
    def from_turntable(
        cls,
        *,
        azimuth: float,
        elevation: float,
    ) -> "Coordinate":
        """Create a coordinate from absolute turntable pan and tilt."""
        antenna_azimuth, antenna_elevation = _turntable_to_antenna(
            turn_elevation_deg=elevation,
            turn_azimuth_deg=azimuth,
        )
        return cls(
            antenna_azimuth=antenna_azimuth,
            antenna_elevation=antenna_elevation,
            turntable_azimuth=azimuth,
            turntable_elevation=elevation,
            kind="turntable",
        )

    @classmethod
    def from_antenna(
        cls,
        *,
        azimuth: float,
        elevation: float,
    ) -> "Coordinate":
        """Create a coordinate from traditional antenna azimuth/elevation."""
        turntable_azimuth, turntable_elevation = _antenna_to_turntable(
            trad_azimuth_deg=azimuth,
            trad_elevation_deg=elevation,
        )
        return cls(
            antenna_azimuth=azimuth,
            antenna_elevation=elevation,
            turntable_azimuth=turntable_azimuth,
            turntable_elevation=turntable_elevation,
            kind="antenna",
        )

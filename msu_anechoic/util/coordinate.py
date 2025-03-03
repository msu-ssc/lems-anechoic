import math
from typing import Literal

import pydantic

__all__ = ["Coordinate"]


def _turntable_to_antenna(
    *,
    turn_elevation_deg: float,
    turn_azimuth_deg: float,
) -> tuple[float, float]:
    """
    Convert turntable angles to traditional spherical coordinates.

    Parameters:
      turn_elevation_deg: the elevation rotation of the turntable (in degrees).
      turn_azimuth_deg: the azimuth rotation performed on the tilted plane (in degrees).

    Returns:
      A tuple (trad_azimuth_deg, trad_elevation_deg) representing the
      traditional azimuth (angle in the horizontal plane) and elevation (angle above horizontal).
    """
    # Convert degrees to radians
    turn_elevation_rad = math.radians(turn_elevation_deg)
    turn_azimuth_rad = math.radians(turn_azimuth_deg)

    # After the elevation rotation (about y by -E) and then azimuth rotation (about z by A),
    # the pointer vector becomes:
    #
    # v = R_y(-E) * (R_z(A) * [1, 0, 0])
    #
    # where R_z(A)*[1, 0, 0] = [cos(A), sin(A), 0] and
    # R_y(-E) rotates this vector to:
    x = math.cos(turn_elevation_rad) * math.cos(turn_azimuth_rad)
    y = math.sin(turn_azimuth_rad)
    z = math.sin(turn_elevation_rad) * math.cos(turn_azimuth_rad)

    # Compute traditional spherical angles:
    trad_azimuth_rad = math.atan2(y, x)  # azimuth: angle in x-y plane
    trad_elevation_rad = math.asin(z)  # elevation: arcsin(z) since |v| = 1

    # Convert results back to degrees
    trad_azimuth_deg = math.degrees(trad_azimuth_rad)
    trad_elevation_deg = math.degrees(trad_elevation_rad)

    return trad_azimuth_deg, trad_elevation_deg


def _antenna_to_turntable(trad_azimuth_deg: float, trad_elevation_deg: float) -> tuple[float, float]:
    """
    Convert traditional spherical coordinates (azimuth and elevation) to turntable coordinates.

    The traditional spherical coordinates are defined as:
      x = cos(φ)*cos(θ)
      y = cos(φ)*sin(θ)
      z = sin(φ)
    and are related to the turntable coordinates by:
      x = cos(E)*cos(A)
      y = sin(A)
      z = sin(E)*cos(A)

    Solving for the turntable angles:
      - Turntable elevation (E):
          tan E = tan(φ) / cos(θ)
          E = arctan(tan(φ)/cos(θ))
      - Turntable azimuth (A):
          tan A = cos(E) * tan(θ)
          A = atan2(sin(θ), cos(θ)/cos(E))

    Parameters:
      trad_azimuth_deg (float): Traditional azimuth (θ) in degrees.
      trad_elevation_deg (float): Traditional elevation (φ) in degrees.

    Returns:
      tuple[float, float]: (turntable_elevation_deg, turntable_azimuth_deg)
    """
    # Convert input angles from degrees to radians.
    theta: float = math.radians(trad_azimuth_deg)  # traditional azimuth θ
    phi: float = math.radians(trad_elevation_deg)  # traditional elevation φ

    # Compute turntable elevation E from:
    # tan(E) = tan(φ)/cos(θ)
    E: float = math.atan(math.tan(phi) / math.cos(theta))

    # Compute turntable azimuth A.
    # One robust way is to use the relation: tan A = cos(E)*tan(θ)
    # This is equivalent to:
    A: float = math.atan2(math.sin(theta), math.cos(theta) / math.cos(E))

    # Convert the results back to degrees.
    turntable_elevation_deg: float = math.degrees(E)
    turntable_azimuth_deg: float = math.degrees(A)

    return turntable_azimuth_deg, turntable_elevation_deg


class Coordinate(pydantic.BaseModel):
    """A spherical coordinate system with azimuth and elevation angles, in one of several reference frames.

    Do not instantiate this class directly. Instead, use the class methods to create instances.

    ```
    point = Coordinate.from_turntable(azimuth=45, elevation=30, neutral_elevation=0)
    point = Coordinate.from_absolute_turntable(azimuth=45, elevation=30, neutral_elevation=0)
    point = Coordinate.from_antenna(azimuth=45, elevation=30, neutral_elevation=0)
    ```

    The coordinate systems:
    - Antenna: Normal azimuth and elevation. Elevation is relative to the neutral elevation.
    - Turntable: The pan and tilt angles of the turntable. Elevation is relative to the neutral elevation.
    - Absolute turntable: The pan and tilt angles of the turntable. Elevation is relative to true level.

    "Neutral elevation" is the elevation angle at which the AUT is directly pointed at the radiating source.
    So it will be a positive number if the AUT is below the source and a negative number if the AUT is above the source.

    NOTE: All angles in degrees.
    """

    antenna_azimuth: float
    """The azimuth angle of the antenna, in traditional spherical coordinates, where the (0, 0) point is the vector pointing directly from the AUT to the source."""

    antenna_elevation: float
    """The elevation angle of the antenna, in traditional spherical coordinates, where the (0, 0) point is the vector pointing directly from the AUT to the source."""

    turntable_azimuth: float
    """The azimuth angle of the turntable, AKA the "pan" angle, where the (0, 0) point is the vector pointing directly from the AUT to the source.
    
    NOTE: This does NOT have the same meaning as the normal use of the word "azimuth"."""

    turntable_elevation: float
    """The elevation angle of the turntable, AKA the "tilt" angle, where the (0, 0) point is the vector pointing directly from the AUT to the source.

    NOTE: This does NOT have the same meaning as the normal use of the word "elevation"."""

    absolute_turntable_azimuth: float
    """The azimuth angle of the turntable, AKA the "pan" angle, where the (0, 0) point is the vector whose azimuth points directly from the AUT to the source, and whose
    elevation is level (with respect to gravity).
    
    NOTE: This does NOT have the same meaning as the normal use of the word "azimuth"."""

    absolute_turntable_elevation: float
    """The elevation angle of the turntable, AKA the "tilt" angle, where the (0, 0) point is the vector whose azimuth points directly from the AUT to the source, and whose
    elevation is level (with respect to gravity).

    NOTE: This does NOT have the same meaning as the normal use of the word "elevation"."""

    neutral_elevation: float
    """The elevation angle at which the AUT is directly pointed at the radiating source.
    
    Should be a positive number if the AUT is below the source and a negative number if the AUT is above the source."""

    kind: Literal[
        "antenna",
        "turntable",
        "absolute_turntable",
    ]
    """What was the original source of the coordinate."""

    def __str__(self):
        kind_str = self.kind.replace("_", " ").capitalize()
        return f"<az={self.azimuth:+.1f}, el={self.elevation:+.1f} ({kind_str})>"

    @property
    def pan(self) -> float:
        """The pan angle of the turntable. This is an alias to the `turntable_azimuth` field."""
        return self.turntable_azimuth

    @property
    def tilt(self) -> float:
        """The tilt angle of the turntable. This is an alias to the `turntable_elevation` field."""
        return self.turntable_elevation

    @property
    def azimuth(self) -> float:
        if self.kind == "antenna":
            return self.antenna_azimuth
        elif self.kind == "turntable":
            return self.turntable_azimuth
        elif self.kind == "absolute_turntable":
            return self.absolute_turntable_azimuth
        else:
            raise ValueError(f"Invalid kind: {self.kind}")

    @property
    def elevation(self) -> float:
        if self.kind == "antenna":
            return self.antenna_elevation
        elif self.kind == "turntable":
            return self.turntable_elevation
        elif self.kind == "absolute_turntable":
            return self.absolute_turntable_elevation
        else:
            raise ValueError(f"Invalid kind: {self.kind}")

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

    def as_kind(self, kind: Literal["antenna", "turntable", "absolute_turntable"]) -> "Coordinate":
        """Convert the coordinate to a different kind."""
        return Coordinate(
            antenna_azimuth=self.antenna_azimuth,
            antenna_elevation=self.antenna_elevation,
            turntable_azimuth=self.turntable_azimuth,
            turntable_elevation=self.turntable_elevation,
            absolute_turntable_azimuth=self.absolute_turntable_azimuth,
            absolute_turntable_elevation=self.absolute_turntable_elevation,
            neutral_elevation=self.neutral_elevation,
            kind=kind,
        )

    @classmethod
    def from_turntable(
        cls,
        *,
        azimuth: float,
        elevation: float,
        neutral_elevation: float = 0.0,
    ):
        """Create a TurntableLocation instance from turntable coordinates."""
        absolute_turntable_azimuth = azimuth
        absolute_turntable_elevation = elevation + neutral_elevation

        antenna_azimuth, antenna_elevation = _turntable_to_antenna(
            turn_elevation_deg=elevation,
            turn_azimuth_deg=azimuth,
        )

        return cls(
            antenna_azimuth=antenna_azimuth,
            antenna_elevation=antenna_elevation,
            turntable_azimuth=azimuth,
            turntable_elevation=elevation,
            absolute_turntable_azimuth=absolute_turntable_azimuth,
            absolute_turntable_elevation=absolute_turntable_elevation,
            neutral_elevation=neutral_elevation,
            kind="turntable",
        )

    @classmethod
    def from_absolute_turntable(
        cls,
        *,
        azimuth: float,
        elevation: float,
        neutral_elevation: float = 0.0,
    ):
        """Create a TurntableLocation instance from absolute turntable coordinates."""
        turntable_azimuth = azimuth
        turntable_elevation = elevation - neutral_elevation

        antenna_azimuth, antenna_elevation = _turntable_to_antenna(
            turn_elevation_deg=turntable_elevation,
            turn_azimuth_deg=turntable_azimuth,
        )

        return cls(
            antenna_azimuth=antenna_azimuth,
            antenna_elevation=antenna_elevation,
            turntable_azimuth=turntable_azimuth,
            turntable_elevation=turntable_elevation,
            absolute_turntable_azimuth=azimuth,
            absolute_turntable_elevation=elevation,
            neutral_elevation=neutral_elevation,
            kind="absolute_turntable",
        )

    @classmethod
    def from_antenna(
        cls,
        *,
        azimuth: float,
        elevation: float,
        neutral_elevation: float = 0.0,
    ):
        """Create a TurntableLocation instance from antenna coordinates."""
        turntable_azimuth, turntable_elevation = _antenna_to_turntable(
            trad_azimuth_deg=azimuth,
            trad_elevation_deg=elevation,
        )

        absolute_turntable_azimuth = turntable_azimuth
        absolute_turntable_elevation = turntable_elevation + neutral_elevation

        return cls(
            antenna_azimuth=azimuth,
            antenna_elevation=elevation,
            turntable_azimuth=turntable_azimuth,
            turntable_elevation=turntable_elevation,
            absolute_turntable_azimuth=absolute_turntable_azimuth,
            absolute_turntable_elevation=absolute_turntable_elevation,
            neutral_elevation=neutral_elevation,
            kind="antenna",
        )


if __name__ == "__main__":
    # Create a TurntableLocation instance with spherical coordinates
    turntable_location = Coordinate(
        antenna_azimuth=45.0,
        antenna_elevation=30.0,
        turntable_azimuth=45.0,
        turntable_elevation=30.0,
        absolute_antenna_azimuth=45.0,
        absolute_antenna_elevation=30.0,
        absolute_turntable_azimuth=45.0,
        absolute_turntable_elevation=30.0,
        neutral_elevation=0.0,
        kind="antenna",
    )

    turntable_location = Coordinate.from_turntable(
        azimuth=45,
        elevation=45,
        neutral_elevation=3.75,
    )

    absolute_turntable_location = Coordinate.from_absolute_turntable(
        azimuth=45,
        elevation=45,
        neutral_elevation=3.75,
    )

    antenna_location = Coordinate.from_antenna(
        azimuth=45,
        elevation=45,
        neutral_elevation=3.75,
    )

    print(f"{turntable_location=!s}")
    # print(f"{turntable_location=!r}")

    print(f"{absolute_turntable_location=!s}")
    # print(f"{absolute_turntable_location=!r}")

    print(f"{antenna_location=!s}")
    # print(f"{antenna_location=!r}")
    # print(turntable_location.model_dump_json(indent=4))

    point1 = Coordinate.from_antenna(azimuth=45, elevation=35, neutral_elevation=5)
    point2 = Coordinate.from_turntable(
        azimuth=point1.turntable_azimuth,
        elevation=point1.turntable_elevation,
        neutral_elevation=point1.neutral_elevation,
    )
    print(f"---------")
    print(f"{point1=!s}")
    print(f"{point1.as_kind('antenna')           =!s}")
    print(f"{point1.as_kind('turntable')         =!s}")
    print(f"{point1.as_kind('absolute_turntable')=!s}")
    print(f"---------")
    print(f"{point2=!s}")
    print(f"{point2.as_kind('antenna')           =!s}")
    print(f"{point2.as_kind('turntable')         =!s}")
    print(f"{point2.as_kind('absolute_turntable')=!s}")

    print(f"{point1.model_dump_json(indent=4)}")

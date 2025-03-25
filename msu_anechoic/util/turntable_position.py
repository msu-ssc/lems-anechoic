import functools
import math

import pydantic


class TurntablePosition(pydantic.BaseModel):
    """
    A position of the turntable in the anechoic chamber.

    All angles are in RADIANS
    """

    azimuth: float
    elevation: float
    tilt: float
    pan: float

    model_config = pydantic.ConfigDict(frozen=True)

    @property
    @functools.lru_cache
    def azimuth_deg(self) -> float:
        return math.degrees(self.azimuth)

    @property
    @functools.lru_cache
    def elevation_deg(self) -> float:
        return math.degrees(self.elevation)

    @property
    @functools.lru_cache
    def tilt_deg(self) -> float:
        return math.degrees(self.tilt)

    @property
    @functools.lru_cache
    def pan_deg(self) -> float:
        return math.degrees(self.pan)

    @property
    @functools.lru_cache
    def azimuth_rad(self) -> float:
        return self.azimuth

    @property
    @functools.lru_cache
    def elevation_rad(self) -> float:
        return self.elevation

    @property
    @functools.lru_cache
    def tilt_rad(self) -> float:
        return self.tilt

    @property
    @functools.lru_cache
    def pan_rad(self) -> float:
        return self.pan

    def __format__(self, format_spec: str):
        """
        Include 'd' for degrees (default), or 'r' for radians.
        Include 'a' for azimuth and elevation, or 't' for tilt and pan.
        Everything else will go to formatting the floats
        so 'da0.3f' would format the object as "(az=45.000, el=30.000)"
        """

        def _parse_deg(format_spec: str) -> tuple[bool, str]:
            use_deg = True
            if "d" in format_spec:
                format_spec = format_spec.replace("d", "")
            elif "r" in format_spec:
                use_deg = False
                format_spec = format_spec.replace("r", "")
            return use_deg, format_spec

        def _parse_tilt_pan(format_spec: str) -> tuple[bool, str]:
            use_tilt_pan = False
            if "a" in format_spec:
                format_spec = format_spec.replace("a", "")
            elif "t" in format_spec:
                use_tilt_pan = True
                format_spec = format_spec.replace("t", "")
            return use_tilt_pan, format_spec

        use_deg, format_spec = _parse_deg(format_spec)
        use_tilt_pan, format_spec = _parse_tilt_pan(format_spec)

        if not format_spec:
            if use_deg:
                format_spec = "+0.1f"
            else:
                format_spec = "+0.3f"

        if use_deg:
            angle_string = "°"
            if use_tilt_pan:
                tilt = self.tilt_deg
                pan = self.pan_deg
                return f"(tilt={tilt:{format_spec}}{angle_string}, pan={pan:{format_spec}}{angle_string})"
            else:
                azimuth = self.azimuth_deg
                elevation = self.elevation_deg
                return f"(az={azimuth:{format_spec}}{angle_string}, el={elevation:{format_spec}}{angle_string})"
        else:
            angle_string = " rad"
            if use_tilt_pan:
                tilt = self.tilt_rad
                pan = self.pan_rad
                return f"(tilt={tilt:{format_spec}}{angle_string}, pan={pan:{format_spec}}{angle_string})"
            else:
                azimuth = self.azimuth_rad
                elevation = self.elevation_rad
                return f"(az={azimuth:{format_spec}}{angle_string}, el={elevation:{format_spec}}{angle_string})"

    def __str__(self):
        return format(self, "da+0.1f")

    @classmethod
    def from_az_el(
        cls,
        *,
        azimuth_deg: float | None = None,
        azimuth_rad: float | None = None,
        elevation_deg: float | None = None,
        elevation_rad: float | None = None,
    ) -> "TurntablePosition":
        """
        Create a TurntablePosition object from azimuth and elevation angles
        """
        azimuths_given = [azimuth_deg, azimuth_rad].count(None) == 1
        if azimuths_given != 1:
            raise ValueError("Exactly one of azimuth_deg or azimuth_rad must be provided")

        elevations_given = [elevation_deg, elevation_rad].count(None) == 1
        if elevations_given != 1:
            raise ValueError("Exactly one of elevation_deg or elevation_rad must be provided")

        if azimuth_rad is not None:
            azimuth = azimuth_rad
        else:
            azimuth = math.radians(azimuth_deg)

        if elevation_rad is not None:
            elevation = elevation_rad
        else:
            elevation = math.radians(elevation_deg)

        tilt, pan = _tilt_pan_from_az_el(azimuth_rad=azimuth, elevation_rad=elevation)

        return cls(azimuth=azimuth, elevation=elevation, tilt=tilt, pan=pan)

    @classmethod
    def from_tilt_pan(
        cls,
        *,
        tilt_deg: float | None = None,
        tilt_rad: float | None = None,
        pan_deg: float | None = None,
        pan_rad: float | None = None,
    ) -> "TurntablePosition":
        """
        Create a TurntablePosition object from tilt and pan angles
        """
        tilts_given = [tilt_deg, tilt_rad].count(None) == 1
        if tilts_given != 1:
            raise ValueError("Exactly one of tilt_deg or tilt_rad must be provided")

        pans_given = [pan_deg, pan_rad].count(None) == 1
        if pans_given != 1:
            raise ValueError("Exactly one of pan_deg or pan_rad must be provided")

        if tilt_rad is not None:
            tilt = tilt_rad
        else:
            tilt = math.radians(tilt_deg)

        if pan_rad is not None:
            pan = pan_rad
        else:
            pan = math.radians(pan_deg)

        azimuth, elevation = _az_el_from_tilt_pan(tilt_rad=tilt, pan_rad=pan)

        return cls(azimuth=azimuth, elevation=elevation, tilt=tilt, pan=pan)

    def xyz(self, radius: float = 1) -> tuple[float, float, float]:
        x = radius * math.cos(self.elevation) * math.cos(self.azimuth)
        y = radius * math.cos(self.elevation) * math.sin(self.azimuth)
        z = radius * math.sin(self.elevation)
        return x, y, z


# def _tilt_pan_from_az_el(azimuth: float, elevation: float) -> tuple[float, float]:
#     """
#     Placeholder function to calculate tilt and pan from azimuth and elevation.
#     Replace this with the actual implementation.
#     """
#     tilt = 0.0  # Example value
#     pan = 0.0  # Example value
#     return tilt, pan


def _tilt_pan_from_az_el(*, azimuth_rad: float, elevation_rad: float) -> tuple[float, float]:
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
    theta: float = azimuth_rad  # traditional azimuth θ
    phi: float = elevation_rad  # traditional elevation φ

    # Compute turntable elevation E from:
    # tan(E) = tan(φ)/cos(θ)
    E: float = math.atan(math.tan(phi) / math.cos(theta))

    # Compute turntable azimuth A.
    # One robust way is to use the relation: tan A = cos(E)*tan(θ)
    # This is equivalent to:
    A: float = math.atan2(math.sin(theta), math.cos(theta) / math.cos(E))

    # Convert the results back to degrees.
    tilt_rad: float = E
    pan_rad: float = A

    return tilt_rad, pan_rad


def _az_el_from_tilt_pan(
    *,
    tilt_rad: float,
    pan_rad: float,
) -> tuple[float, float]:
    # Convert degrees to radians
    # After the elevation rotation (about y by -E) and then azimuth rotation (about z by A),
    # the pointer vector becomes:
    #
    # v = R_y(-E) * (R_z(A) * [1, 0, 0])
    #
    # where R_z(A)*[1, 0, 0] = [cos(A), sin(A), 0] and
    # R_y(-E) rotates this vector to:
    x = math.cos(tilt_rad) * math.cos(pan_rad)
    y = math.sin(pan_rad)
    z = math.sin(tilt_rad) * math.cos(pan_rad)

    # Compute traditional spherical angles:
    azimuth_rad = math.atan2(y, x)  # azimuth: angle in x-y plane
    elevation_rad = math.asin(z)  # elevation: arcsin(z) since |v| = 1

    # # Convert results back to degrees
    # trad_azimuth_deg = math.degrees(trad_azimuth_rad)
    # trad_elevation_deg = math.degrees(trad_elevation_rad)

    return azimuth_rad, elevation_rad


if __name__ == "__main__":
    # Example usage
    # pos1 = TurntablePosition.from_az_el(azimuth_deg=-45, elevation_deg=-30)
    pos2 = TurntablePosition.from_tilt_pan(tilt_deg=-30, pan_deg=-60)

    for pos in [
        # pos1,
        pos2,
    ]:
        print("************************************")
        print(pos)

        print(f"{pos=!r}")
        print(f"{pos=:td}")
        print(f"{pos=:tr}")
        print(f"{pos=:ad}")
        print(f"{pos=:ar}")

        print(f"{pos.azimuth=}")
        print(f"{pos.elevation=}")
        print(f"{pos.tilt=}")
        print(f"{pos.pan=}")

        print(f"{pos.azimuth_deg=}")
        print(f"{pos.elevation_deg=}")
        print(f"{pos.tilt_deg=}")
        print(f"{pos.pan_deg=}")

        print(f"{pos.azimuth_rad=}")
        print(f"{pos.elevation_rad=}")
        print(f"{pos.tilt_rad=}")
        print(f"{pos.pan_rad=}")

        print(pos.model_dump_json(indent=2))

    from matplotlib import pyplot as plt  # noqa: I001
    import numpy as np

    fig, ax = plt.subplots(subplot_kw={"projection": "3d"})
    ax.set_box_aspect([1, 1, 1])

    points: list[tuple[float, float, float]] = []

    tilt_or_el_degs = np.linspace(-30, 30, 11)
    pan_or_az_degs = np.linspace(-150, 150, 21)
    rev = False
    for tilt_or_el_deg in tilt_or_el_degs:
        pan_or_az_degs = list(reversed(pan_or_az_degs))
        for pan_or_az_deg in pan_or_az_degs:
            pos = TurntablePosition.from_az_el(elevation_deg=tilt_or_el_deg, azimuth_deg=pan_or_az_deg)
            # pos = TurntablePosition.from_tilt_pan(tilt_deg=tilt_or_el_deg, pan_deg=pan_or_az_deg)
            x, y, z = pos.xyz()
            points.append((x, y, z))
            # ax.plot([0, x], [0, y], [0, z], color="gray", linewidth=0.5)
            color = "blue"
            if pos.tilt_deg > 45 or pos.tilt_deg < -90:
                color = "red"
            print(f"{pos:td}: {color}")

            # if color != "red":
            ax.scatter(x, y, z, marker="o", color=color)

    x, y, z = zip(*points)
    # ax.plot(x, y, z)
    ax.set_xlim(-1.5, 1.5)
    ax.set_ylim(-1.5, 1.5)
    ax.set_zlim(-1.5, 1.5)
    plt.show()

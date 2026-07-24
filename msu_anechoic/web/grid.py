"""Framework-independent grid generation and coordinate conversion.

The conversions in this module intentionally do not use the repository's
legacy coordinate classes.  They describe a direction vector using either:

* conventional azimuth/elevation, or
* pan/tilt rotations, with tilt followed by pan about the tilted axis.

All public angles are expressed in degrees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from decimal import InvalidOperation
from typing import Literal

CoordinateSystem = Literal["az_el", "pan_tilt"]
MAX_GRID_POINTS = 10_000
MAX_TURNTABLE_TILT = 45.0
_ZERO_TOLERANCE = 1e-12


class GridValidationError(ValueError):
    """Raised when a requested grid cannot be generated."""


@dataclass(frozen=True)
class AxisDefinition:
    minimum: float
    maximum: float
    step: float


@dataclass(frozen=True)
class GridPoint:
    traversal_index: int
    row: int
    column: int
    azimuth: float
    elevation: float
    pan: float
    tilt: float


@dataclass(frozen=True)
class DesignedGrid:
    input_system: CoordinateSystem
    horizontal_values: tuple[float, ...]
    vertical_values: tuple[float, ...]
    points: tuple[GridPoint, ...]

    @property
    def row_count(self) -> int:
        return len(self.vertical_values)

    @property
    def column_count(self) -> int:
        return len(self.horizontal_values)


def _clean_angle(value: float) -> float:
    """Remove floating-point noise while preserving useful precision."""
    if abs(value) < _ZERO_TOLERANCE:
        return 0.0
    if abs(abs(value) - 180.0) < _ZERO_TOLERANCE:
        return math.copysign(180.0, value)
    return value


def _normalize_longitude(value: float) -> float:
    normalized = (value + 180.0) % 360.0 - 180.0
    if normalized == -180.0 and value > 0:
        return 180.0
    return _clean_angle(normalized)


def az_el_to_pan_tilt(azimuth: float, elevation: float) -> tuple[float, float]:
    """Convert conventional azimuth/elevation to pan/tilt.

    The conversion goes through a unit direction vector.  The returned tilt is
    the principal value in [-90, 90], while pan is in [-180, 180].
    """
    azimuth_rad = math.radians(azimuth)
    elevation_rad = math.radians(elevation)

    x = math.cos(elevation_rad) * math.cos(azimuth_rad)
    y = math.cos(elevation_rad) * math.sin(azimuth_rad)
    z = math.sin(elevation_rad)

    cos_pan_magnitude = math.hypot(x, z)
    if cos_pan_magnitude < _ZERO_TOLERANCE:
        # At this singularity, tilt is immaterial; choose a stable principal
        # representation that preserves the direction.
        pan = math.copysign(90.0, y)
        tilt = 0.0
    else:
        cos_pan_sign = -1.0 if x < -_ZERO_TOLERANCE else 1.0
        signed_cos_pan = cos_pan_sign * cos_pan_magnitude
        pan = math.degrees(math.atan2(y, signed_cos_pan))
        tilt = math.degrees(math.atan2(z * cos_pan_sign, x * cos_pan_sign))

    return _normalize_longitude(pan), _clean_angle(tilt)


def pan_tilt_to_az_el(pan: float, tilt: float) -> tuple[float, float]:
    """Convert pan/tilt rotations to conventional azimuth/elevation."""
    pan_rad = math.radians(pan)
    tilt_rad = math.radians(tilt)

    x = math.cos(tilt_rad) * math.cos(pan_rad)
    y = math.sin(pan_rad)
    z = math.sin(tilt_rad) * math.cos(pan_rad)

    azimuth = math.degrees(math.atan2(y, x))
    elevation = math.degrees(math.atan2(z, math.hypot(x, y)))
    return _normalize_longitude(azimuth), _clean_angle(elevation)


def axis_values(axis: AxisDefinition, *, label: str) -> tuple[float, ...]:
    """Return inclusive, evenly spaced values for an axis."""
    try:
        minimum = Decimal(str(axis.minimum))
        maximum = Decimal(str(axis.maximum))
        step = Decimal(str(axis.step))
    except InvalidOperation as exc:
        raise GridValidationError(f"{label} values must be finite numbers.") from exc

    if not all(math.isfinite(value) for value in (axis.minimum, axis.maximum, axis.step)):
        raise GridValidationError(f"{label} values must be finite numbers.")
    if step <= 0:
        raise GridValidationError(f"{label} step size must be greater than zero.")
    if maximum < minimum:
        raise GridValidationError(f"{label} maximum must be greater than or equal to its minimum.")

    span = maximum - minimum
    full_step_count = int(span // step)
    values = [minimum + step * index for index in range(full_step_count + 1)]
    if not values or values[-1] != maximum:
        values.append(maximum)
    return tuple(float(value) for value in values)


def design_grid(
    *,
    input_system: CoordinateSystem,
    horizontal: AxisDefinition,
    vertical: AxisDefinition,
    reject_inaccessible: bool = False,
) -> DesignedGrid:
    """Create a top-left, horizontal-first serpentine grid."""
    if input_system not in ("az_el", "pan_tilt"):
        raise GridValidationError("Select either azimuth/elevation or pan/tilt input.")

    horizontal_label = "Azimuth" if input_system == "az_el" else "Pan"
    vertical_label = "Elevation" if input_system == "az_el" else "Tilt"
    horizontal_values = axis_values(horizontal, label=horizontal_label)
    vertical_values = axis_values(vertical, label=vertical_label)

    point_count = len(horizontal_values) * len(vertical_values)
    if point_count > MAX_GRID_POINTS:
        raise GridValidationError(
            f"This grid contains {point_count:,} points; the designer limit is {MAX_GRID_POINTS:,}."
        )

    points: list[GridPoint] = []
    # Plot coordinates increase upward, so top-left means maximum vertical and
    # minimum horizontal. Alternate horizontal direction on every row.
    for row, vertical_value in enumerate(reversed(vertical_values)):
        row_horizontal_values = horizontal_values if row % 2 == 0 else tuple(reversed(horizontal_values))
        for traversal_column, horizontal_value in enumerate(row_horizontal_values):
            if input_system == "az_el":
                azimuth = horizontal_value
                elevation = vertical_value
                pan, tilt = az_el_to_pan_tilt(azimuth, elevation)
            else:
                pan = horizontal_value
                tilt = vertical_value
                azimuth, elevation = pan_tilt_to_az_el(pan, tilt)

            if reject_inaccessible and tilt > MAX_TURNTABLE_TILT + _ZERO_TOLERANCE:
                continue

            points.append(
                GridPoint(
                    traversal_index=len(points) + 1,
                    row=row,
                    column=traversal_column,
                    azimuth=azimuth,
                    elevation=elevation,
                    pan=pan,
                    tilt=tilt,
                )
            )

    if reject_inaccessible and not points:
        raise GridValidationError(
            "No accessible points remain after applying the +45° turntable tilt limit."
        )

    return DesignedGrid(
        input_system=input_system,
        horizontal_values=horizontal_values,
        vertical_values=vertical_values,
        points=tuple(points),
    )

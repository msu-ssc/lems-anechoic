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
from dataclasses import replace
from decimal import ROUND_HALF_UP
from decimal import Decimal
from decimal import InvalidOperation
from typing import Literal

CoordinateSystem = Literal["az_el", "pan_tilt"]
MAX_GRID_POINTS = 10_000
MAX_TURNTABLE_TILT = 45.0
DUPLICATE_TOLERANCE = 0.1
_ZERO_TOLERANCE = 1e-12


class GridValidationError(ValueError):
    """Raised when a requested grid cannot be generated."""


@dataclass(frozen=True)
class AxisDefinition:
    minimum: float
    maximum: float
    step: float


@dataclass(frozen=True)
class QuantizationDefinition:
    enabled: bool = False
    origin: float = 0.0
    step: float = 0.5


@dataclass(frozen=True)
class SimpleGridDefinition:
    horizontal: AxisDefinition
    vertical: AxisDefinition
    cosine_correct_azimuth_spacing: bool = False
    stagger_alternate_elevation_rows: bool = False
    equal_area_pan_spacing: bool = False
    stagger_alternate_tilt_rows: bool = False


@dataclass(frozen=True)
class GridPoint:
    traversal_index: int
    row: int
    column: int
    ideal_azimuth: float
    ideal_elevation: float
    ideal_pan: float
    ideal_tilt: float
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
        return max((point.row for point in self.points), default=-1) + 1

    @property
    def column_count(self) -> int:
        if not self.points:
            return 0
        counts: dict[int, int] = {}
        for point in self.points:
            counts[point.row] = counts.get(point.row, 0) + 1
        return max(counts.values())


@dataclass(frozen=True)
class _CandidatePoint:
    point: GridPoint
    logical_vertical: float


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


def _regular_values_within_bounds(
    axis: AxisDefinition,
    *,
    step: float,
    offset: float = 0.0,
) -> tuple[float, ...]:
    """Generate regular values without appending a short final interval."""
    minimum = Decimal(str(axis.minimum))
    maximum = Decimal(str(axis.maximum))
    decimal_step = Decimal(str(step))
    start = minimum + Decimal(str(offset))
    if start > maximum:
        return (float(minimum),)
    count = int((maximum - start) // decimal_step)
    return tuple(float(start + decimal_step * index) for index in range(count + 1))


def _azimuth_values_for_elevation(
    grid: SimpleGridDefinition,
    *,
    elevation: float,
    row_index: int,
    validated_values: tuple[float, ...],
) -> tuple[float, ...]:
    if not (
        grid.cosine_correct_azimuth_spacing
        or grid.stagger_alternate_elevation_rows
    ):
        return validated_values
    if abs(abs(elevation) - 90.0) < _ZERO_TOLERANCE:
        return ((grid.horizontal.minimum + grid.horizontal.maximum) / 2.0,)

    effective_step = grid.horizontal.step
    if grid.cosine_correct_azimuth_spacing:
        effective_step /= abs(math.cos(math.radians(elevation)))
    offset = (
        effective_step / 2.0
        if grid.stagger_alternate_elevation_rows and row_index % 2 == 1
        else 0.0
    )
    return _regular_values_within_bounds(
        grid.horizontal,
        step=effective_step,
        offset=offset,
    )


def _equal_area_pan_coordinate(pan: float) -> float:
    """Map pan in degrees to a monotonic integral of ``abs(cos(pan))``."""
    pan_radians = math.radians(pan)
    segment = math.floor((pan_radians + math.pi / 2.0) / math.pi)
    remainder = pan_radians + math.pi / 2.0 - segment * math.pi
    return 2.0 * segment - math.cos(remainder)


def _pan_from_equal_area_coordinate(coordinate: float) -> float:
    """Invert :func:`_equal_area_pan_coordinate`."""
    segment = math.floor((coordinate + 1.0) / 2.0)
    cosine_remainder = max(-1.0, min(1.0, 2.0 * segment - coordinate))
    remainder = math.acos(cosine_remainder)
    pan_radians = -math.pi / 2.0 + segment * math.pi + remainder
    return math.degrees(pan_radians)


def _pan_values_for_tilt(
    grid: SimpleGridDefinition,
    *,
    row_index: int,
    validated_values: tuple[float, ...],
) -> tuple[float, ...]:
    if not (
        grid.equal_area_pan_spacing
        or grid.stagger_alternate_tilt_rows
    ):
        return validated_values

    staggered = grid.stagger_alternate_tilt_rows and row_index % 2 == 1
    if not grid.equal_area_pan_spacing:
        return _regular_values_within_bounds(
            grid.horizontal,
            step=grid.horizontal.step,
            offset=grid.horizontal.step / 2.0 if staggered else 0.0,
        )

    minimum = _equal_area_pan_coordinate(grid.horizontal.minimum)
    maximum = _equal_area_pan_coordinate(grid.horizontal.maximum)
    step = _equal_area_pan_coordinate(grid.horizontal.step)
    start = minimum + (step / 2.0 if staggered else 0.0)
    if start > maximum:
        return (grid.horizontal.minimum,)
    count = math.floor((maximum - start) / step + 1e-12)
    return tuple(
        _pan_from_equal_area_coordinate(start + step * index)
        for index in range(count + 1)
    )


def _is_pan_singularity(pan: float) -> bool:
    return abs(math.cos(math.radians(pan))) < _ZERO_TOLERANCE


def quantize_angle(
    value: float,
    definition: QuantizationDefinition,
    *,
    label: str,
) -> float:
    """Round an angle to the nearest ``origin + N * step`` lattice point."""
    if not definition.enabled:
        return value
    if not all(math.isfinite(number) for number in (value, definition.origin, definition.step)):
        raise GridValidationError(f"{label} quantization values must be finite numbers.")
    if definition.step <= 0:
        raise GridValidationError(f"{label} quantization step size must be greater than zero.")

    value_decimal = Decimal(str(value))
    origin_decimal = Decimal(str(definition.origin))
    step_decimal = Decimal(str(definition.step))
    multiple = ((value_decimal - origin_decimal) / step_decimal).to_integral_value(
        rounding=ROUND_HALF_UP
    )
    return _clean_angle(float(origin_decimal + multiple * step_decimal))


def _specified_coordinates(
    point: GridPoint,
    input_system: CoordinateSystem,
) -> tuple[float, float]:
    if input_system == "az_el":
        return point.azimuth, point.elevation
    return point.pan, point.tilt


def _angular_distance(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _points_are_duplicates(
    left: GridPoint,
    right: GridPoint,
    input_system: CoordinateSystem,
) -> bool:
    left_x, left_y = _specified_coordinates(left, input_system)
    right_x, right_y = _specified_coordinates(right, input_system)
    return (
        _angular_distance(left_x, right_x) <= DUPLICATE_TOLERANCE + _ZERO_TOLERANCE
        and abs(left_y - right_y) <= DUPLICATE_TOLERANCE + _ZERO_TOLERANCE
    )


def _remove_duplicate_candidates(
    candidates: list[_CandidatePoint],
    input_system: CoordinateSystem,
) -> list[_CandidatePoint]:
    unique: list[_CandidatePoint] = []
    buckets: dict[tuple[int, int], list[_CandidatePoint]] = {}
    horizontal_bin_count = round(360.0 / DUPLICATE_TOLERANCE)

    for candidate in candidates:
        x, y = _specified_coordinates(candidate.point, input_system)
        normalized_x = (x + 180.0) % 360.0
        x_bin = math.floor(normalized_x / DUPLICATE_TOLERANCE) % horizontal_bin_count
        y_bin = math.floor(y / DUPLICATE_TOLERANCE)
        duplicate = False
        for x_offset in (-1, 0, 1):
            neighbor_x = (x_bin + x_offset) % horizontal_bin_count
            for y_offset in (-1, 0, 1):
                for existing in buckets.get((neighbor_x, y_bin + y_offset), ()):
                    if _points_are_duplicates(
                        candidate.point,
                        existing.point,
                        input_system,
                    ):
                        duplicate = True
                        break
                if duplicate:
                    break
            if duplicate:
                break
        if duplicate:
            continue

        unique.append(candidate)
        buckets.setdefault((x_bin, y_bin), []).append(candidate)
    return unique


def _route_candidates(
    candidates: list[_CandidatePoint],
    input_system: CoordinateSystem,
) -> tuple[GridPoint, ...]:
    candidates.sort(key=lambda candidate: candidate.logical_vertical, reverse=True)
    rows: list[tuple[float, list[_CandidatePoint]]] = []
    for candidate in candidates:
        matching_row = next(
            (
                row
                for row in rows
                if abs(row[0] - candidate.logical_vertical)
                <= DUPLICATE_TOLERANCE + _ZERO_TOLERANCE
            ),
            None,
        )
        if matching_row is None:
            rows.append((candidate.logical_vertical, [candidate]))
        else:
            matching_row[1].append(candidate)

    routed: list[GridPoint] = []
    previous_point: GridPoint | None = None
    for row_index, (_, row_candidates) in enumerate(rows):
        row_candidates.sort(
            key=lambda candidate: _specified_coordinates(
                candidate.point,
                input_system,
            )[0]
        )
        if previous_point is not None and len(row_candidates) > 1:
            previous_x, previous_y = _specified_coordinates(
                previous_point,
                input_system,
            )

            def endpoint_distance(candidate: _CandidatePoint) -> float:
                x, y = _specified_coordinates(candidate.point, input_system)
                return math.hypot(_angular_distance(x, previous_x), y - previous_y)

            if endpoint_distance(row_candidates[-1]) < endpoint_distance(row_candidates[0]):
                row_candidates.reverse()

        for column, candidate in enumerate(row_candidates):
            point = replace(
                candidate.point,
                traversal_index=len(routed) + 1,
                row=row_index,
                column=column,
            )
            routed.append(point)
            previous_point = point
    return tuple(routed)


def design_combined_grid(
    *,
    input_system: CoordinateSystem,
    grids: tuple[SimpleGridDefinition, ...],
    reject_inaccessible: bool = False,
    pan_quantization: QuantizationDefinition = QuantizationDefinition(),
    tilt_quantization: QuantizationDefinition = QuantizationDefinition(),
) -> DesignedGrid:
    """Combine simple grids, remove duplicates, and route them row by row."""
    if input_system not in ("az_el", "pan_tilt"):
        raise GridValidationError("Select either azimuth/elevation or pan/tilt input.")
    if not grids:
        raise GridValidationError("Add at least one simple grid.")

    horizontal_label = "Azimuth" if input_system == "az_el" else "Pan"
    vertical_label = "Elevation" if input_system == "az_el" else "Tilt"
    horizontal_value_set: set[float] = set()
    vertical_value_set: set[float] = set()
    expanded_grids: list[
        tuple[SimpleGridDefinition, tuple[float, ...], tuple[float, ...]]
    ] = []
    point_count = 0
    for grid in grids:
        horizontal_values = axis_values(grid.horizontal, label=horizontal_label)
        vertical_values = axis_values(grid.vertical, label=vertical_label)
        point_count += len(horizontal_values) * len(vertical_values)
        if point_count > MAX_GRID_POINTS:
            raise GridValidationError(
                f"These grids contain {point_count:,} points before duplicate removal; "
                f"the designer limit is {MAX_GRID_POINTS:,}."
            )
        vertical_value_set.update(vertical_values)
        expanded_grids.append((grid, horizontal_values, vertical_values))

    candidates: list[_CandidatePoint] = []
    for grid, validated_horizontal_values, vertical_values in expanded_grids:
        singular_pan_directions: set[int] = set()
        pan_sampling_enabled = (
            grid.equal_area_pan_spacing
            or grid.stagger_alternate_tilt_rows
        )
        for row_index, vertical_value in enumerate(reversed(vertical_values)):
            if input_system == "az_el":
                horizontal_values = _azimuth_values_for_elevation(
                    grid,
                    elevation=vertical_value,
                    row_index=row_index,
                    validated_values=validated_horizontal_values,
                )
            else:
                horizontal_values = _pan_values_for_tilt(
                    grid,
                    row_index=row_index,
                    validated_values=validated_horizontal_values,
                )
            horizontal_value_set.update(horizontal_values)
            for horizontal_value in horizontal_values:
                point_vertical_value = vertical_value
                logical_vertical = vertical_value
                if (
                    input_system == "pan_tilt"
                    and pan_sampling_enabled
                    and _is_pan_singularity(horizontal_value)
                ):
                    singular_direction = (
                        1 if math.sin(math.radians(horizontal_value)) > 0 else -1
                    )
                    if singular_direction in singular_pan_directions:
                        continue
                    singular_pan_directions.add(singular_direction)
                    point_vertical_value = (
                        grid.vertical.minimum + grid.vertical.maximum
                    ) / 2.0
                    logical_vertical = point_vertical_value

                if input_system == "az_el":
                    ideal_azimuth = horizontal_value
                    ideal_elevation = point_vertical_value
                    ideal_pan, ideal_tilt = az_el_to_pan_tilt(
                        ideal_azimuth,
                        ideal_elevation,
                    )
                else:
                    ideal_pan = horizontal_value
                    ideal_tilt = point_vertical_value
                    ideal_azimuth, ideal_elevation = pan_tilt_to_az_el(
                        ideal_pan,
                        ideal_tilt,
                    )

                pan = quantize_angle(
                    ideal_pan,
                    pan_quantization,
                    label="Pan",
                )
                tilt = quantize_angle(
                    ideal_tilt,
                    tilt_quantization,
                    label="Tilt",
                )
                if pan == ideal_pan and tilt == ideal_tilt:
                    azimuth = ideal_azimuth
                    elevation = ideal_elevation
                else:
                    azimuth, elevation = pan_tilt_to_az_el(pan, tilt)

                if (
                    reject_inaccessible
                    and tilt > MAX_TURNTABLE_TILT + _ZERO_TOLERANCE
                ):
                    continue

                candidates.append(
                    _CandidatePoint(
                        point=GridPoint(
                            traversal_index=0,
                            row=0,
                            column=0,
                            ideal_azimuth=ideal_azimuth,
                            ideal_elevation=ideal_elevation,
                            ideal_pan=ideal_pan,
                            ideal_tilt=ideal_tilt,
                            azimuth=azimuth,
                            elevation=elevation,
                            pan=pan,
                            tilt=tilt,
                        ),
                        logical_vertical=logical_vertical,
                    )
                )

    candidates = _remove_duplicate_candidates(candidates, input_system)
    if not candidates:
        if reject_inaccessible:
            raise GridValidationError(
                "No accessible points remain after applying the +45° turntable tilt limit."
            )
        raise GridValidationError("No points remain after duplicate removal.")

    points = _route_candidates(candidates, input_system)
    return DesignedGrid(
        input_system=input_system,
        horizontal_values=tuple(sorted(horizontal_value_set)),
        vertical_values=tuple(sorted(vertical_value_set)),
        points=points,
    )


def design_grid(
    *,
    input_system: CoordinateSystem,
    horizontal: AxisDefinition,
    vertical: AxisDefinition,
    cosine_correct_azimuth_spacing: bool = False,
    stagger_alternate_elevation_rows: bool = False,
    equal_area_pan_spacing: bool = False,
    stagger_alternate_tilt_rows: bool = False,
    reject_inaccessible: bool = False,
    pan_quantization: QuantizationDefinition = QuantizationDefinition(),
    tilt_quantization: QuantizationDefinition = QuantizationDefinition(),
) -> DesignedGrid:
    """Create a combined grid containing one simple rectangular grid."""
    return design_combined_grid(
        input_system=input_system,
        grids=(
            SimpleGridDefinition(
                horizontal=horizontal,
                vertical=vertical,
                cosine_correct_azimuth_spacing=cosine_correct_azimuth_spacing,
                stagger_alternate_elevation_rows=stagger_alternate_elevation_rows,
                equal_area_pan_spacing=equal_area_pan_spacing,
                stagger_alternate_tilt_rows=stagger_alternate_tilt_rows,
            ),
        ),
        reject_inaccessible=reject_inaccessible,
        pan_quantization=pan_quantization,
        tilt_quantization=tilt_quantization,
    )

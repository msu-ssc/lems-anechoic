import importlib
import math
import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from msu_anechoic import experiment
from msu_anechoic.web.app import INACCESSIBLE_AZ_EL_REGIONS
from msu_anechoic.web.app import _az_el_unit_vector
from msu_anechoic.web.app import _estimate_grid_cost
from msu_anechoic.web.app import _estimate_grid_travel_time
from msu_anechoic.web.app import _estimate_move_cost
from msu_anechoic.web.app import _estimate_move_travel_time
from msu_anechoic.web.app import _experiment_cuts_from_grid
from msu_anechoic.web.app import _figure
from msu_anechoic.web.app import _flat_topped_lower_hemisphere_mesh
from msu_anechoic.web.app import _format_duration
from msu_anechoic.web.app import _grid_with_order
from msu_anechoic.web.app import _interpolated_route_coordinates
from msu_anechoic.web.app import _optimize_grid_route
from msu_anechoic.web.app import _pan_tilt_candidate_neighbors
from msu_anechoic.web.app import _quantization_error_figure
from msu_anechoic.web.app import _spherical_patch_mesh
from msu_anechoic.web.app import _three_dimensional_figure
from msu_anechoic.web.app import app
from msu_anechoic.web.app import experiment_designer
from msu_anechoic.web.app import save_experiment_design
from msu_anechoic.web.grid import DUPLICATE_TOLERANCE
from msu_anechoic.web.grid import MAX_TURNTABLE_TILT
from msu_anechoic.web.grid import AxisDefinition
from msu_anechoic.web.grid import GridValidationError
from msu_anechoic.web.grid import QuantizationDefinition
from msu_anechoic.web.grid import SimpleGridDefinition
from msu_anechoic.web.grid import _equal_area_pan_coordinate
from msu_anechoic.web.grid import _pan_from_equal_area_coordinate
from msu_anechoic.web.grid import axis_values
from msu_anechoic.web.grid import az_el_to_pan_tilt
from msu_anechoic.web.grid import design_combined_grid
from msu_anechoic.web.grid import design_grid
from msu_anechoic.web.grid import pan_tilt_to_az_el
from msu_anechoic.web.grid import quantize_angle


def test_axis_values_are_inclusive_and_decimal_safe():
    values = axis_values(AxisDefinition(-0.3, 0.3, 0.1), label="Azimuth")
    assert values == pytest.approx((-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3))


def test_axis_uses_a_shorter_final_interval_to_include_maximum():
    values = axis_values(AxisDefinition(0, 10, 3), label="Tilt")
    assert values == (0, 3, 6, 9, 10)


def test_cosine_corrected_azimuth_spacing_scales_each_elevation_row():
    grid = design_grid(
        input_system="az_el",
        horizontal=AxisDefinition(0, 40, 10),
        vertical=AxisDefinition(0, 60, 60),
        cosine_correct_azimuth_spacing=True,
    )
    azimuths_by_elevation = {
        elevation: [point.azimuth for point in grid.points if point.elevation == elevation] for elevation in (0, 60)
    }

    assert sorted(azimuths_by_elevation[0]) == pytest.approx([0, 10, 20, 30, 40])
    assert sorted(azimuths_by_elevation[60]) == pytest.approx([0, 20, 40])


def test_corrected_azimuth_rows_do_not_append_a_short_final_interval():
    grid = design_grid(
        input_system="az_el",
        horizontal=AxisDefinition(0, 10, 3),
        vertical=AxisDefinition(0, 0, 1),
        cosine_correct_azimuth_spacing=True,
    )

    assert sorted(point.azimuth for point in grid.points) == [0, 3, 6, 9]


def test_staggering_offsets_every_other_elevation_row_by_half_a_step():
    grid = design_grid(
        input_system="az_el",
        horizontal=AxisDefinition(0, 40, 10),
        vertical=AxisDefinition(0, 20, 10),
        stagger_alternate_elevation_rows=True,
    )
    azimuths_by_elevation = {
        elevation: sorted(point.azimuth for point in grid.points if point.elevation == elevation)
        for elevation in (0, 10, 20)
    }

    assert azimuths_by_elevation[20] == [0, 10, 20, 30, 40]
    assert azimuths_by_elevation[10] == [5, 15, 25, 35]
    assert azimuths_by_elevation[0] == [0, 10, 20, 30, 40]


def test_corrected_pole_rows_contain_one_centered_azimuth():
    grid = design_grid(
        input_system="az_el",
        horizontal=AxisDefinition(-180, 180, 10),
        vertical=AxisDefinition(-90, 90, 180),
        cosine_correct_azimuth_spacing=True,
        stagger_alternate_elevation_rows=True,
    )

    assert len(grid.points) == 2
    assert {point.elevation for point in grid.points} == {-90, 90}
    assert all(point.azimuth == 0 for point in grid.points)


@pytest.mark.parametrize("pan", [-270, -180, -90, -30, 0, 30, 90, 180, 270])
def test_equal_area_pan_coordinate_round_trips_across_singularities(pan):
    coordinate = _equal_area_pan_coordinate(pan)

    assert _pan_from_equal_area_coordinate(coordinate) == pytest.approx(pan)


def test_equal_area_pan_spacing_has_constant_spherical_strip_area():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(0, 60, 10),
        vertical=AxisDefinition(0, 0, 1),
        equal_area_pan_spacing=True,
    )
    pans = sorted(point.pan for point in grid.points)
    equal_area_coordinates = [_equal_area_pan_coordinate(pan) for pan in pans]
    intervals = [
        right - left
        for left, right in zip(
            equal_area_coordinates,
            equal_area_coordinates[1:],
        )
    ]

    assert pans[0] == 0
    assert pans[1] == pytest.approx(10)
    assert all(interval == pytest.approx(intervals[0]) for interval in intervals)
    assert all(right - left < next_right - right for left, right, next_right in zip(pans, pans[1:], pans[2:]))


def test_equal_area_pan_rows_do_not_append_a_short_final_interval():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(0, 25, 10),
        vertical=AxisDefinition(0, 0, 1),
        equal_area_pan_spacing=True,
    )

    assert [point.pan for point in grid.points] == pytest.approx(
        [0, 10, math.degrees(math.asin(2 * math.sin(math.radians(10))))]
    )


def test_equal_area_staggering_offsets_alternate_tilt_rows_by_half_an_area_step():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(0, 40, 10),
        vertical=AxisDefinition(0, 20, 10),
        equal_area_pan_spacing=True,
        stagger_alternate_tilt_rows=True,
    )
    pans_by_tilt = {tilt: sorted(point.pan for point in grid.points if point.tilt == tilt) for tilt in (0, 10, 20)}
    half_step_pan = math.degrees(math.asin(math.sin(math.radians(10)) / 2))

    assert pans_by_tilt[20][0] == 0
    assert pans_by_tilt[10][0] == pytest.approx(half_step_pan)
    assert pans_by_tilt[0][0] == 0


def test_equal_area_pan_singularities_collapse_to_one_centered_tilt_point():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(-90, 90, 90),
        vertical=AxisDefinition(-10, 10, 10),
        equal_area_pan_spacing=True,
    )
    points_by_pan = {pan: [point for point in grid.points if point.pan == pan] for pan in (-90, 0, 90)}

    assert len(grid.points) == 5
    assert len(points_by_pan[-90]) == 1
    assert len(points_by_pan[90]) == 1
    assert points_by_pan[-90][0].tilt == 0
    assert points_by_pan[90][0].tilt == 0
    assert sorted(point.tilt for point in points_by_pan[0]) == [-10, 0, 10]


def test_quantization_rounds_to_nearest_origin_plus_integer_step():
    definition = QuantizationDefinition(enabled=True, origin=0.1, step=0.5)

    assert quantize_angle(20.123, definition, label="Pan") == pytest.approx(20.1)
    assert quantize_angle(20.298, definition, label="Pan") == pytest.approx(20.1)
    assert quantize_angle(20.35, definition, label="Pan") == pytest.approx(20.6)
    assert quantize_angle(-0.15, definition, label="Pan") == pytest.approx(-0.4)
    assert (
        quantize_angle(
            20.298,
            QuantizationDefinition(enabled=False, origin=0.1, step=0.5),
            label="Pan",
        )
        == 20.298
    )


def test_grid_retains_ideal_and_quantized_coordinates():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(20.123, 20.298, 0.175),
        vertical=AxisDefinition(10.123, 10.123, 1),
        pan_quantization=QuantizationDefinition(enabled=True, step=0.5),
        tilt_quantization=QuantizationDefinition(enabled=True, step=0.5),
    )

    assert [point.ideal_pan for point in grid.points] == [20.123, 20.298]
    assert [point.pan for point in grid.points] == [20.0, 20.5]
    assert all(point.ideal_tilt == 10.123 for point in grid.points)
    assert all(point.tilt == 10.0 for point in grid.points)


def test_quantization_happens_before_inaccessible_point_rejection():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(0, 0, 1),
        vertical=AxisDefinition(45.24, 45.26, 0.02),
        reject_inaccessible=True,
        tilt_quantization=QuantizationDefinition(enabled=True, step=0.5),
    )

    assert len(grid.points) == 1
    assert grid.points[0].ideal_tilt == pytest.approx(45.24)
    assert grid.points[0].tilt == pytest.approx(45.0)


def test_combined_grid_removes_overlapping_points():
    grid = design_combined_grid(
        input_system="pan_tilt",
        grids=(
            SimpleGridDefinition(
                horizontal=AxisDefinition(-2, 2, 2),
                vertical=AxisDefinition(-2, 2, 2),
            ),
            SimpleGridDefinition(
                horizontal=AxisDefinition(-1, 1, 1),
                vertical=AxisDefinition(-1, 1, 1),
            ),
        ),
    )

    assert len(grid.points) == 17
    assert grid.row_count == 5
    assert grid.column_count == 5


def test_combined_grid_checks_duplicates_after_quantization():
    grid = design_combined_grid(
        input_system="pan_tilt",
        grids=(
            SimpleGridDefinition(
                horizontal=AxisDefinition(20.12, 20.12, 1),
                vertical=AxisDefinition(10, 10, 1),
            ),
            SimpleGridDefinition(
                horizontal=AxisDefinition(20.24, 20.24, 1),
                vertical=AxisDefinition(10, 10, 1),
            ),
        ),
        pan_quantization=QuantizationDefinition(enabled=True, step=0.5),
    )

    assert len(grid.points) == 1
    assert grid.points[0].pan == 20.0


def test_duplicate_tolerance_applies_to_both_specified_axes():
    grid = design_combined_grid(
        input_system="pan_tilt",
        grids=(
            SimpleGridDefinition(
                horizontal=AxisDefinition(0, 0, 1),
                vertical=AxisDefinition(0, 0, 1),
            ),
            SimpleGridDefinition(
                horizontal=AxisDefinition(
                    DUPLICATE_TOLERANCE,
                    DUPLICATE_TOLERANCE,
                    1,
                ),
                vertical=AxisDefinition(
                    DUPLICATE_TOLERANCE,
                    DUPLICATE_TOLERANCE,
                    1,
                ),
            ),
            SimpleGridDefinition(
                horizontal=AxisDefinition(
                    DUPLICATE_TOLERANCE + 0.001,
                    DUPLICATE_TOLERANCE + 0.001,
                    1,
                ),
                vertical=AxisDefinition(0, 0, 1),
            ),
        ),
    )

    assert len(grid.points) == 2


def test_combined_path_chooses_closest_endpoint_of_each_next_row():
    grid = design_combined_grid(
        input_system="pan_tilt",
        grids=(
            SimpleGridDefinition(
                horizontal=AxisDefinition(0, 10, 10),
                vertical=AxisDefinition(10, 10, 1),
            ),
            SimpleGridDefinition(
                horizontal=AxisDefinition(1, 9, 8),
                vertical=AxisDefinition(0, 0, 1),
            ),
            SimpleGridDefinition(
                horizontal=AxisDefinition(0, 100, 100),
                vertical=AxisDefinition(-10, -10, 1),
            ),
        ),
    )

    assert [(point.pan, point.tilt) for point in grid.points] == [
        (0, 10),
        (10, 10),
        (9, 0),
        (1, 0),
        (0, -10),
        (100, -10),
    ]


def test_grid_starts_top_left_and_traverses_horizontal_serpentine():
    grid = design_grid(
        input_system="az_el",
        horizontal=AxisDefinition(-10, 10, 10),
        vertical=AxisDefinition(-10, 10, 10),
    )

    coordinates = [(point.azimuth, point.elevation) for point in grid.points]
    assert coordinates == [
        (-10, 10),
        (0, 10),
        (10, 10),
        (10, 0),
        (0, 0),
        (-10, 0),
        (-10, -10),
        (0, -10),
        (10, -10),
    ]
    assert [point.traversal_index for point in grid.points] == list(range(1, 10))


def test_grid_can_reject_points_above_turntable_tilt_limit():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(-10, 10, 10),
        vertical=AxisDefinition(40, 50, 5),
        reject_inaccessible=True,
    )

    assert len(grid.points) == 6
    assert all(point.tilt <= MAX_TURNTABLE_TILT for point in grid.points)
    assert {point.tilt for point in grid.points} == {40, 45}
    assert [point.traversal_index for point in grid.points] == list(range(1, 7))


def test_grid_applies_tilt_limit_after_converting_azimuth_elevation():
    grid = design_grid(
        input_system="az_el",
        horizontal=AxisDefinition(0, 0, 1),
        vertical=AxisDefinition(45, 46, 1),
        reject_inaccessible=True,
    )

    assert len(grid.points) == 1
    assert grid.points[0].elevation == 45
    assert grid.points[0].tilt == pytest.approx(MAX_TURNTABLE_TILT)


def test_grid_reports_when_rejection_removes_every_point():
    with pytest.raises(GridValidationError, match="No accessible points remain"):
        design_grid(
            input_system="pan_tilt",
            horizontal=AxisDefinition(0, 10, 10),
            vertical=AxisDefinition(46, 50, 4),
            reject_inaccessible=True,
        )


@pytest.mark.parametrize(
    ("azimuth", "elevation", "expected"),
    [
        (0, 0, (1, 0, 0)),
        (90, 0, (0, -1, 0)),
        (-90, 0, (0, 1, 0)),
        (0, 90, (0, 0, 1)),
        (0, -90, (0, 0, -1)),
    ],
)
def test_az_el_unit_vector_uses_positive_x_boresight_reflected_across_xz_plane(
    azimuth,
    elevation,
    expected,
):
    assert _az_el_unit_vector(azimuth, elevation) == pytest.approx(expected, abs=1e-12)


def test_turntable_mesh_is_a_flat_topped_lower_hemisphere():
    x, y, z, i, j, k = _flat_topped_lower_hemisphere_mesh(radius=0.5)

    assert min(z) == pytest.approx(-0.5)
    assert max(z) == pytest.approx(0.0, abs=1e-12)
    assert all(value <= 1e-12 for value in z)
    assert max(
        math.sqrt(x_value**2 + y_value**2 + z_value**2) for x_value, y_value, z_value in zip(x, y, z)
    ) == pytest.approx(0.5)
    assert len(i) == len(j) == len(k)
    assert len(i) > 0


def test_spherical_screen_pads_angular_extents_just_inside_unit_sphere():
    radius = 0.985
    x, y, z, i, j, k = _spherical_patch_mesh(
        azimuth_min=-30,
        azimuth_max=30,
        elevation_min=-20,
        elevation_max=20,
        radius=radius,
    )
    vertices = list(zip(x, y, z))
    expected_azimuth_min = -33.0
    expected_azimuth_max = 33.0
    expected_elevation_min = -22.0
    expected_elevation_max = 22.0

    assert vertices[0] == pytest.approx(
        tuple(
            radius * component
            for component in _az_el_unit_vector(
                expected_azimuth_min,
                expected_elevation_min,
            )
        )
    )
    assert vertices[-1] == pytest.approx(
        tuple(
            radius * component
            for component in _az_el_unit_vector(
                expected_azimuth_max,
                expected_elevation_max,
            )
        )
    )
    assert all(
        math.sqrt(x_value**2 + y_value**2 + z_value**2) == pytest.approx(radius)
        for x_value, y_value, z_value in vertices
    )
    assert len(i) == len(j) == len(k) == 32 * 20 * 2


def test_spherical_screen_caps_azimuth_at_one_revolution():
    radius = 0.985
    azimuth_segments = 32
    elevation_segments = 20
    x, y, z, i, j, k = _spherical_patch_mesh(
        azimuth_min=-179,
        azimuth_max=179,
        elevation_min=-20,
        elevation_max=20,
        radius=radius,
        azimuth_segments=azimuth_segments,
        elevation_segments=elevation_segments,
    )
    row_width = azimuth_segments + 1

    for elevation_index in range(elevation_segments + 1):
        row_start = elevation_index * row_width
        row_end = row_start + azimuth_segments
        assert (x[row_start], y[row_start], z[row_start]) == pytest.approx(
            (x[row_end], y[row_end], z[row_end]),
            abs=1e-12,
        )

    assert len(i) == len(j) == len(k) == azimuth_segments * elevation_segments * 2


def test_az_el_grid_routes_are_interpolated_in_azimuth_and_elevation():
    grid = design_combined_grid(
        input_system="az_el",
        grids=(
            SimpleGridDefinition(
                horizontal=AxisDefinition(0, 0, 1),
                vertical=AxisDefinition(0, 0, 1),
            ),
            SimpleGridDefinition(
                horizontal=AxisDefinition(80, 80, 1),
                vertical=AxisDefinition(60, 60, 1),
            ),
        ),
    )

    route = _interpolated_route_coordinates(grid)

    assert len(route) == 101
    assert route[50] == pytest.approx(_az_el_unit_vector(40, 30))
    assert all(math.dist(point, (0.0, 0.0, 0.0)) == pytest.approx(1.0) for point in route)


def test_long_pan_tilt_routes_are_interpolated_in_pan_and_tilt():
    grid = design_combined_grid(
        input_system="pan_tilt",
        grids=(
            SimpleGridDefinition(
                horizontal=AxisDefinition(0, 0, 1),
                vertical=AxisDefinition(0, 0, 1),
            ),
            SimpleGridDefinition(
                horizontal=AxisDefinition(80, 80, 1),
                vertical=AxisDefinition(60, 60, 1),
            ),
        ),
    )

    route = _interpolated_route_coordinates(grid)
    midpoint_azimuth, midpoint_elevation = pan_tilt_to_az_el(40, 30)

    assert len(route) == 101
    assert route[50] == pytest.approx(_az_el_unit_vector(midpoint_azimuth, midpoint_elevation))
    assert all(math.dist(point, (0.0, 0.0, 0.0)) == pytest.approx(1.0) for point in route)


def test_sub_degree_routes_remain_straight_cartesian_segments():
    grid = design_combined_grid(
        input_system="pan_tilt",
        grids=(
            SimpleGridDefinition(
                horizontal=AxisDefinition(0, 0, 1),
                vertical=AxisDefinition(0, 0, 1),
            ),
            SimpleGridDefinition(
                horizontal=AxisDefinition(0.5, 0.5, 1),
                vertical=AxisDefinition(0.5, 0.5, 1),
            ),
        ),
    )

    route = _interpolated_route_coordinates(grid)

    assert len(route) == 2


def test_pan_route_uses_long_bounded_move_between_positive_and_negative_limits():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(-160, 160, 320),
        vertical=AxisDefinition(0, 0, 1),
    )

    route = _interpolated_route_coordinates(grid)

    assert len(route) == 321
    assert route[160] == pytest.approx(_az_el_unit_vector(0, 0))


def test_azimuth_route_lerps_directly_between_positive_and_negative_limits():
    grid = design_grid(
        input_system="az_el",
        horizontal=AxisDefinition(-160, 160, 320),
        vertical=AxisDefinition(0, 0, 1),
    )

    route = _interpolated_route_coordinates(grid)

    assert len(route) == 321
    assert route[160] == pytest.approx(_az_el_unit_vector(0, 0))


def test_move_time_does_not_wrap_across_pan_limits(monkeypatch):
    calls = []

    def fake_estimate_time(angle, *, kind, trace):
        calls.append((angle, kind, trace))
        return angle

    monkeypatch.setattr(experiment, "_estimate_time", fake_estimate_time)

    assert _estimate_move_travel_time((160, 0), (-160, 0)) == 320
    assert calls == [(320, "horizontal", False)]


def test_grid_travel_time_sums_simultaneous_axis_move_estimates(monkeypatch):
    calls = []

    def fake_estimate_time(angle, *, kind, trace):
        calls.append((angle, kind, trace))
        return angle * (2 if kind == "horizontal" else 3)

    monkeypatch.setattr(experiment, "_estimate_time", fake_estimate_time)
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(0, 10, 10),
        vertical=AxisDefinition(0, 10, 10),
    )

    assert _estimate_grid_travel_time(grid) == pytest.approx(100)
    assert calls == [
        (10, "vertical", False),
        (10, "horizontal", False),
        (10, "vertical", False),
        (10, "horizontal", False),
    ]


def test_grid_travel_time_includes_both_origin_legs(monkeypatch):
    calls = []

    def fake_estimate_time(angle, *, kind, trace):
        calls.append((angle, kind, trace))
        return angle * (2 if kind == "horizontal" else 3)

    monkeypatch.setattr(experiment, "_estimate_time", fake_estimate_time)
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(10, 10, 1),
        vertical=AxisDefinition(20, 20, 1),
    )

    assert _estimate_grid_travel_time(grid) == pytest.approx(120)
    assert calls == [
        (10, "horizontal", False),
        (20, "vertical", False),
        (10, "horizontal", False),
        (20, "vertical", False),
    ]


def test_move_cost_weights_vertical_time_without_changing_real_time(
    monkeypatch,
):
    def fake_estimate_time(angle, *, kind, trace):
        assert trace is False
        return angle * (2 if kind == "horizontal" else 3)

    monkeypatch.setattr(experiment, "_estimate_time", fake_estimate_time)

    assert _estimate_move_travel_time((0, 0), (10, 5)) == pytest.approx(20)
    assert _estimate_move_cost(
        (0, 0),
        (10, 5),
        vertical_movement_multiplier=3.0,
    ) == pytest.approx(65)


def test_two_opt_improves_an_inefficient_pan_tilt_route():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(10, 40, 10),
        vertical=AxisDefinition(0, 0, 1),
    )
    inefficient_grid = _grid_with_order(grid, (0, 2, 1, 3))
    original_cost = _estimate_grid_cost(
        inefficient_grid,
        vertical_movement_multiplier=3.0,
    )

    optimized_order, optimized_cost = _optimize_grid_route(
        inefficient_grid,
        max_seconds=0.05,
        random_seed=1,
    )

    assert sorted(optimized_order) == [0, 1, 2, 3]
    assert optimized_cost < original_cost


def test_optimizer_removes_large_pole_crossing_moves_from_spherical_grid():
    grid = design_grid(
        input_system="az_el",
        horizontal=AxisDefinition(-180, 180, 10),
        vertical=AxisDefinition(-90, 40, 10),
    )
    original_cost = _estimate_grid_cost(
        grid,
        vertical_movement_multiplier=3.0,
    )

    optimized_order, optimized_cost = _optimize_grid_route(
        grid,
        max_seconds=0.25,
        random_seed=1,
    )

    route = (
        [(0.0, 0.0)] + [(grid.points[index].pan, grid.points[index].tilt) for index in optimized_order] + [(0.0, 0.0)]
    )
    maximum_axis_move = max(
        max(
            abs(end[0] - start[0]),
            abs(end[1] - start[1]),
        )
        for start, end in zip(route, route[1:])
    )

    assert optimized_cost < original_cost * 0.5
    assert maximum_axis_move < 130.0


def test_optimizer_neighbors_match_tilt_branches_across_pan_pole():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(-91, -89, 2),
        vertical=AxisDefinition(-80, 40, 120),
    )
    neighbors, _ = _pan_tilt_candidate_neighbors(
        grid.points,
        neighbor_count=1,
    )
    point_index = next(index for index, point in enumerate(grid.points) if point.pan == -89 and point.tilt == -80)
    neighbor = grid.points[neighbors[point_index][0]]

    assert neighbor.pan == -91
    assert neighbor.tilt == -80


def test_optimizer_neighbors_do_not_wrap_across_pan_limits():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(-179, 179, 279),
        vertical=AxisDefinition(0, 0, 1),
    )
    neighbors, _ = _pan_tilt_candidate_neighbors(
        grid.points,
        neighbor_count=1,
    )
    point_index = next(index for index, point in enumerate(grid.points) if point.pan == 179)
    neighbor = grid.points[neighbors[point_index][0]]

    assert neighbor.pan == 100


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0 sec"),
        (12.4, "12 sec"),
        (90, "1 min 30 sec"),
        (3600, "1 hr"),
        (3723, "1 hr 2 min 3 sec"),
    ],
)
def test_duration_formatting(seconds, expected):
    assert _format_duration(seconds) == expected


def test_three_dimensional_figure_contains_requested_geometry_and_az_el_grid():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(-10, 10, 10),
        vertical=AxisDefinition(-10, 10, 10),
    )
    figure = _three_dimensional_figure(grid)
    traces_by_role = {trace["meta"]["role"]: trace for trace in figure["data"]}

    assert set(traces_by_role) == {
        "turntable",
        "boresight",
        "origin",
        "source",
        "grid-screen",
        "grid-route",
        "grid-points",
        "grid-start",
        "grid-end",
    }
    assert traces_by_role["turntable"]["type"] == "mesh3d"
    assert traces_by_role["boresight"]["x"] == [0.0, 3.0]
    assert traces_by_role["boresight"]["y"] == [0.0, 0.0]
    assert traces_by_role["boresight"]["z"] == [0.0, 0.0]
    assert traces_by_role["boresight"]["line"]["color"] == "#005eb8"
    assert traces_by_role["grid-screen"]["type"] == "mesh3d"
    assert traces_by_role["grid-screen"]["opacity"] == pytest.approx(0.22)
    assert traces_by_role["grid-screen"]["hoverinfo"] == "skip"
    assert figure["layout"]["scene"]["aspectmode"] == "manual"
    assert figure["layout"]["scene"]["aspectratio"] == {
        "x": pytest.approx(4.45),
        "y": pytest.approx(2.4),
        "z": pytest.approx(2.4),
    }
    assert "title" not in figure["layout"]
    assert figure["layout"]["margin"]["t"] == 20
    for axis_name in ("xaxis", "yaxis", "zaxis"):
        assert figure["layout"]["scene"][axis_name]["showticklabels"] is False
        assert figure["layout"]["scene"][axis_name]["ticks"] == ""

    points = traces_by_role["grid-points"]
    expected = [_az_el_unit_vector(point.azimuth, point.elevation) for point in grid.points]
    assert list(zip(points["x"], points["y"], points["z"])) == pytest.approx(expected)
    assert points["mode"] == "markers"

    route = traces_by_role["grid-route"]
    assert route["mode"] == "lines"
    assert route["hoverinfo"] == "skip"
    assert route["meta"]["line_segments"] == "line-only"
    assert len(route["x"]) >= len(points["x"])


@pytest.mark.parametrize(
    ("azimuth", "elevation"),
    [
        (0, 0),
        (35, 20),
        (-70, 30),
        (120, 25),
        (-145, -40),
    ],
)
def test_coordinate_conversion_round_trips(azimuth, elevation):
    pan, tilt = az_el_to_pan_tilt(azimuth, elevation)
    actual_azimuth, actual_elevation = pan_tilt_to_az_el(pan, tilt)
    assert actual_azimuth == pytest.approx(azimuth, abs=1e-9)
    assert actual_elevation == pytest.approx(elevation, abs=1e-9)
    assert math.isfinite(pan)
    assert math.isfinite(tilt)


@pytest.mark.parametrize(
    ("pan", "tilt"),
    [
        (0, 0),
        (35, 20),
        (-70, 30),
        (120, 25),
        (-145, -40),
    ],
)
def test_pan_tilt_conversion_round_trips(pan, tilt):
    azimuth, elevation = pan_tilt_to_az_el(pan, tilt)
    actual_pan, actual_tilt = az_el_to_pan_tilt(azimuth, elevation)
    assert actual_pan == pytest.approx(pan, abs=1e-9)
    assert actual_tilt == pytest.approx(tilt, abs=1e-9)


def test_grid_designer_page_loads():
    client = TestClient(app)
    response = client.get("/grid-designer")
    assert response.status_code == 200
    assert "Grid Designer" in response.text
    assert 'name="grid_name"' in response.text
    assert 'value="Grid 1"' in response.text
    assert "data-simple-grid-name" in response.text
    assert "MSU Anechoic Chamber" in response.text
    assert "LEMS Anechoic Chamber" not in response.text
    assert 'id="menu-toggle"' in response.text
    assert 'id="application-menu"' in response.text
    assert 'id="theme-select"' not in response.text
    assert "grid-designer-themes" not in response.text
    assert 'id="color-mode-light"' in response.text
    assert 'id="color-mode-dark"' in response.text
    assert "grid-designer-color-mode" in response.text
    assert "Azimuth / elevation" in response.text
    assert "Pan / tilt" in response.text
    assert "Quantize" in response.text
    assert "Simple grids" in response.text
    assert "data-add-simple-grid" in response.text
    assert response.text.count("data-simple-grid>") == 1
    assert "data-remove-simple-grid" in response.text
    assert "Cosine-correct azimuth spacing" in response.text
    assert "Stagger alternate elevation rows" in response.text
    assert 'name="cosine_correct_azimuth_spacing_0"' in response.text
    assert 'name="stagger_alternate_elevation_rows_0"' in response.text
    assert "Equal-area pan spacing" in response.text
    assert "Stagger alternate tilt rows" in response.text
    assert 'name="equal_area_pan_spacing_0"' in response.text
    assert 'name="stagger_alternate_tilt_rows_0"' in response.text
    quantization_markup = response.text.split(
        '<section class="quantization-section"',
        1,
    )[1].split("</section>", 1)[0]
    assert quantization_markup.index('name="quantize_pan"') < quantization_markup.index('name="quantize_tilt"')
    assert "<legend" not in quantization_markup
    tilt_control = response.text.split('name="quantize_tilt"', 1)[1].split(">", 1)[0]
    pan_control = response.text.split('name="quantize_pan"', 1)[1].split(">", 1)[0]
    assert "checked" in tilt_control
    assert "checked" not in pan_control
    assert 'name="tilt_quantization_origin"' in response.text
    assert 'name="tilt_quantization_step"' in response.text
    assert 'name="pan_quantization_origin"' in response.text
    assert 'name="pan_quantization_step"' in response.text
    assert 'name="reject_inaccessible"' in response.text
    assert "Reject inaccessible points" in response.text
    assert "Use this grid in an experiment" in response.text
    assert "data-use-grid-for-experiment" in response.text
    assert client.get("/vendor/plotly.min.js").status_code == 200
    assert client.get("/static/htmx.min.js").status_code == 200


def experiment_design_request(
    params: dict | None = None,
    *,
    method: str = "GET",
) -> Request:
    path = "/experiment/design"
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "headers": [],
            "query_string": urlencode(params or {}).encode(),
            "server": ("testserver", 80),
            "client": ("testclient", 1),
            "scheme": "http",
            "root_path": "",
            "app": app,
            "router": app.router,
        }
    )


def test_experiment_designer_reads_the_grid_designer_grid():
    response = experiment_designer(experiment_design_request())
    body = response.body.decode()
    grid_script = Path(
        "msu_anechoic/web/static/grid-designer.js"
    ).read_text(encoding="utf-8")
    design_script = Path(
        "msu_anechoic/web/static/experiment-design.js"
    ).read_text(encoding="utf-8")

    assert response.status_code == 200
    assert "<h1>Experiment Designer</h1>" in body
    assert 'id="experiment-design-form"' in body
    assert 'name="folder_name"' in body
    assert "Save parameters.json" in body
    assert 'data-save-experiment' in body
    assert "Grid Designer grid" in body
    assert 'data-grid-source-facts' in body
    assert 'id="grid-form"' not in body
    assert 'name="input_system"' not in body
    assert 'name="pan_min"' not in body
    assert 'name="azimuth_min"' not in body
    assert "/static/experiment-design.js" in body
    assert 'sessionStorage.setItem(' in grid_script
    assert '"experiment-designer-grid"' in grid_script
    assert 'window.location.assign("/experiment/design")' in grid_script
    assert "window.sessionStorage.getItem(GRID_STORAGE_KEY)" in design_script
    assert 'new URLSearchParams(gridDefinition)' in design_script


def test_experiment_designer_saves_exact_serpentine_cuts(
    tmp_path: Path,
    monkeypatch,
):
    experiments_root = tmp_path / "experiments"
    monkeypatch.setattr(
        experiment,
        "EXPERIMENTS_FOLDER_PATH",
        experiments_root,
    )
    params = {
        "input_system": "pan_tilt",
        "grid_name": "Measurement grid",
        "pan_min": -10,
        "pan_max": 10,
        "pan_step": 10,
        "tilt_min": -5,
        "tilt_max": 5,
        "tilt_step": 5,
        "folder_name": "designed-test",
        "short_description": "Designed test",
        "long_description": "Created from a pan/tilt grid",
        "center_frequency": 8_457_300_000,
        "signal_power": 10,
        "vernier_power": 0,
        "reference_level": -40,
        "span": 10_000,
        "polarization": "horizontal",
        "log_level": "INFO",
        "collect_center_frequency_data": "true",
        "collect_peak_data": "true",
    }
    payload = save_experiment_design(
        experiment_design_request(params, method="POST")
    )

    assert payload["cut_count"] == 3
    assert payload["point_count"] == 9
    parameters_path = experiments_root / "designed-test" / "parameters.json"
    assert parameters_path.is_file()
    parameters = experiment.ExperimentParameters.model_validate_json(
        parameters_path.read_text(encoding="utf-8")
    )
    assert parameters.short_description == "Designed test"
    assert parameters.long_description == "Created from a pan/tilt grid"
    assert parameters.relative_folder_path == experiments_root / "designed-test"
    assert parameters.grid is None
    assert parameters.cuts is not None
    assert [cut.fixed_angle for cut in parameters.cuts.values()] == [5, 0, -5]
    route = [
        (coordinate.pan, coordinate.tilt)
        for cut in parameters.cuts.values()
        for coordinate in cut.coordinates
    ]
    assert route == [
        (-10, 5),
        (0, 5),
        (10, 5),
        (10, 0),
        (0, 0),
        (-10, 0),
        (-10, -5),
        (0, -5),
        (10, -5),
    ]
    assert "neutral_elevation" not in parameters_path.read_text(encoding="utf-8")

    original = parameters_path.read_text(encoding="utf-8")
    with pytest.raises(HTTPException, match="already exists") as exc_info:
        save_experiment_design(experiment_design_request(params, method="POST"))
    assert exc_info.value.status_code == 400
    assert parameters_path.read_text(encoding="utf-8") == original


def test_experiment_designer_rejects_az_el_without_creating_a_folder(
    tmp_path: Path,
    monkeypatch,
):
    experiments_root = tmp_path / "experiments"
    monkeypatch.setattr(
        experiment,
        "EXPERIMENTS_FOLDER_PATH",
        experiments_root,
    )

    with pytest.raises(HTTPException, match="only pan/tilt") as exc_info:
        save_experiment_design(
            experiment_design_request(
                {
                    "input_system": "az_el",
                    "azimuth_min": -10,
                    "azimuth_max": 10,
                    "azimuth_step": 10,
                    "elevation_min": 0,
                    "elevation_max": 0,
                    "elevation_step": 1,
                    "folder_name": "unsupported-az-el",
                },
                method="POST",
            )
        )

    assert exc_info.value.status_code == 400
    assert not (experiments_root / "unsupported-az-el").exists()


def test_experiment_designer_preserves_nonuniform_pan_spacing():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(0, 40, 10),
        vertical=AxisDefinition(0, 0, 1),
        equal_area_pan_spacing=True,
    )

    cuts = _experiment_cuts_from_grid(grid)

    assert len(cuts) == 1
    cut = next(iter(cuts.values()))
    expected_pans = [point.pan for point in grid.points]
    assert cut.angles == expected_pans
    assert [coordinate.pan for coordinate in cut.coordinates] == expected_pans


def test_grid_designer_uses_msu_palette_for_both_color_modes():
    client = TestClient(app)
    page = client.get("/grid-designer")
    stylesheet = client.get("/static/grid-designer.css")

    assert "#0033a0" in page.text
    assert "#18453b" not in page.text
    assert "--accent: #0033a0" in stylesheet.text
    assert "--brand-yellow: #ffcf00" in stylesheet.text
    assert ':root[data-color-mode="dark"]' in stylesheet.text


def test_grid_designer_uses_large_high_contrast_type_and_yellow_header_details():
    client = TestClient(app)
    stylesheet = client.get("/static/grid-designer.css")

    assert stylesheet.status_code == 200
    assert "--text: #000000" in stylesheet.text
    assert "--text-muted: #000000" in stylesheet.text
    assert "--text: #ffffff" in stylesheet.text
    assert "--text-muted: #ffffff" in stylesheet.text
    assert "font-size: 16px" in stylesheet.text
    assert "font-size: 28px" in stylesheet.text
    assert "background: var(--brand-yellow)" in stylesheet.text
    assert "color: var(--brand-yellow)" in stylesheet.text
    assert "border-left: 1px solid var(--brand-yellow)" in stylesheet.text

    grid = design_grid(
        input_system="az_el",
        horizontal=AxisDefinition(-10, 10, 10),
        vertical=AxisDefinition(-10, 10, 10),
    )
    figure = _figure(grid, coordinate_system="az_el")
    assert figure["layout"]["font"]["color"] == "#000000"
    assert figure["layout"]["font"]["size"] == 14
    assert "title" not in figure["layout"]
    assert ".plot-card-heading h3" in stylesheet.text
    assert figure["layout"]["xaxis"]["title"]["font"]["size"] == 16
    assert figure["layout"]["xaxis"]["tickfont"]["size"] == 14


def test_three_dimensional_view_has_explicit_rotation_controls():
    script = TestClient(app).get("/static/grid-designer.js")

    assert script.status_code == 200
    assert "CAMERA_ROTATION_PERIOD_MS = 60_000" in script.text
    assert "window.Plotly.relayout" in script.text
    assert '"scene.camera.eye"' in script.text
    assert "paused: true" in script.text
    assert "cameraRotationSettings.paused" in script.text
    assert "cameraRotationSettings.speed" in script.text
    assert "[data-rotation-toggle]" in script.text
    assert "[data-rotation-speed]" in script.text
    assert '"pointerenter"' not in script.text
    assert '"pointerleave"' not in script.text
    assert "IntersectionObserver" in script.text
    assert "document.hidden" in script.text


def test_two_dimensional_views_include_non_ranging_inaccessible_masks():
    client = TestClient(app)
    stylesheet = client.get("/static/grid-designer.css")
    script = client.get("/static/grid-designer.js")
    grid = design_grid(
        input_system="az_el",
        horizontal=AxisDefinition(-90, 90, 30),
        vertical=AxisDefinition(-60, 60, 30),
    )
    azimuth_elevation_figure = _figure(grid, coordinate_system="az_el")
    pan_tilt_figure = _figure(grid, coordinate_system="pan_tilt")

    assert "--plot-inaccessible:" in stylesheet.text
    assert "azimuthElevationMaskShapes" in script.text
    assert "panTiltMaskShapes" in script.text
    assert "scheduleInaccessibleMaskUpdate" not in script.text
    assert '"xaxis.range": xRange' in script.text
    assert '"yaxis.range": yRange' in script.text
    assert azimuth_elevation_figure["layout"]["meta"]["coordinate_system"] == "az_el"
    assert azimuth_elevation_figure["layout"]["meta"]["maximum_turntable_tilt"] == MAX_TURNTABLE_TILT
    assert azimuth_elevation_figure["layout"]["meta"]["inaccessible_regions"] is INACCESSIBLE_AZ_EL_REGIONS
    assert pan_tilt_figure["layout"]["meta"] == {
        "coordinate_system": "pan_tilt",
        "maximum_turntable_tilt": MAX_TURNTABLE_TILT,
    }


def test_two_dimensional_figures_contain_ideal_and_quantized_traces():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(20.2, 20.2, 1),
        vertical=AxisDefinition(10.2, 10.2, 1),
        pan_quantization=QuantizationDefinition(enabled=True, step=0.5),
        tilt_quantization=QuantizationDefinition(enabled=True, step=0.5),
    )
    figure = _figure(grid, coordinate_system="pan_tilt")
    traces_by_role = {trace["meta"]["role"]: trace for trace in figure["data"]}

    assert traces_by_role["grid-ideal"]["x"] == [20.2]
    assert traces_by_role["grid-ideal"]["y"] == [10.2]
    assert traces_by_role["grid-ideal"]["meta"]["representation"] == "ideal"
    assert traces_by_role["grid-ideal"]["meta"]["line_segments"] == "with-markers"
    assert traces_by_role["grid-path"]["x"] == [20.0]
    assert traces_by_role["grid-path"]["y"] == [10.0]
    assert traces_by_role["grid-path"]["meta"]["representation"] == "quantized"
    assert traces_by_role["grid-path"]["meta"]["line_segments"] == "with-markers"


def test_quantization_error_figures_plot_actual_minus_ideal_components():
    grid = design_grid(
        input_system="pan_tilt",
        horizontal=AxisDefinition(20.2, 20.2, 1),
        vertical=AxisDefinition(10.2, 10.2, 1),
        pan_quantization=QuantizationDefinition(enabled=True, step=0.5),
        tilt_quantization=QuantizationDefinition(enabled=True, step=0.5),
    )
    figure = _quantization_error_figure(grid, coordinate_system="pan_tilt")
    trace = figure["data"][0]

    assert trace["x"] == pytest.approx([-0.2])
    assert trace["y"] == pytest.approx([-0.2])
    assert trace["meta"]["role"] == "quantization-error"
    assert figure["layout"]["xaxis"]["title"]["text"] == "Pan error (°)"
    assert figure["layout"]["yaxis"]["title"]["text"] == "Tilt error (°)"


def test_az_el_mask_boundaries_are_precomputed_at_one_degree_intervals():
    assert len(INACCESSIBLE_AZ_EL_REGIONS) == 3
    assert [len(region["azimuths"]) for region in INACCESSIBLE_AZ_EL_REGIONS] == [
        91,
        181,
        91,
    ]
    for region in INACCESSIBLE_AZ_EL_REGIONS:
        assert all(
            right - left == 1
            for left, right in zip(
                region["azimuths"],
                region["azimuths"][1:],
            )
        )

    forward = INACCESSIBLE_AZ_EL_REGIONS[1]
    assert forward["elevations"][0] == pytest.approx(0, abs=1e-12)
    assert forward["elevations"][90] == pytest.approx(45)
    assert forward["elevations"][-1] == pytest.approx(0, abs=1e-12)
    assert INACCESSIBLE_AZ_EL_REGIONS[0]["elevations"][0] == pytest.approx(-45)
    assert INACCESSIBLE_AZ_EL_REGIONS[2]["elevations"][-1] == pytest.approx(-45)


def test_preview_accepts_a_range_that_does_not_align_with_step_size():
    response = TestClient(app).get(
        "/grid-designer/preview",
        params={
            "input_system": "az_el",
            "azimuth_min": 0,
            "azimuth_max": 10,
            "azimuth_step": 3,
        },
    )
    assert response.status_code == 200
    assert "<strong>25</strong> points" in response.text
    assert "Check the grid definition" not in response.text


def test_preview_applies_indexed_az_el_sampling_options():
    response = TestClient(app).get(
        "/grid-designer/preview",
        params={
            "input_system": "az_el",
            "azimuth_min": 0,
            "azimuth_max": 10,
            "azimuth_step": 3,
            "elevation_min": 0,
            "elevation_max": 0,
            "elevation_step": 1,
            "cosine_correct_azimuth_spacing_0": "true",
            "stagger_alternate_elevation_rows_0": "true",
        },
    )

    assert response.status_code == 200
    assert "<strong>4</strong> points" in response.text
    assert "Check the grid definition" not in response.text


def test_preview_applies_indexed_pan_tilt_sampling_options():
    response = TestClient(app).get(
        "/grid-designer/preview",
        params={
            "input_system": "pan_tilt",
            "pan_min": 0,
            "pan_max": 25,
            "pan_step": 10,
            "tilt_min": 0,
            "tilt_max": 0,
            "tilt_step": 1,
            "equal_area_pan_spacing_0": "true",
            "stagger_alternate_tilt_rows_0": "true",
        },
    )

    assert response.status_code == 200
    assert "<strong>3</strong> points" in response.text
    assert "Check the grid definition" not in response.text


def test_preview_reports_an_incomplete_input_without_http_error():
    response = TestClient(app).get(
        "/grid-designer/preview",
        params={
            "input_system": "az_el",
            "azimuth_min": "",
        },
    )
    assert response.status_code == 200
    assert "Enter a number for azimuth minimum" in response.text


def test_pan_tilt_preview_contains_three_plot_payloads():
    response = TestClient(app).get(
        "/grid-designer/preview",
        params={
            "input_system": "pan_tilt",
            "pan_min": -10,
            "pan_max": 10,
            "pan_step": 10,
            "tilt_min": -10,
            "tilt_max": 10,
            "tilt_step": 10,
        },
    )
    assert response.status_code == 200
    assert 'id="az-el-figure"' in response.text
    assert 'id="pan-tilt-figure"' in response.text
    assert 'id="three-dimensional-figure"' in response.text
    assert 'id="az-el-error-figure"' in response.text
    assert 'id="pan-tilt-error-figure"' in response.text
    assert response.text.count("Show ideal") == 2
    assert response.text.count("Show quantized") == 2
    assert response.text.count("Show line segments") == 3
    assert response.text.count('class="plot-card plot-card--primary"') == 2
    assert "<h2" in response.text
    assert "Grid info" in response.text
    assert "Path optimization" in response.text
    assert 'name="optimization_max_time"' in response.text
    assert 'name="vertical_movement_multiplier"' in response.text
    assert 'value="3.0"' in response.text
    assert 'value="1.0"' in response.text
    assert 'hx-get="/grid-designer/optimize"' in response.text
    assert '<th scope="row">Original path</th>' in response.text
    assert 'class="grid-info-card"' in response.text
    assert "Estimated travel time" in response.text
    assert 'class="grid-info-table"' in response.text
    assert ">Grid</th>" in response.text
    assert ">Cost</th>" in response.text
    assert ">Points</th>" in response.text
    assert ">Rows</th>" in response.text
    assert ">Columns</th>" not in response.text
    assert '<th scope="row">Grid 1</th>' in response.text
    assert "seconds" in response.text
    assert 'data-plot-visibility-controls="three-dimensional-figure"' in response.text
    assert "data-rotation-toggle" in response.text
    assert "data-rotation-speed" in response.text
    assert "data-rotation-speed-output" in response.text
    assert "<h3>3D pointing geometry</h3>" in response.text
    assert '<button type="button" data-rotation-toggle>Play</button>' in response.text
    assert 'max="10"' in response.text
    assert "<strong>9</strong> points" in response.text


def test_preview_checkbox_rejects_inaccessible_points():
    response = TestClient(app).get(
        "/grid-designer/preview",
        params={
            "input_system": "pan_tilt",
            "pan_min": -10,
            "pan_max": 10,
            "pan_step": 10,
            "tilt_min": 40,
            "tilt_max": 50,
            "tilt_step": 5,
            "reject_inaccessible": "true",
        },
    )

    assert response.status_code == 200
    assert "<strong>6</strong> points" in response.text


def test_preview_combines_repeated_simple_grid_parameters():
    response = TestClient(app).get(
        "/grid-designer/preview",
        params=[
            ("input_system", "pan_tilt"),
            ("grid_name", "Sparse"),
            ("grid_name", "Dense"),
            ("pan_min", "-2"),
            ("pan_min", "-1"),
            ("pan_max", "2"),
            ("pan_max", "1"),
            ("pan_step", "2"),
            ("pan_step", "1"),
            ("tilt_min", "-2"),
            ("tilt_min", "-1"),
            ("tilt_max", "2"),
            ("tilt_max", "1"),
            ("tilt_step", "2"),
            ("tilt_step", "1"),
        ],
    )

    assert response.status_code == 200
    assert "<strong>17</strong> points" in response.text
    assert "<strong>5</strong> rows" in response.text
    assert "<strong>5</strong> columns" in response.text
    assert '<th scope="row">Combined grid</th>' in response.text
    assert '<th scope="row">Sparse</th>' in response.text
    assert '<th scope="row">Dense</th>' in response.text
    assert response.text.count('class="grid-info-subgrid"') == 2
    assert "Sparse and Dense have 1 coincident point." in response.text


def test_optimization_endpoint_records_and_loads_previous_paths(monkeypatch):
    starting_orders = []

    def fake_optimize(
        grid,
        *,
        starting_order,
        max_seconds,
        vertical_movement_multiplier,
        random_seed,
    ):
        assert max_seconds == 0.01
        assert vertical_movement_multiplier in (3.0, 4.0)
        assert random_seed is not None
        starting_orders.append(starting_order)
        return (
            tuple(reversed(starting_order)),
            _estimate_grid_cost(
                grid,
                vertical_movement_multiplier=(vertical_movement_multiplier),
            )
            - len(starting_orders),
        )

    app_module = importlib.import_module("msu_anechoic.web.app")
    monkeypatch.setattr(app_module, "_optimize_grid_route", fake_optimize)
    params = {
        "input_system": "pan_tilt",
        "pan_min": -10,
        "pan_max": 10,
        "pan_step": 10,
        "tilt_min": 0,
        "tilt_max": 0,
        "tilt_step": 1,
        "optimization_max_time": 0.01,
    }
    client = TestClient(app)

    optimized = client.get("/grid-designer/optimize", params=params)

    assert optimized.status_code == 200
    assert '<th scope="row">Original path</th>' in optimized.text
    assert '<th scope="row">Optimized path #1</th>' in optimized.text
    assert ">Calculation time</th>" in optimized.text
    assert ">Vertical multiplier</th>" in optimized.text
    assert "3.0×" in optimized.text
    assert len(re.findall(r">\s*Load\s*</button>", optimized.text)) == 1
    assert '<th scope="row">Grid 1</th>' not in optimized.text
    session_match = re.search(
        r'name="optimization_session_id"\s+value="([^"]+)"',
        optimized.text,
    )
    assert session_match

    loaded = client.get(
        "/grid-designer/optimization/load",
        params={
            **params,
            "optimization_session_id": session_match.group(1),
            "optimization_path": 0,
        },
    )

    assert loaded.status_code == 200
    assert "Loaded Original path." in loaded.text
    assert '<th scope="row">Original path</th>' in loaded.text
    assert '<th scope="row">Optimized path #1</th>' in loaded.text

    continued = client.get(
        "/grid-designer/optimize",
        params={
            **params,
            "optimization_session_id": session_match.group(1),
        },
    )

    assert continued.status_code == 200
    assert '<th scope="row">Original path</th>' in continued.text
    assert '<th scope="row">Optimized path #1</th>' in continued.text
    assert '<th scope="row">Optimized path #2</th>' in continued.text

    changed_multiplier = client.get(
        "/grid-designer/optimize",
        params={
            **params,
            "vertical_movement_multiplier": 4,
            "optimization_session_id": session_match.group(1),
        },
    )

    assert changed_multiplier.status_code == 200
    assert '<th scope="row">Original path</th>' in changed_multiplier.text
    assert '<th scope="row">Optimized path #1</th>' in changed_multiplier.text
    assert '<th scope="row">Optimized path #2</th>' in changed_multiplier.text
    assert '<th scope="row">Optimized path #3</th>' in changed_multiplier.text
    assert "3.0×" in changed_multiplier.text
    assert "4.0×" in changed_multiplier.text

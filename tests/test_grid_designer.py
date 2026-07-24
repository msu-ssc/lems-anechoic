import math

import pytest
from fastapi.testclient import TestClient

from msu_anechoic.web.app import _az_el_unit_vector
from msu_anechoic.web.app import _figure
from msu_anechoic.web.app import _flat_topped_lower_hemisphere_mesh
from msu_anechoic.web.app import _spherical_patch_mesh
from msu_anechoic.web.app import _three_dimensional_figure
from msu_anechoic.web.app import INACCESSIBLE_AZ_EL_REGIONS
from msu_anechoic.web.app import app
from msu_anechoic.web.grid import AxisDefinition
from msu_anechoic.web.grid import GridValidationError
from msu_anechoic.web.grid import MAX_TURNTABLE_TILT
from msu_anechoic.web.grid import axis_values
from msu_anechoic.web.grid import az_el_to_pan_tilt
from msu_anechoic.web.grid import design_grid
from msu_anechoic.web.grid import pan_tilt_to_az_el


def test_axis_values_are_inclusive_and_decimal_safe():
    values = axis_values(AxisDefinition(-0.3, 0.3, 0.1), label="Azimuth")
    assert values == pytest.approx((-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3))


def test_axis_uses_a_shorter_final_interval_to_include_maximum():
    values = axis_values(AxisDefinition(0, 10, 3), label="Tilt")
    assert values == (0, 3, 6, 9, 10)


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
    assert max(math.sqrt(x_value**2 + y_value**2 + z_value**2) for x_value, y_value, z_value in zip(x, y, z)) == pytest.approx(0.5)
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
        "grid-path",
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

    path = traces_by_role["grid-path"]
    expected = [
        _az_el_unit_vector(point.azimuth, point.elevation)
        for point in grid.points
    ]
    assert list(zip(path["x"], path["y"], path["z"])) == pytest.approx(expected)
    assert path["mode"] == "lines+markers"


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
    assert 'name="reject_inaccessible"' in response.text
    assert "Reject inaccessible points" in response.text
    assert client.get("/vendor/plotly.min.js").status_code == 200
    assert client.get("/static/htmx.min.js").status_code == 200


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
    assert figure["layout"]["title"]["font"]["size"] == 20
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
    assert (
        azimuth_elevation_figure["layout"]["meta"]["maximum_turntable_tilt"]
        == MAX_TURNTABLE_TILT
    )
    assert (
        azimuth_elevation_figure["layout"]["meta"]["inaccessible_regions"]
        is INACCESSIBLE_AZ_EL_REGIONS
    )
    assert pan_tilt_figure["layout"]["meta"] == {
        "coordinate_system": "pan_tilt",
        "maximum_turntable_tilt": MAX_TURNTABLE_TILT,
    }


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

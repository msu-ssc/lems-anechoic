import math

import pytest
from fastapi.testclient import TestClient

from msu_anechoic.web.app import app
from msu_anechoic.web.grid import AxisDefinition
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
    assert "Azimuth / elevation" in response.text
    assert "Pan / tilt" in response.text
    assert client.get("/vendor/plotly.min.js").status_code == 200
    assert client.get("/static/htmx.min.js").status_code == 200


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


def test_pan_tilt_preview_contains_two_plot_payloads():
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
    assert "<strong>9</strong> points" in response.text

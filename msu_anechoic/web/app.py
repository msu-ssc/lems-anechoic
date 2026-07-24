"""FastAPI application for the anechoic chamber web interface."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from plotly.offline import get_plotlyjs

from msu_anechoic.web.grid import AxisDefinition
from msu_anechoic.web.grid import DesignedGrid
from msu_anechoic.web.grid import GridValidationError
from msu_anechoic.web.grid import MAX_TURNTABLE_TILT
from msu_anechoic.web.grid import design_grid

WEB_ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=WEB_ROOT / "templates")

app = FastAPI(title="LEMS Anechoic", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")

DEFAULTS = {
    "input_system": "az_el",
    "azimuth_min": -30.0,
    "azimuth_max": 30.0,
    "azimuth_step": 10.0,
    "elevation_min": -20.0,
    "elevation_max": 20.0,
    "elevation_step": 10.0,
    "pan_min": -30.0,
    "pan_max": 30.0,
    "pan_step": 10.0,
    "tilt_min": -20.0,
    "tilt_max": 20.0,
    "tilt_step": 10.0,
    "reject_inaccessible": False,
}


def _precompute_inaccessible_az_el_regions() -> tuple[dict, ...]:
    """Sample the fixed +45° tilt boundary at one-degree azimuth intervals."""
    tilt_tangent = math.tan(math.radians(MAX_TURNTABLE_TILT))
    regions = []
    for azimuth_start, azimuth_end, mask_edge in (
        (-180, -90, -90.0),
        (-90, 90, 90.0),
        (90, 180, -90.0),
    ):
        azimuths = tuple(range(azimuth_start, azimuth_end + 1))
        elevations = tuple(
            math.degrees(
                math.atan(
                    tilt_tangent * math.cos(math.radians(azimuth))
                )
            )
            for azimuth in azimuths
        )
        regions.append(
            {
                "azimuths": azimuths,
                "elevations": elevations,
                "mask_edge": mask_edge,
            }
        )
    return tuple(regions)


INACCESSIBLE_AZ_EL_REGIONS = _precompute_inaccessible_az_el_regions()


def _az_el_unit_vector(azimuth: float, elevation: float) -> tuple[float, float, float]:
    """Map azimuth/elevation angles in degrees onto the unit sphere."""
    azimuth_radians = math.radians(azimuth)
    elevation_radians = math.radians(elevation)
    horizontal_radius = math.cos(elevation_radians)
    return (
        horizontal_radius * math.cos(azimuth_radians),
        -horizontal_radius * math.sin(azimuth_radians),
        math.sin(elevation_radians),
    )


def _sphere_mesh(
    *,
    center: tuple[float, float, float],
    radius: float,
    latitude_segments: int = 12,
    longitude_segments: int = 24,
) -> tuple[list[float], list[float], list[float], list[int], list[int], list[int]]:
    """Create an indexed UV sphere mesh."""
    vertices = [(center[0], center[1], center[2] - radius)]

    for latitude_index in range(1, latitude_segments):
        latitude = -math.pi / 2 + math.pi * latitude_index / latitude_segments
        ring_radius = radius * math.cos(latitude)
        z = center[2] + radius * math.sin(latitude)
        for longitude_index in range(longitude_segments):
            longitude = math.tau * longitude_index / longitude_segments
            vertices.append(
                (
                    center[0] + ring_radius * math.cos(longitude),
                    center[1] + ring_radius * math.sin(longitude),
                    z,
                )
            )

    north_pole_index = len(vertices)
    vertices.append((center[0], center[1], center[2] + radius))

    faces: list[tuple[int, int, int]] = []
    first_ring_start = 1
    for longitude_index in range(longitude_segments):
        current = first_ring_start + longitude_index
        following = first_ring_start + (longitude_index + 1) % longitude_segments
        faces.append((0, following, current))

    ring_count = latitude_segments - 1
    for ring_index in range(ring_count - 1):
        lower_start = 1 + ring_index * longitude_segments
        upper_start = lower_start + longitude_segments
        for longitude_index in range(longitude_segments):
            following = (longitude_index + 1) % longitude_segments
            lower_current = lower_start + longitude_index
            lower_following = lower_start + following
            upper_current = upper_start + longitude_index
            upper_following = upper_start + following
            faces.append((lower_current, lower_following, upper_current))
            faces.append((lower_following, upper_following, upper_current))

    last_ring_start = 1 + (ring_count - 1) * longitude_segments
    for longitude_index in range(longitude_segments):
        current = last_ring_start + longitude_index
        following = last_ring_start + (longitude_index + 1) % longitude_segments
        faces.append((current, following, north_pole_index))

    return (
        [vertex[0] for vertex in vertices],
        [vertex[1] for vertex in vertices],
        [vertex[2] for vertex in vertices],
        [face[0] for face in faces],
        [face[1] for face in faces],
        [face[2] for face in faces],
    )


def _flat_topped_lower_hemisphere_mesh(
    *,
    radius: float,
    latitude_segments: int = 8,
    longitude_segments: int = 32,
) -> tuple[list[float], list[float], list[float], list[int], list[int], list[int]]:
    """Create the lower half of a sphere, closed by a flat disk at z=0."""
    vertices = [(0.0, 0.0, -radius)]

    for latitude_index in range(1, latitude_segments + 1):
        latitude = -math.pi / 2 + (math.pi / 2) * latitude_index / latitude_segments
        ring_radius = radius * math.cos(latitude)
        z = radius * math.sin(latitude)
        for longitude_index in range(longitude_segments):
            longitude = math.tau * longitude_index / longitude_segments
            vertices.append(
                (
                    ring_radius * math.cos(longitude),
                    ring_radius * math.sin(longitude),
                    z,
                )
            )

    faces: list[tuple[int, int, int]] = []
    first_ring_start = 1
    for longitude_index in range(longitude_segments):
        current = first_ring_start + longitude_index
        following = first_ring_start + (longitude_index + 1) % longitude_segments
        faces.append((0, following, current))

    for ring_index in range(latitude_segments - 1):
        lower_start = 1 + ring_index * longitude_segments
        upper_start = lower_start + longitude_segments
        for longitude_index in range(longitude_segments):
            following = (longitude_index + 1) % longitude_segments
            lower_current = lower_start + longitude_index
            lower_following = lower_start + following
            upper_current = upper_start + longitude_index
            upper_following = upper_start + following
            faces.append((lower_current, lower_following, upper_current))
            faces.append((lower_following, upper_following, upper_current))

    rim_start = 1 + (latitude_segments - 1) * longitude_segments
    cap_center_index = len(vertices)
    vertices.append((0.0, 0.0, 0.0))
    for longitude_index in range(longitude_segments):
        current = rim_start + longitude_index
        following = rim_start + (longitude_index + 1) % longitude_segments
        faces.append((cap_center_index, current, following))

    return (
        [vertex[0] for vertex in vertices],
        [vertex[1] for vertex in vertices],
        [vertex[2] for vertex in vertices],
        [face[0] for face in faces],
        [face[1] for face in faces],
        [face[2] for face in faces],
    )


def _spherical_patch_mesh(
    *,
    azimuth_min: float,
    azimuth_max: float,
    elevation_min: float,
    elevation_max: float,
    radius: float = 0.985,
    azimuth_segments: int = 32,
    elevation_segments: int = 20,
) -> tuple[list[float], list[float], list[float], list[int], list[int], list[int]]:
    """Create a padded rectangular az/el patch just inside the unit sphere."""
    azimuth_center = (azimuth_min + azimuth_max) / 2
    azimuth_width = min((azimuth_max - azimuth_min) * 1.10, 360.0)
    azimuth_min = azimuth_center - azimuth_width / 2
    azimuth_max = azimuth_center + azimuth_width / 2

    elevation_center = (elevation_min + elevation_max) / 2
    elevation_width = (elevation_max - elevation_min) * 1.10
    elevation_min = max(-90.0, elevation_center - elevation_width / 2)
    elevation_max = min(90.0, elevation_center + elevation_width / 2)

    vertices: list[tuple[float, float, float]] = []
    for elevation_index in range(elevation_segments + 1):
        fraction = elevation_index / elevation_segments
        elevation = elevation_min + (elevation_max - elevation_min) * fraction
        for azimuth_index in range(azimuth_segments + 1):
            fraction = azimuth_index / azimuth_segments
            azimuth = azimuth_min + (azimuth_max - azimuth_min) * fraction
            unit_vector = _az_el_unit_vector(azimuth, elevation)
            vertices.append(tuple(radius * component for component in unit_vector))

    faces: list[tuple[int, int, int]] = []
    row_width = azimuth_segments + 1
    for elevation_index in range(elevation_segments):
        lower_start = elevation_index * row_width
        upper_start = lower_start + row_width
        for azimuth_index in range(azimuth_segments):
            lower_left = lower_start + azimuth_index
            lower_right = lower_left + 1
            upper_left = upper_start + azimuth_index
            upper_right = upper_left + 1
            faces.append((lower_left, lower_right, upper_left))
            faces.append((lower_right, upper_right, upper_left))

    return (
        [vertex[0] for vertex in vertices],
        [vertex[1] for vertex in vertices],
        [vertex[2] for vertex in vertices],
        [face[0] for face in faces],
        [face[1] for face in faces],
        [face[2] for face in faces],
    )


def _mesh_trace(
    mesh: tuple[list[float], list[float], list[float], list[int], list[int], list[int]],
    *,
    name: str,
    color: str,
    role: str,
    opacity: float = 1.0,
    hoverinfo: str = "name",
) -> dict:
    x, y, z, i, j, k = mesh
    return {
        "type": "mesh3d",
        "x": x,
        "y": y,
        "z": z,
        "i": i,
        "j": j,
        "k": k,
        "name": name,
        "color": color,
        "opacity": opacity,
        "flatshading": False,
        "hoverinfo": hoverinfo,
        "lighting": {
            "ambient": 0.55,
            "diffuse": 0.75,
            "fresnel": 0.08,
            "roughness": 0.8,
            "specular": 0.15,
        },
        "lightposition": {"x": 3, "y": 4, "z": 5},
        "showlegend": False,
        "meta": {"role": role},
    }


def _figure(
    grid: DesignedGrid,
    *,
    coordinate_system: Literal["az_el", "pan_tilt"],
) -> dict:
    if coordinate_system == "az_el":
        x = [point.azimuth for point in grid.points]
        y = [point.elevation for point in grid.points]
        x_title = "Azimuth (°)"
        y_title = "Elevation (°)"
        title = "Azimuth / elevation"
    else:
        x = [point.pan for point in grid.points]
        y = [point.tilt for point in grid.points]
        x_title = "Pan (°)"
        y_title = "Tilt (°)"
        title = "Pan / tilt"

    point_numbers = [point.traversal_index for point in grid.points]
    hover_text = [
        (
            f"<b>Point {point.traversal_index}</b><br>"
            f"Azimuth: {point.azimuth:.3f}°<br>"
            f"Elevation: {point.elevation:.3f}°<br>"
            f"Pan: {point.pan:.3f}°<br>"
            f"Tilt: {point.tilt:.3f}°"
        )
        for point in grid.points
    ]

    data = [
        {
            "type": "scatter",
            "mode": "lines+markers",
            "x": x,
            "y": y,
            "customdata": point_numbers,
            "text": hover_text,
            "hovertemplate": "%{text}<extra></extra>",
            "line": {"color": "#4368aa", "width": 2},
            "marker": {
                "color": point_numbers,
                "colorscale": [[0, "#0033a0"], [1, "#c49300"]],
                "size": 8,
                "line": {"color": "#ffffff", "width": 1},
            },
            "name": "Traversal",
            "meta": {"role": "grid-path"},
        },
        {
            "type": "scatter",
            "mode": "markers",
            "x": [x[0]],
            "y": [y[0]],
            "hovertemplate": "Start · Point 1<extra></extra>",
            "marker": {
                "color": "#0033a0",
                "size": 15,
                "symbol": "circle",
                "line": {"color": "#ffffff", "width": 3},
            },
            "name": "Start",
            "meta": {"role": "grid-start"},
        },
        {
            "type": "scatter",
            "mode": "markers",
            "x": [x[-1]],
            "y": [y[-1]],
            "hovertemplate": f"End · Point {len(grid.points)}<extra></extra>",
            "marker": {
                "color": "#c49300",
                "size": 15,
                "symbol": "diamond",
                "line": {"color": "#ffffff", "width": 3},
            },
            "name": "End",
            "meta": {"role": "grid-end"},
        },
    ]

    return {
        "data": data,
        "layout": {
            "title": {
                "text": title,
                "x": 0.02,
                "xanchor": "left",
                "font": {"size": 20},
            },
            "paper_bgcolor": "#e6eeff",
            "plot_bgcolor": "#d1e0ff",
            "font": {
                "family": "Aptos, Segoe UI, Arial, sans-serif",
                "color": "#000000",
                "size": 14,
            },
            "margin": {"l": 62, "r": 24, "t": 58, "b": 58},
            "hovermode": "closest",
            "showlegend": False,
            "meta": {
                "coordinate_system": coordinate_system,
                "maximum_turntable_tilt": MAX_TURNTABLE_TILT,
                **(
                    {"inaccessible_regions": INACCESSIBLE_AZ_EL_REGIONS}
                    if coordinate_system == "az_el"
                    else {}
                ),
            },
            "xaxis": {
                "title": {"text": x_title, "font": {"size": 16}},
                "tickfont": {"size": 14},
                "gridcolor": "#8fa6d2",
                "zerolinecolor": "#5f79ad",
                "automargin": True,
            },
            "yaxis": {
                "title": {"text": y_title, "font": {"size": 16}},
                "tickfont": {"size": 14},
                "gridcolor": "#8fa6d2",
                "zerolinecolor": "#5f79ad",
                "automargin": True,
                "scaleanchor": "x",
                "scaleratio": 1,
            },
            "uirevision": f"{coordinate_system}-{grid.input_system}",
        },
        "config": {
            "displaylogo": False,
            "responsive": True,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    }


def _three_dimensional_figure(grid: DesignedGrid) -> dict:
    coordinates = [
        _az_el_unit_vector(point.azimuth, point.elevation)
        for point in grid.points
    ]
    x = [coordinate[0] for coordinate in coordinates]
    y = [coordinate[1] for coordinate in coordinates]
    z = [coordinate[2] for coordinate in coordinates]
    point_numbers = [point.traversal_index for point in grid.points]
    azimuths = [point.azimuth for point in grid.points]
    elevations = [point.elevation for point in grid.points]
    hover_text = [
        (
            f"<b>Point {point.traversal_index}</b><br>"
            f"Azimuth: {point.azimuth:.3f}Â°<br>"
            f"Elevation: {point.elevation:.3f}Â°"
        )
        for point in grid.points
    ]

    data = [
        _mesh_trace(
            _flat_topped_lower_hemisphere_mesh(radius=0.5),
            name="Turntable",
            color="#808080",
            role="turntable",
        ),
        {
            "type": "scatter3d",
            "mode": "lines",
            "x": [0.0, 3.0],
            "y": [0.0, 0.0],
            "z": [0.0, 0.0],
            "line": {"color": "#005eb8", "width": 6},
            "hoverinfo": "skip",
            "name": "Boresight",
            "showlegend": False,
            "meta": {"role": "boresight"},
        },
        _mesh_trace(
            _sphere_mesh(center=(0.0, 0.0, 0.0), radius=0.075),
            name="Origin",
            color="#d62728",
            role="origin",
        ),
        _mesh_trace(
            _sphere_mesh(center=(3.0, 0.0, 0.0), radius=0.09),
            name="Antenna source",
            color="#2ca02c",
            role="source",
        ),
        _mesh_trace(
            _spherical_patch_mesh(
                azimuth_min=min(azimuths),
                azimuth_max=max(azimuths),
                elevation_min=min(elevations),
                elevation_max=max(elevations),
            ),
            name="Grid extent",
            color="#7a7a7a",
            role="grid-screen",
            opacity=0.22,
            hoverinfo="skip",
        ),
        {
            "type": "scatter3d",
            "mode": "lines+markers",
            "x": x,
            "y": y,
            "z": z,
            "customdata": point_numbers,
            "text": hover_text,
            "hovertemplate": "%{text}<extra></extra>",
            "line": {"color": "#4368aa", "width": 4},
            "marker": {
                "color": point_numbers,
                "colorscale": [[0, "#0033a0"], [1, "#c49300"]],
                "size": 4,
                "line": {"color": "#ffffff", "width": 1},
            },
            "name": "Traversal",
            "showlegend": False,
            "meta": {"role": "grid-path"},
        },
        {
            "type": "scatter3d",
            "mode": "markers",
            "x": [x[0]],
            "y": [y[0]],
            "z": [z[0]],
            "hovertemplate": "Start Â· Point 1<extra></extra>",
            "marker": {
                "color": "#0033a0",
                "size": 8,
                "symbol": "circle",
                "line": {"color": "#ffffff", "width": 2},
            },
            "name": "Start",
            "showlegend": False,
            "meta": {"role": "grid-start"},
        },
        {
            "type": "scatter3d",
            "mode": "markers",
            "x": [x[-1]],
            "y": [y[-1]],
            "z": [z[-1]],
            "hovertemplate": f"End Â· Point {len(grid.points)}<extra></extra>",
            "marker": {
                "color": "#c49300",
                "size": 8,
                "symbol": "diamond",
                "line": {"color": "#ffffff", "width": 2},
            },
            "name": "End",
            "showlegend": False,
            "meta": {"role": "grid-end"},
        },
    ]

    return {
        "data": data,
        "layout": {
            "paper_bgcolor": "#e6eeff",
            "font": {
                "family": "Aptos, Segoe UI, Arial, sans-serif",
                "color": "#000000",
                "size": 14,
            },
            "margin": {"l": 20, "r": 20, "t": 20, "b": 20},
            "showlegend": False,
            "scene": {
                "bgcolor": "#d1e0ff",
                "aspectmode": "manual",
                "aspectratio": {"x": 4.45, "y": 2.4, "z": 2.4},
                "camera": {
                    "eye": {"x": -1.35, "y": -1.65, "z": 1.05},
                    "projection": {"type": "orthographic"},
                },
                "xaxis": {
                    "title": {"text": "X", "font": {"size": 16}},
                    "range": [-1.2, 3.25],
                    "showticklabels": False,
                    "ticks": "",
                    "gridcolor": "#8fa6d2",
                    "zerolinecolor": "#5f79ad",
                    "tickfont": {"size": 14},
                },
                "yaxis": {
                    "title": {"text": "Y", "font": {"size": 16}},
                    "range": [-1.2, 1.2],
                    "showticklabels": False,
                    "ticks": "",
                    "gridcolor": "#8fa6d2",
                    "zerolinecolor": "#5f79ad",
                    "tickfont": {"size": 14},
                },
                "zaxis": {
                    "title": {"text": "Z", "font": {"size": 16}},
                    "range": [-1.2, 1.2],
                    "showticklabels": False,
                    "ticks": "",
                    "gridcolor": "#8fa6d2",
                    "zerolinecolor": "#5f79ad",
                    "tickfont": {"size": 14},
                },
            },
            "uirevision": f"three-dimensional-{grid.input_system}",
        },
        "config": {
            "displaylogo": False,
            "responsive": True,
            "scrollZoom": True,
        },
    }


def _preview_context(grid: DesignedGrid) -> dict:
    return {
        "grid": grid,
        "az_el_figure_json": json.dumps(_figure(grid, coordinate_system="az_el"), allow_nan=False),
        "pan_tilt_figure_json": json.dumps(_figure(grid, coordinate_system="pan_tilt"), allow_nan=False),
        "three_dimensional_figure_json": json.dumps(_three_dimensional_figure(grid), allow_nan=False),
        "error": None,
    }


def _build_grid(
    *,
    input_system: Literal["az_el", "pan_tilt"],
    azimuth_min: float,
    azimuth_max: float,
    azimuth_step: float,
    elevation_min: float,
    elevation_max: float,
    elevation_step: float,
    pan_min: float,
    pan_max: float,
    pan_step: float,
    tilt_min: float,
    tilt_max: float,
    tilt_step: float,
    reject_inaccessible: bool,
) -> DesignedGrid:
    if input_system == "az_el":
        horizontal = AxisDefinition(azimuth_min, azimuth_max, azimuth_step)
        vertical = AxisDefinition(elevation_min, elevation_max, elevation_step)
    else:
        horizontal = AxisDefinition(pan_min, pan_max, pan_step)
        vertical = AxisDefinition(tilt_min, tilt_max, tilt_step)
    return design_grid(
        input_system=input_system,
        horizontal=horizontal,
        vertical=vertical,
        reject_inaccessible=reject_inaccessible,
    )


def _parse_number(value: str | float, *, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GridValidationError(f"Enter a number for {label}.") from exc
    if not math.isfinite(number):
        raise GridValidationError(f"Enter a finite number for {label}.")
    return number


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url="/grid-designer", status_code=307)


@app.get("/grid-designer", response_class=HTMLResponse)
def grid_designer(request: Request) -> HTMLResponse:
    grid = _build_grid(**DEFAULTS)
    return templates.TemplateResponse(
        request=request,
        name="grid_designer.html",
        context={
            **DEFAULTS,
            **_preview_context(grid),
        },
    )


@app.get("/grid-designer/preview", response_class=HTMLResponse)
def grid_designer_preview(
    request: Request,
    input_system: Literal["az_el", "pan_tilt"] = "az_el",
    azimuth_min: str = str(DEFAULTS["azimuth_min"]),
    azimuth_max: str = str(DEFAULTS["azimuth_max"]),
    azimuth_step: str = str(DEFAULTS["azimuth_step"]),
    elevation_min: str = str(DEFAULTS["elevation_min"]),
    elevation_max: str = str(DEFAULTS["elevation_max"]),
    elevation_step: str = str(DEFAULTS["elevation_step"]),
    pan_min: str = str(DEFAULTS["pan_min"]),
    pan_max: str = str(DEFAULTS["pan_max"]),
    pan_step: str = str(DEFAULTS["pan_step"]),
    tilt_min: str = str(DEFAULTS["tilt_min"]),
    tilt_max: str = str(DEFAULTS["tilt_max"]),
    tilt_step: str = str(DEFAULTS["tilt_step"]),
    reject_inaccessible: bool = False,
) -> HTMLResponse:
    try:
        values = dict(DEFAULTS)
        values["input_system"] = input_system
        values["reject_inaccessible"] = reject_inaccessible
        if input_system == "az_el":
            values.update(
                azimuth_min=_parse_number(azimuth_min, label="azimuth minimum"),
                azimuth_max=_parse_number(azimuth_max, label="azimuth maximum"),
                azimuth_step=_parse_number(azimuth_step, label="azimuth step size"),
                elevation_min=_parse_number(elevation_min, label="elevation minimum"),
                elevation_max=_parse_number(elevation_max, label="elevation maximum"),
                elevation_step=_parse_number(elevation_step, label="elevation step size"),
            )
        else:
            values.update(
                pan_min=_parse_number(pan_min, label="pan minimum"),
                pan_max=_parse_number(pan_max, label="pan maximum"),
                pan_step=_parse_number(pan_step, label="pan step size"),
                tilt_min=_parse_number(tilt_min, label="tilt minimum"),
                tilt_max=_parse_number(tilt_max, label="tilt maximum"),
                tilt_step=_parse_number(tilt_step, label="tilt step size"),
            )
        grid = _build_grid(**values)
        context = _preview_context(grid)
    except GridValidationError as exc:
        context = {"grid": None, "error": str(exc)}

    return templates.TemplateResponse(
        request=request,
        name="_grid_preview.html",
        context=context,
    )


@lru_cache(maxsize=1)
def _plotly_javascript() -> str:
    return get_plotlyjs()


@app.get("/vendor/plotly.min.js", include_in_schema=False)
def plotly_javascript() -> Response:
    return Response(
        content=_plotly_javascript(),
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )

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


def _preview_context(grid: DesignedGrid) -> dict:
    return {
        "grid": grid,
        "az_el_figure_json": json.dumps(_figure(grid, coordinate_system="az_el"), allow_nan=False),
        "pan_tilt_figure_json": json.dumps(_figure(grid, coordinate_system="pan_tilt"), allow_nan=False),
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
) -> DesignedGrid:
    if input_system == "az_el":
        horizontal = AxisDefinition(azimuth_min, azimuth_max, azimuth_step)
        vertical = AxisDefinition(elevation_min, elevation_max, elevation_step)
    else:
        horizontal = AxisDefinition(pan_min, pan_max, pan_step)
        vertical = AxisDefinition(tilt_min, tilt_max, tilt_step)
    return design_grid(input_system=input_system, horizontal=horizontal, vertical=vertical)


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
) -> HTMLResponse:
    try:
        values = dict(DEFAULTS)
        values["input_system"] = input_system
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

"""FastAPI application for the anechoic chamber web interface."""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import random
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from plotly.offline import get_plotlyjs
from pydantic import BaseModel
from scipy.spatial import cKDTree

from msu_anechoic import experiment
from msu_anechoic.turntable2 import TurntableError
from msu_anechoic.web.experiment import experiment_service
from msu_anechoic.web.grid import MAX_TURNTABLE_TILT
from msu_anechoic.web.grid import AxisDefinition
from msu_anechoic.web.grid import DesignedGrid
from msu_anechoic.web.grid import GridPoint
from msu_anechoic.web.grid import GridValidationError
from msu_anechoic.web.grid import QuantizationDefinition
from msu_anechoic.web.grid import SimpleGridDefinition
from msu_anechoic.web.grid import count_coincident_points
from msu_anechoic.web.grid import design_combined_grid
from msu_anechoic.web.grid import pan_tilt_to_az_el
from msu_anechoic.web.turntable import DEFAULT_HISTORY_MAX_POINTS
from msu_anechoic.web.turntable import DEFAULT_HISTORY_MAX_TIME
from msu_anechoic.web.turntable import DEFAULT_HISTORY_RATE
from msu_anechoic.web.turntable import DEFAULT_RECENT_HISTORY_RATE
from msu_anechoic.web.turntable import DEFAULT_RECENT_HISTORY_TIME
from msu_anechoic.web.turntable import DEFAULT_REFRESH_INTERVAL
from msu_anechoic.web.turntable import MOVE_TIMEOUT_MINIMUM
from msu_anechoic.web.turntable import MOVE_TIMEOUT_SAFETY_FACTOR
from msu_anechoic.web.turntable import turntable_service

WEB_ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=WEB_ROOT / "templates")

app = FastAPI(title="LEMS Anechoic", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")

DEFAULTS = {
    "input_system": "az_el",
    "grid_name": "Grid 1",
    "azimuth_min": -30.0,
    "azimuth_max": 30.0,
    "azimuth_step": 10.0,
    "elevation_min": -20.0,
    "elevation_max": 20.0,
    "elevation_step": 10.0,
    "cosine_correct_azimuth_spacing": False,
    "stagger_alternate_elevation_rows": False,
    "pan_min": -30.0,
    "pan_max": 30.0,
    "pan_step": 10.0,
    "tilt_min": -20.0,
    "tilt_max": 20.0,
    "tilt_step": 10.0,
    "equal_area_pan_spacing": False,
    "stagger_alternate_tilt_rows": False,
    "quantize_tilt": True,
    "tilt_quantization_origin": 0.0,
    "tilt_quantization_step": 0.5,
    "quantize_pan": False,
    "pan_quantization_origin": 0.0,
    "pan_quantization_step": 0.5,
    "reject_inaccessible": False,
    "vertical_movement_multiplier": 3.0,
}

ROUTE_INTERPOLATION_THRESHOLD_DEGREES = 1.0
ROUTE_MAX_STEP_DEGREES = 1.0
DEFAULT_OPTIMIZATION_TIME_SECONDS = 1.0
DEFAULT_VERTICAL_MOVEMENT_MULTIPLIER = 3.0
MAX_OPTIMIZATION_TIME_SECONDS = 60.0
MAX_VERTICAL_MOVEMENT_MULTIPLIER = 100.0
MAX_OPTIMIZATION_SESSIONS = 32
MAX_OPTIMIZATION_HISTORY = 50
OPTIMIZATION_NEIGHBOR_COUNT = 48
PAN_TRAVEL_TIME_SCALE = 0.3940
TILT_TRAVEL_TIME_SCALE = 0.9038


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
            math.degrees(math.atan(tilt_tangent * math.cos(math.radians(azimuth)))) for azimuth in azimuths
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


def _estimate_move_axis_times(
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    """Estimate the horizontal and vertical portions of one move."""
    pan_delta = abs(end[0] - start[0])
    tilt_delta = abs(end[1] - start[1])
    horizontal_seconds = (
        experiment._estimate_time(
            pan_delta,
            kind="horizontal",
            trace=False,
        )
        if pan_delta > 1e-12
        else 0.0
    )
    vertical_seconds = (
        experiment._estimate_time(
            tilt_delta,
            kind="vertical",
            trace=False,
        )
        if tilt_delta > 1e-12
        else 0.0
    )
    return max(0.0, horizontal_seconds), max(0.0, vertical_seconds)


def _estimate_move_travel_time(
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Estimate elapsed time for one simultaneous pan/tilt move."""
    horizontal_seconds, vertical_seconds = _estimate_move_axis_times(
        start,
        end,
    )
    return max(horizontal_seconds, vertical_seconds)


def _estimate_move_cost(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    vertical_movement_multiplier: float,
) -> float:
    """Return horizontal time plus weighted vertical time for one move."""
    horizontal_seconds, vertical_seconds = _estimate_move_axis_times(
        start,
        end,
    )
    return horizontal_seconds + vertical_movement_multiplier * vertical_seconds


def _ordered_grid_travel_time(
    points: tuple[GridPoint, ...],
    order: tuple[int, ...],
) -> float:
    """Estimate origin-to-route-to-origin travel for a point permutation."""
    total_seconds = 0.0
    previous = (0.0, 0.0)
    for point_index in order:
        point = points[point_index]
        current = (point.pan, point.tilt)
        total_seconds += _estimate_move_travel_time(previous, current)
        previous = current
    total_seconds += _estimate_move_travel_time(previous, (0.0, 0.0))
    return total_seconds


def _estimate_grid_travel_time(grid: DesignedGrid) -> float:
    """Estimate a complete origin-to-grid-to-origin excursion."""
    return _ordered_grid_travel_time(
        grid.points,
        tuple(range(len(grid.points))),
    )


def _ordered_grid_cost(
    points: tuple[GridPoint, ...],
    order: tuple[int, ...],
    *,
    vertical_movement_multiplier: float,
) -> float:
    """Calculate weighted origin-to-route-to-origin movement cost."""
    total_cost = 0.0
    previous = (0.0, 0.0)
    for point_index in order:
        point = points[point_index]
        current = (point.pan, point.tilt)
        total_cost += _estimate_move_cost(
            previous,
            current,
            vertical_movement_multiplier=vertical_movement_multiplier,
        )
        previous = current
    total_cost += _estimate_move_cost(
        previous,
        (0.0, 0.0),
        vertical_movement_multiplier=vertical_movement_multiplier,
    )
    return total_cost


def _estimate_grid_cost(
    grid: DesignedGrid,
    *,
    vertical_movement_multiplier: float,
) -> float:
    return _ordered_grid_cost(
        grid.points,
        tuple(range(len(grid.points))),
        vertical_movement_multiplier=vertical_movement_multiplier,
    )


class _RouteCostModel:
    """Cache symmetric move costs while an optimization run is active."""

    def __init__(
        self,
        points: tuple[GridPoint, ...],
        *,
        vertical_movement_multiplier: float,
    ):
        self.points = points
        self.vertical_movement_multiplier = vertical_movement_multiplier
        self._cache: dict[tuple[int, int], float] = {}

    def move_cost(self, left: int, right: int) -> float:
        if left == right:
            return 0.0
        key = (left, right) if left < right else (right, left)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        left_coordinates = (0.0, 0.0) if left == -1 else (self.points[left].pan, self.points[left].tilt)
        right_coordinates = (0.0, 0.0) if right == -1 else (self.points[right].pan, self.points[right].tilt)
        cost = _estimate_move_cost(
            left_coordinates,
            right_coordinates,
            vertical_movement_multiplier=self.vertical_movement_multiplier,
        )
        self._cache[key] = cost
        return cost

    def route_cost(self, order: tuple[int, ...] | list[int]) -> float:
        total_cost = 0.0
        previous = -1
        for point_index in order:
            total_cost += self.move_cost(previous, point_index)
            previous = point_index
        return total_cost + self.move_cost(previous, -1)

    def two_opt_delta(
        self,
        order: list[int],
        start_index: int,
        end_index: int,
    ) -> float:
        before = -1 if start_index == 0 else order[start_index - 1]
        first = order[start_index]
        last = order[end_index]
        after = -1 if end_index == len(order) - 1 else order[end_index + 1]
        return (
            self.move_cost(before, last)
            + self.move_cost(first, after)
            - self.move_cost(before, first)
            - self.move_cost(last, after)
        )


def _pan_tilt_candidate_neighbors(
    points: tuple[GridPoint, ...],
    *,
    neighbor_count: int = OPTIMIZATION_NEIGHBOR_COUNT,
    vertical_movement_multiplier: float = DEFAULT_VERTICAL_MOVEMENT_MULTIPLIER,
) -> tuple[tuple[tuple[int, ...], ...], tuple[int, ...]]:
    """Find local neighbors on the turntable's bounded pan/tilt axes.

    Pan is intentionally not periodic: the mechanism must travel through zero
    to move from a large positive pan to a large negative pan.
    """
    point_count = len(points)
    if point_count == 0:
        return (), ()

    coordinates = np.array(
        [
            (
                point.pan * PAN_TRAVEL_TIME_SCALE,
                point.tilt * TILT_TRAVEL_TIME_SCALE * vertical_movement_multiplier,
            )
            for point in points
        ],
        dtype=float,
    )
    point_indexes = np.arange(point_count)
    tree = cKDTree(coordinates)
    query_count = min(
        point_count,
        neighbor_count + 1,
    )
    _, neighbor_indexes = tree.query(
        coordinates,
        k=query_count,
    )

    candidate_neighbors = []
    for point_index, raw_neighbors in enumerate(np.atleast_2d(neighbor_indexes)):
        seen = {point_index}
        neighbors = []
        for raw_neighbor in np.atleast_1d(raw_neighbors):
            neighbor = int(point_indexes[int(raw_neighbor)])
            if neighbor in seen:
                continue
            seen.add(neighbor)
            neighbors.append(neighbor)
            if len(neighbors) >= neighbor_count:
                break
        candidate_neighbors.append(tuple(neighbors))

    origin_query_count = min(
        point_count,
        neighbor_count,
    )
    _, raw_origin_neighbors = tree.query(
        np.array((0.0, 0.0)),
        k=origin_query_count,
    )
    seen = set()
    origin_neighbors = []
    for raw_neighbor in np.atleast_1d(raw_origin_neighbors):
        neighbor = int(point_indexes[int(raw_neighbor)])
        if neighbor in seen:
            continue
        seen.add(neighbor)
        origin_neighbors.append(neighbor)
        if len(origin_neighbors) >= neighbor_count:
            break

    return tuple(candidate_neighbors), tuple(origin_neighbors)


def _multifragment_route_seed(
    points: tuple[GridPoint, ...],
    *,
    candidate_neighbors: tuple[tuple[int, ...], ...],
    cost_model: _RouteCostModel,
    deadline: float,
) -> tuple[int, ...] | None:
    """Build a locally connected tour with a greedy multi-fragment heuristic."""
    point_count = len(points)
    origin = point_count
    edges = []
    for point_index, neighbors in enumerate(candidate_neighbors):
        for neighbor in neighbors:
            if neighbor <= point_index:
                continue
            edges.append(
                (
                    cost_model.move_cost(point_index, neighbor),
                    point_index,
                    neighbor,
                )
            )
    for point_index in range(point_count):
        edges.append(
            (
                cost_model.move_cost(-1, point_index),
                origin,
                point_index,
            )
        )
    edges.sort()
    if time.perf_counter() >= deadline:
        return None

    node_count = point_count + 1
    parents = list(range(node_count))
    component_sizes = [1] * node_count
    degrees = [0] * node_count
    adjacency: list[list[int]] = [[] for _ in range(node_count)]

    def find(node: int) -> int:
        while parents[node] != node:
            parents[node] = parents[parents[node]]
            node = parents[node]
        return node

    def add_edge(left: int, right: int) -> bool:
        left_root = find(left)
        right_root = find(right)
        if degrees[left] >= 2 or degrees[right] >= 2 or left_root == right_root:
            return False
        adjacency[left].append(right)
        adjacency[right].append(left)
        degrees[left] += 1
        degrees[right] += 1
        if component_sizes[left_root] < component_sizes[right_root]:
            left_root, right_root = right_root, left_root
        parents[right_root] = left_root
        component_sizes[left_root] += component_sizes[right_root]
        return True

    edge_count = 0
    for _, left, right in edges:
        if add_edge(left, right):
            edge_count += 1
            if edge_count == point_count:
                break

    # Degree constraints can leave a few local fragments. Join their open
    # endpoints by exact turntable travel time rather than accepting a large
    # arbitrary pole-crossing edge.
    while edge_count < point_count and time.perf_counter() < deadline:
        endpoints = [node for node, degree in enumerate(degrees) if degree < 2]
        if len(endpoints) > 600:
            return None
        fallback_edges = []
        for endpoint_index, left in enumerate(endpoints[:-1]):
            for right in endpoints[endpoint_index + 1 :]:
                if find(left) == find(right):
                    continue
                fallback_edges.append(
                    (
                        cost_model.move_cost(
                            -1 if left == origin else left,
                            -1 if right == origin else right,
                        ),
                        left,
                        right,
                    )
                )
        fallback_edges.sort()
        added_edge = False
        for _, left, right in fallback_edges:
            if add_edge(left, right):
                edge_count += 1
                added_edge = True
                if edge_count == point_count:
                    break
        if not added_edge:
            return None

    if edge_count != point_count:
        return None

    endpoints = [node for node, degree in enumerate(degrees) if degree == 1]
    if len(endpoints) != 2:
        return None
    adjacency[endpoints[0]].append(endpoints[1])
    adjacency[endpoints[1]].append(endpoints[0])

    route = []
    previous = -1
    current = origin
    while True:
        next_node = next(node for node in adjacency[current] if node != previous)
        if next_node == origin:
            break
        route.append(next_node)
        previous, current = current, next_node
    return tuple(route) if len(route) == point_count else None


def _long_edge_first_two_opt(
    order: list[int],
    *,
    candidate_neighbors: tuple[tuple[int, ...], ...],
    origin_neighbors: tuple[int, ...],
    cost_model: _RouteCostModel,
    deadline: float,
) -> bool:
    """Apply one improving 2-opt move, prioritizing the longest route edges."""
    positions = [0] * len(order)
    for position, point_index in enumerate(order):
        positions[point_index] = position

    anchors = [-1, *order]

    def following_node(point_index: int) -> int:
        if point_index == -1:
            return order[0]
        position = positions[point_index]
        return -1 if position == len(order) - 1 else order[position + 1]

    anchors.sort(
        key=lambda point_index: cost_model.move_cost(
            point_index,
            following_node(point_index),
        ),
        reverse=True,
    )
    for anchor_index, point_a in enumerate(anchors):
        if anchor_index % 64 == 0 and time.perf_counter() >= deadline:
            return False
        position_a = -1 if point_a == -1 else positions[point_a]
        neighbors = origin_neighbors if point_a == -1 else candidate_neighbors[point_a]
        for point_b in neighbors:
            position_b = positions[point_b]
            start_index = min(position_a, position_b) + 1
            end_index = max(position_a, position_b)
            if start_index >= end_index:
                continue
            delta = cost_model.two_opt_delta(
                order,
                start_index,
                end_index,
            )
            if delta < -1e-9:
                order[start_index : end_index + 1] = reversed(order[start_index : end_index + 1])
                return True
    return False


def _long_edge_first_relocate(
    order: list[int],
    *,
    candidate_neighbors: tuple[tuple[int, ...], ...],
    cost_model: _RouteCostModel,
    deadline: float,
) -> bool:
    """Relocate one point, starting with points attached to costly edges."""
    positions = [0] * len(order)
    for position, point_index in enumerate(order):
        positions[point_index] = position

    points_by_edge_cost = list(order)

    def adjacent_edge_cost(point_index: int) -> float:
        position = positions[point_index]
        previous = -1 if position == 0 else order[position - 1]
        following = -1 if position == len(order) - 1 else order[position + 1]
        return max(
            cost_model.move_cost(previous, point_index),
            cost_model.move_cost(point_index, following),
        )

    points_by_edge_cost.sort(
        key=adjacent_edge_cost,
        reverse=True,
    )
    for point_number, point_index in enumerate(points_by_edge_cost):
        if point_number % 64 == 0 and time.perf_counter() >= deadline:
            return False
        position = positions[point_index]
        previous = -1 if position == 0 else order[position - 1]
        following = -1 if position == len(order) - 1 else order[position + 1]
        for anchor in candidate_neighbors[point_index]:
            anchor_position = positions[anchor]
            if anchor_position in (position, position - 1):
                continue
            anchor_following = -1 if anchor_position == len(order) - 1 else order[anchor_position + 1]
            delta = (
                cost_model.move_cost(previous, following)
                + cost_model.move_cost(anchor, point_index)
                + cost_model.move_cost(
                    point_index,
                    anchor_following,
                )
                - cost_model.move_cost(previous, point_index)
                - cost_model.move_cost(point_index, following)
                - cost_model.move_cost(anchor, anchor_following)
            )
            if delta < -1e-9:
                order.pop(position)
                if anchor_position > position:
                    anchor_position -= 1
                order.insert(anchor_position + 1, point_index)
                return True
    return False


def _optimize_grid_route(
    grid: DesignedGrid,
    *,
    starting_order: tuple[int, ...] | None = None,
    max_seconds: float = DEFAULT_OPTIMIZATION_TIME_SECONDS,
    vertical_movement_multiplier: float = DEFAULT_VERTICAL_MOVEMENT_MULTIPLIER,
    random_seed: int | None = None,
) -> tuple[tuple[int, ...], float]:
    """Improve a route with local seeding, 2-opt, and randomized 3-opt kicks."""
    point_count = len(grid.points)
    if starting_order is None:
        starting_order = tuple(range(point_count))
    if tuple(sorted(starting_order)) != tuple(range(point_count)):
        raise ValueError("The starting route must contain every grid point exactly once.")
    if not math.isfinite(max_seconds) or max_seconds <= 0.0:
        raise ValueError("Optimization time must be greater than zero.")
    if not math.isfinite(vertical_movement_multiplier) or vertical_movement_multiplier <= 0.0:
        raise ValueError("Vertical movement multiplier must be greater than zero.")

    started = time.perf_counter()
    deadline = started + max_seconds
    randomizer = random.Random(random_seed)
    cost_model = _RouteCostModel(
        grid.points,
        vertical_movement_multiplier=vertical_movement_multiplier,
    )
    best_order = list(starting_order)
    best_cost = cost_model.route_cost(best_order)
    working_order = list(best_order)
    working_cost = best_cost
    if point_count < 2:
        return tuple(best_order), best_cost

    candidate_neighbors: tuple[tuple[int, ...], ...] = ()
    origin_neighbors: tuple[int, ...] = ()
    if max_seconds >= 0.05 and time.perf_counter() < deadline:
        candidate_neighbors, origin_neighbors = _pan_tilt_candidate_neighbors(
            grid.points,
            vertical_movement_multiplier=vertical_movement_multiplier,
        )
        if starting_order == tuple(range(point_count)):
            seed = _multifragment_route_seed(
                grid.points,
                candidate_neighbors=candidate_neighbors,
                cost_model=cost_model,
                deadline=deadline,
            )
            if seed is not None:
                seed_cost = cost_model.route_cost(seed)
                if seed_cost < best_cost - 1e-9:
                    best_order = list(seed)
                    best_cost = seed_cost
                    working_order = list(seed)
                    working_cost = seed_cost

    exhaustive_search = point_count <= 250
    while time.perf_counter() < deadline:
        if not exhaustive_search and candidate_neighbors:
            if _long_edge_first_two_opt(
                working_order,
                candidate_neighbors=candidate_neighbors,
                origin_neighbors=origin_neighbors,
                cost_model=cost_model,
                deadline=deadline,
            ):
                working_cost = cost_model.route_cost(working_order)
                if working_cost < best_cost - 1e-9:
                    best_order = list(working_order)
                    best_cost = working_cost
                continue
            if _long_edge_first_relocate(
                working_order,
                candidate_neighbors=candidate_neighbors,
                cost_model=cost_model,
                deadline=deadline,
            ):
                working_cost = cost_model.route_cost(working_order)
                if working_cost < best_cost - 1e-9:
                    best_order = list(working_order)
                    best_cost = working_cost
                continue

        best_delta = -1e-9
        best_move: tuple[int, int] | None = None

        if exhaustive_search:
            pairs = (
                (start_index, end_index)
                for start_index in range(point_count - 1)
                for end_index in range(start_index + 1, point_count)
            )
        else:
            pairs = (tuple(sorted(randomizer.sample(range(point_count), 2))) for _ in range(2_000))

        for pair_index, (start_index, end_index) in enumerate(pairs):
            if pair_index % 128 == 0 and time.perf_counter() >= deadline:
                break
            delta = cost_model.two_opt_delta(
                working_order,
                start_index,
                end_index,
            )
            if delta < best_delta:
                best_delta = delta
                best_move = (start_index, end_index)

        if best_move is not None:
            start_index, end_index = best_move
            working_order[start_index : end_index + 1] = reversed(working_order[start_index : end_index + 1])
            working_cost = cost_model.route_cost(working_order)
            if working_cost < best_cost - 1e-9:
                best_order = list(working_order)
                best_cost = working_cost
            continue

        if point_count < 6:
            break

        # Swap two adjacent route segments. This changes three connecting
        # edges and moves the next 2-opt pass into a different local basin.
        first_cut, second_cut, third_cut = sorted(randomizer.sample(range(1, point_count), 3))
        working_order = (
            best_order[:first_cut]
            + best_order[second_cut:third_cut]
            + best_order[first_cut:second_cut]
            + best_order[third_cut:]
        )
        working_cost = cost_model.route_cost(working_order)

    best_result = tuple(best_order)
    return best_result, cost_model.route_cost(best_result)


def _grid_with_order(
    grid: DesignedGrid,
    order: tuple[int, ...],
) -> DesignedGrid:
    """Return a grid whose traversal follows the supplied point permutation."""
    return replace(
        grid,
        points=tuple(
            replace(
                grid.points[point_index],
                traversal_index=traversal_index,
            )
            for traversal_index, point_index in enumerate(order, start=1)
        ),
    )


@dataclass(frozen=True)
class _OptimizationPath:
    name: str
    order: tuple[int, ...]
    estimated_seconds: float
    cost: float
    vertical_movement_multiplier: float
    calculation_seconds: float | None


@dataclass
class _OptimizationSession:
    fingerprint: str
    paths: list[_OptimizationPath]
    active_path_index: int = 0
    next_optimization_number: int = 1


_optimization_sessions: OrderedDict[str, _OptimizationSession] = OrderedDict()
_optimization_sessions_lock = threading.Lock()


def _grid_fingerprint(grid: DesignedGrid) -> str:
    """Identify the generated point set and its original traversal order."""
    digest = hashlib.sha256(grid.input_system.encode("ascii"))
    for point in grid.points:
        digest.update(
            (f"|{point.pan:.15g},{point.tilt:.15g},{point.ideal_pan:.15g},{point.ideal_tilt:.15g}").encode("ascii")
        )
    return digest.hexdigest()


def _new_optimization_session(
    grid: DesignedGrid,
    *,
    vertical_movement_multiplier: float,
) -> tuple[str, _OptimizationSession]:
    session_id = secrets.token_urlsafe(18)
    original_order = tuple(range(len(grid.points)))
    session = _OptimizationSession(
        fingerprint=_grid_fingerprint(grid),
        paths=[
            _OptimizationPath(
                name="Original path",
                order=original_order,
                estimated_seconds=_ordered_grid_travel_time(
                    grid.points,
                    original_order,
                ),
                cost=_ordered_grid_cost(
                    grid.points,
                    original_order,
                    vertical_movement_multiplier=(vertical_movement_multiplier),
                ),
                vertical_movement_multiplier=(vertical_movement_multiplier),
                calculation_seconds=None,
            )
        ],
    )
    with _optimization_sessions_lock:
        _optimization_sessions[session_id] = session
        _optimization_sessions.move_to_end(session_id)
        while len(_optimization_sessions) > MAX_OPTIMIZATION_SESSIONS:
            _optimization_sessions.popitem(last=False)
    return session_id, session


def _get_optimization_session(
    session_id: str,
    grid: DesignedGrid,
) -> _OptimizationSession | None:
    if not session_id:
        return None
    with _optimization_sessions_lock:
        session = _optimization_sessions.get(session_id)
        if session is None or session.fingerprint != _grid_fingerprint(grid):
            return None
        _optimization_sessions.move_to_end(session_id)
        return session


def _optimization_context(
    grid: DesignedGrid,
    *,
    session_id: str = "",
    session: _OptimizationSession | None = None,
    max_time_seconds: float = DEFAULT_OPTIMIZATION_TIME_SECONDS,
    vertical_movement_multiplier: float = DEFAULT_VERTICAL_MOVEMENT_MULTIPLIER,
    status: str | None = None,
) -> dict:
    if session is None:
        paths = [
            _OptimizationPath(
                name="Original path",
                order=tuple(range(len(grid.points))),
                estimated_seconds=_estimate_grid_travel_time(grid),
                cost=_estimate_grid_cost(
                    grid,
                    vertical_movement_multiplier=(vertical_movement_multiplier),
                ),
                vertical_movement_multiplier=(vertical_movement_multiplier),
                calculation_seconds=None,
            )
        ]
        active_path_index = 0
    else:
        paths = session.paths
        active_path_index = session.active_path_index

    return {
        "optimization_session_id": session_id,
        "optimization_max_time_seconds": max_time_seconds,
        "vertical_movement_multiplier": vertical_movement_multiplier,
        "optimization_status": status,
        "optimization_paths": [
            {
                "index": index,
                "name": path.name,
                "estimated_travel_time_seconds": path.estimated_seconds,
                "estimated_travel_time_label": _format_duration(path.estimated_seconds),
                "cost": path.cost,
                "cost_label": _format_duration(path.cost),
                "vertical_movement_multiplier": (path.vertical_movement_multiplier),
                "calculation_seconds": path.calculation_seconds,
                "calculation_time_label": _format_calculation_time(path.calculation_seconds),
                "is_active": index == active_path_index,
            }
            for index, path in enumerate(paths)
        ],
    }


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hr")
    if minutes:
        parts.append(f"{minutes} min")
    if seconds or not parts:
        parts.append(f"{seconds} sec")
    return " ".join(parts)


def _format_calculation_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 0.01:
        return "<0.01 sec"
    if seconds < 10:
        return f"{seconds:.2f} sec"
    return _format_duration(seconds)


def _interpolated_route_coordinates(
    grid: DesignedGrid,
) -> list[tuple[float, float, float]]:
    """Interpolate long route segments in the grid's input coordinates."""
    if not grid.points:
        return []

    if grid.input_system == "az_el":

        def coordinates(point: GridPoint) -> tuple[float, float]:
            return point.azimuth, point.elevation

        def unit_vector(
            azimuth: float,
            elevation: float,
        ) -> tuple[float, float, float]:
            return _az_el_unit_vector(azimuth, elevation)

    else:

        def coordinates(point: GridPoint) -> tuple[float, float]:
            return point.pan, point.tilt

        def unit_vector(
            pan: float,
            tilt: float,
        ) -> tuple[float, float, float]:
            azimuth, elevation = pan_tilt_to_az_el(pan, tilt)
            return _az_el_unit_vector(azimuth, elevation)

    route = [unit_vector(*coordinates(grid.points[0]))]
    for start, end in zip(grid.points, grid.points[1:]):
        start_horizontal, start_vertical = coordinates(start)
        end_horizontal, end_vertical = coordinates(end)
        horizontal_delta = end_horizontal - start_horizontal
        vertical_delta = end_vertical - start_vertical
        coordinate_distance = math.hypot(
            horizontal_delta,
            vertical_delta,
        )
        subdivision_count = (
            math.ceil(coordinate_distance / ROUTE_MAX_STEP_DEGREES)
            if coordinate_distance > ROUTE_INTERPOLATION_THRESHOLD_DEGREES + 1e-9
            else 1
        )
        for step in range(1, subdivision_count + 1):
            fraction = step / subdivision_count
            route.append(
                unit_vector(
                    start_horizontal + horizontal_delta * fraction,
                    start_vertical + vertical_delta * fraction,
                )
            )
    return route


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
        ideal_x = [point.ideal_azimuth for point in grid.points]
        ideal_y = [point.ideal_elevation for point in grid.points]
        x_title = "Azimuth (°)"
        y_title = "Elevation (°)"
    else:
        x = [point.pan for point in grid.points]
        y = [point.tilt for point in grid.points]
        ideal_x = [point.ideal_pan for point in grid.points]
        ideal_y = [point.ideal_tilt for point in grid.points]
        x_title = "Pan (°)"
        y_title = "Tilt (°)"

    point_numbers = [point.traversal_index for point in grid.points]
    quantized_hover_text = [
        (
            f"<b>Point {point.traversal_index}</b><br>"
            f"Azimuth: {point.azimuth:.3f}°<br>"
            f"Elevation: {point.elevation:.3f}°<br>"
            f"Pan: {point.pan:.3f}°<br>"
            f"Tilt: {point.tilt:.3f}°"
        )
        for point in grid.points
    ]
    ideal_hover_text = [
        (
            f"<b>Ideal point {point.traversal_index}</b><br>"
            f"Azimuth: {point.ideal_azimuth:.3f}°<br>"
            f"Elevation: {point.ideal_elevation:.3f}°<br>"
            f"Pan: {point.ideal_pan:.3f}°<br>"
            f"Tilt: {point.ideal_tilt:.3f}°"
        )
        for point in grid.points
    ]

    data = [
        {
            "type": "scatter",
            "mode": "lines+markers",
            "x": ideal_x,
            "y": ideal_y,
            "customdata": point_numbers,
            "text": ideal_hover_text,
            "hovertemplate": "%{text}<extra></extra>",
            "line": {"color": "#6f7680", "width": 2, "dash": "dot"},
            "marker": {
                "color": "#6f7680",
                "size": 7,
                "symbol": "circle-open",
                "line": {"color": "#6f7680", "width": 2},
            },
            "name": "Ideal",
            "meta": {
                "role": "grid-ideal",
                "representation": "ideal",
                "line_segments": "with-markers",
            },
        },
        {
            "type": "scatter",
            "mode": "lines+markers",
            "x": x,
            "y": y,
            "customdata": point_numbers,
            "text": quantized_hover_text,
            "hovertemplate": "%{text}<extra></extra>",
            "line": {"color": "#4368aa", "width": 2},
            "marker": {
                "color": point_numbers,
                "colorscale": [[0, "#0033a0"], [1, "#c49300"]],
                "size": 8,
                "line": {"color": "#ffffff", "width": 1},
            },
            "name": "Quantized",
            "meta": {
                "role": "grid-path",
                "representation": "quantized",
                "line_segments": "with-markers",
            },
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
            "meta": {"role": "grid-start", "representation": "quantized"},
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
            "meta": {"role": "grid-end", "representation": "quantized"},
        },
    ]

    return {
        "data": data,
        "layout": {
            "paper_bgcolor": "#e6eeff",
            "plot_bgcolor": "#d1e0ff",
            "font": {
                "family": "Aptos, Segoe UI, Arial, sans-serif",
                "color": "#000000",
                "size": 14,
            },
            "margin": {"l": 62, "r": 24, "t": 20, "b": 58},
            "hovermode": "closest",
            "showlegend": False,
            "meta": {
                "coordinate_system": coordinate_system,
                "maximum_turntable_tilt": MAX_TURNTABLE_TILT,
                **({"inaccessible_regions": INACCESSIBLE_AZ_EL_REGIONS} if coordinate_system == "az_el" else {}),
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


def _angular_error(actual: float, ideal: float) -> float:
    difference = (actual - ideal + 180.0) % 360.0 - 180.0
    if difference == -180.0 and actual - ideal > 0:
        return 180.0
    return difference


def _quantization_error_figure(
    grid: DesignedGrid,
    *,
    coordinate_system: Literal["az_el", "pan_tilt"],
) -> dict:
    if coordinate_system == "az_el":
        x = [_angular_error(point.azimuth, point.ideal_azimuth) for point in grid.points]
        y = [point.elevation - point.ideal_elevation for point in grid.points]
        x_title = "Azimuth error (°)"
        y_title = "Elevation error (°)"
    else:
        x = [_angular_error(point.pan, point.ideal_pan) for point in grid.points]
        y = [point.tilt - point.ideal_tilt for point in grid.points]
        x_title = "Pan error (°)"
        y_title = "Tilt error (°)"

    point_numbers = [point.traversal_index for point in grid.points]
    hover_text = [
        (
            f"<b>Point {point.traversal_index}</b><br>"
            f"Azimuth error: {_angular_error(point.azimuth, point.ideal_azimuth):.4f}°<br>"
            f"Elevation error: {point.elevation - point.ideal_elevation:.4f}°<br>"
            f"Pan error: {_angular_error(point.pan, point.ideal_pan):.4f}°<br>"
            f"Tilt error: {point.tilt - point.ideal_tilt:.4f}°"
        )
        for point in grid.points
    ]
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "x": x,
                "y": y,
                "customdata": point_numbers,
                "text": hover_text,
                "hovertemplate": "%{text}<extra></extra>",
                "marker": {
                    "color": point_numbers,
                    "colorscale": [[0, "#0033a0"], [1, "#c49300"]],
                    "size": 9,
                    "line": {"color": "#ffffff", "width": 1},
                },
                "name": "Quantization error",
                "meta": {"role": "quantization-error"},
            }
        ],
        "layout": {
            "paper_bgcolor": "#e6eeff",
            "plot_bgcolor": "#d1e0ff",
            "font": {
                "family": "Aptos, Segoe UI, Arial, sans-serif",
                "color": "#000000",
                "size": 14,
            },
            "margin": {"l": 62, "r": 24, "t": 20, "b": 58},
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
            "uirevision": f"quantization-error-{coordinate_system}-{grid.input_system}",
        },
        "config": {
            "displaylogo": False,
            "responsive": True,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    }


def _three_dimensional_figure(grid: DesignedGrid) -> dict:
    coordinates = [_az_el_unit_vector(point.azimuth, point.elevation) for point in grid.points]
    x = [coordinate[0] for coordinate in coordinates]
    y = [coordinate[1] for coordinate in coordinates]
    z = [coordinate[2] for coordinate in coordinates]
    route_coordinates = _interpolated_route_coordinates(grid)
    route_x = [coordinate[0] for coordinate in route_coordinates]
    route_y = [coordinate[1] for coordinate in route_coordinates]
    route_z = [coordinate[2] for coordinate in route_coordinates]
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
            "mode": "lines",
            "x": route_x,
            "y": route_y,
            "z": route_z,
            "line": {"color": "#4368aa", "width": 4},
            "hoverinfo": "skip",
            "name": "Traversal route",
            "showlegend": False,
            "meta": {"role": "grid-route", "line_segments": "line-only"},
        },
        {
            "type": "scatter3d",
            "mode": "markers",
            "x": x,
            "y": y,
            "z": z,
            "customdata": point_numbers,
            "text": hover_text,
            "hovertemplate": "%{text}<extra></extra>",
            "marker": {
                "color": point_numbers,
                "colorscale": [[0, "#0033a0"], [1, "#c49300"]],
                "size": 4,
                "line": {"color": "#ffffff", "width": 1},
            },
            "name": "Measurement points",
            "showlegend": False,
            "meta": {"role": "grid-points"},
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


def _grid_info_row(
    name: str,
    grid: DesignedGrid | None,
    *,
    vertical_movement_multiplier: float = DEFAULT_VERTICAL_MOVEMENT_MULTIPLIER,
) -> dict:
    estimated_seconds = _estimate_grid_travel_time(grid) if grid else 0.0
    cost = (
        _estimate_grid_cost(
            grid,
            vertical_movement_multiplier=vertical_movement_multiplier,
        )
        if grid
        else 0.0
    )
    return {
        "name": name,
        "estimated_travel_time_seconds": estimated_seconds,
        "estimated_travel_time_label": _format_duration(estimated_seconds),
        "cost": cost,
        "cost_label": _format_duration(cost),
        "point_count": len(grid.points) if grid else 0,
        "row_count": grid.row_count if grid else 0,
        "column_count": grid.column_count if grid else 0,
    }


def _preview_context(
    grid: DesignedGrid,
    *,
    grid_info_rows: list[dict] | None = None,
    optimization_context: dict | None = None,
    vertical_movement_multiplier: float = DEFAULT_VERTICAL_MOVEMENT_MULTIPLIER,
    coincident_point_summaries: list[str] | None = None,
) -> dict:
    estimated_travel_time_seconds = _estimate_grid_travel_time(grid)
    return {
        "grid": grid,
        "grid_info_rows": grid_info_rows
        or [
            _grid_info_row(
                "Grid 1",
                grid,
                vertical_movement_multiplier=(vertical_movement_multiplier),
            )
        ],
        "coincident_point_summaries": (coincident_point_summaries or []),
        **(
            optimization_context
            or _optimization_context(
                grid,
                vertical_movement_multiplier=(vertical_movement_multiplier),
            )
        ),
        "estimated_travel_time_seconds": estimated_travel_time_seconds,
        "estimated_travel_time_label": _format_duration(estimated_travel_time_seconds),
        "az_el_figure_json": json.dumps(_figure(grid, coordinate_system="az_el"), allow_nan=False),
        "pan_tilt_figure_json": json.dumps(_figure(grid, coordinate_system="pan_tilt"), allow_nan=False),
        "three_dimensional_figure_json": json.dumps(_three_dimensional_figure(grid), allow_nan=False),
        "az_el_error_figure_json": json.dumps(
            _quantization_error_figure(grid, coordinate_system="az_el"),
            allow_nan=False,
        ),
        "pan_tilt_error_figure_json": json.dumps(
            _quantization_error_figure(grid, coordinate_system="pan_tilt"),
            allow_nan=False,
        ),
        "error": None,
    }


def _build_grid(
    *,
    input_system: Literal["az_el", "pan_tilt"],
    grids: tuple[SimpleGridDefinition, ...],
    quantize_tilt: bool,
    tilt_quantization_origin: float,
    tilt_quantization_step: float,
    quantize_pan: bool,
    pan_quantization_origin: float,
    pan_quantization_step: float,
    reject_inaccessible: bool,
) -> DesignedGrid:
    return design_combined_grid(
        input_system=input_system,
        grids=grids,
        reject_inaccessible=reject_inaccessible,
        pan_quantization=QuantizationDefinition(
            enabled=quantize_pan,
            origin=pan_quantization_origin,
            step=pan_quantization_step,
        ),
        tilt_quantization=QuantizationDefinition(
            enabled=quantize_tilt,
            origin=tilt_quantization_origin,
            step=tilt_quantization_step,
        ),
    )


def _build_grid_info_rows(
    *,
    combined_grid: DesignedGrid,
    input_system: Literal["az_el", "pan_tilt"],
    grids: tuple[SimpleGridDefinition, ...],
    quantize_tilt: bool,
    tilt_quantization_origin: float,
    tilt_quantization_step: float,
    quantize_pan: bool,
    pan_quantization_origin: float,
    pan_quantization_step: float,
    reject_inaccessible: bool,
    vertical_movement_multiplier: float,
) -> tuple[list[dict], list[str]]:
    if len(grids) == 1:
        return (
            [
                _grid_info_row(
                    grids[0].name or "Grid 1",
                    combined_grid,
                    vertical_movement_multiplier=(vertical_movement_multiplier),
                )
            ],
            [],
        )

    rows = [
        _grid_info_row(
            "Combined grid",
            combined_grid,
            vertical_movement_multiplier=(vertical_movement_multiplier),
        )
    ]
    simple_grids: list[DesignedGrid | None] = []
    for index, definition in enumerate(grids):
        try:
            simple_grid = _build_grid(
                input_system=input_system,
                grids=(definition,),
                quantize_tilt=quantize_tilt,
                tilt_quantization_origin=tilt_quantization_origin,
                tilt_quantization_step=tilt_quantization_step,
                quantize_pan=quantize_pan,
                pan_quantization_origin=pan_quantization_origin,
                pan_quantization_step=pan_quantization_step,
                reject_inaccessible=reject_inaccessible,
            )
        except GridValidationError:
            simple_grid = None
        simple_grids.append(simple_grid)
        rows.append(
            _grid_info_row(
                definition.name or f"Grid {index + 1}",
                simple_grid,
                vertical_movement_multiplier=(vertical_movement_multiplier),
            )
        )

    coincident_point_summaries = []
    for left_index, left_grid in enumerate(simple_grids[:-1]):
        if left_grid is None:
            continue
        for right_index in range(left_index + 1, len(simple_grids)):
            right_grid = simple_grids[right_index]
            if right_grid is None:
                continue
            count = count_coincident_points(
                left_grid.points,
                right_grid.points,
                input_system,
            )
            if count == 0:
                continue
            left_name = grids[left_index].name or (f"Grid {left_index + 1}")
            right_name = grids[right_index].name or (f"Grid {right_index + 1}")
            point_word = "point" if count == 1 else "points"
            coincident_point_summaries.append(f"{left_name} and {right_name} have {count:,} coincident {point_word}.")
    if not coincident_point_summaries:
        coincident_point_summaries.append("No coincident points were found between simple grids.")
    return rows, coincident_point_summaries


def _simple_grid_definition(
    input_system: Literal["az_el", "pan_tilt"],
    values: dict[str, float | bool | str],
) -> SimpleGridDefinition:
    if input_system == "az_el":
        return SimpleGridDefinition(
            horizontal=AxisDefinition(
                values["azimuth_min"],
                values["azimuth_max"],
                values["azimuth_step"],
            ),
            vertical=AxisDefinition(
                values["elevation_min"],
                values["elevation_max"],
                values["elevation_step"],
            ),
            name=str(values["grid_name"]),
            cosine_correct_azimuth_spacing=bool(values["cosine_correct_azimuth_spacing"]),
            stagger_alternate_elevation_rows=bool(values["stagger_alternate_elevation_rows"]),
        )
    return SimpleGridDefinition(
        horizontal=AxisDefinition(
            values["pan_min"],
            values["pan_max"],
            values["pan_step"],
        ),
        vertical=AxisDefinition(
            values["tilt_min"],
            values["tilt_max"],
            values["tilt_step"],
        ),
        name=str(values["grid_name"]),
        equal_area_pan_spacing=bool(values["equal_area_pan_spacing"]),
        stagger_alternate_tilt_rows=bool(values["stagger_alternate_tilt_rows"]),
    )


def _parse_number(value: str | float, *, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GridValidationError(f"Enter a number for {label}.") from exc
    if not math.isfinite(number):
        raise GridValidationError(f"Enter a finite number for {label}.")
    return number


def _parse_simple_grids(
    request: Request,
    input_system: Literal["az_el", "pan_tilt"],
) -> tuple[SimpleGridDefinition, ...]:
    names = (
        (
            "azimuth_min",
            "azimuth_max",
            "azimuth_step",
            "elevation_min",
            "elevation_max",
            "elevation_step",
        )
        if input_system == "az_el"
        else (
            "pan_min",
            "pan_max",
            "pan_step",
            "tilt_min",
            "tilt_max",
            "tilt_step",
        )
    )
    raw_values = {name: request.query_params.getlist(name) for name in names}
    grid_count = max((len(values) for values in raw_values.values()), default=0) or 1
    raw_grid_names = request.query_params.getlist("grid_name")
    if raw_grid_names and len(raw_grid_names) != grid_count:
        raise GridValidationError("Every simple grid must have one name.")
    for name, values in raw_values.items():
        if not values:
            raw_values[name] = [str(DEFAULTS[name])] * grid_count
    if any(len(values) != grid_count for values in raw_values.values()):
        raise GridValidationError("Every simple grid must have a complete set of axis parameters.")

    grids = []
    for index in range(grid_count):

        def field_label(name: str) -> str:
            label = (
                name.replace("_min", " minimum")
                .replace("_max", " maximum")
                .replace("_step", " step size")
                .replace("_", " ")
            )
            return f"grid {index + 1} {label}" if grid_count > 1 else label

        values: dict[str, float | bool | str] = {
            name: _parse_number(
                raw_values[name][index],
                label=field_label(name),
            )
            for name in names
        }
        grid_name = raw_grid_names[index].strip() if raw_grid_names else ""
        values["grid_name"] = grid_name or f"Grid {index + 1}"
        options = (
            (
                "cosine_correct_azimuth_spacing",
                "stagger_alternate_elevation_rows",
            )
            if input_system == "az_el"
            else (
                "equal_area_pan_spacing",
                "stagger_alternate_tilt_rows",
            )
        )
        values.update({option: request.query_params.get(f"{option}_{index}") == "true" for option in options})
        grids.append(_simple_grid_definition(input_system, values))
    return tuple(grids)


def _requested_grid(
    request: Request,
    *,
    include_info_rows: bool = True,
) -> tuple[DesignedGrid, list[dict], list[str], float]:
    input_system = request.query_params.get("input_system", "az_el")
    if input_system not in ("az_el", "pan_tilt"):
        raise GridValidationError("Select either azimuth/elevation or pan/tilt input.")
    grids = _parse_simple_grids(request, input_system)
    tilt_origin = _parse_number(
        request.query_params.get(
            "tilt_quantization_origin",
            str(DEFAULTS["tilt_quantization_origin"]),
        ),
        label="tilt quantization origin",
    )
    tilt_step = _parse_number(
        request.query_params.get(
            "tilt_quantization_step",
            str(DEFAULTS["tilt_quantization_step"]),
        ),
        label="tilt quantization step size",
    )
    pan_origin = _parse_number(
        request.query_params.get(
            "pan_quantization_origin",
            str(DEFAULTS["pan_quantization_origin"]),
        ),
        label="pan quantization origin",
    )
    pan_step = _parse_number(
        request.query_params.get(
            "pan_quantization_step",
            str(DEFAULTS["pan_quantization_step"]),
        ),
        label="pan quantization step size",
    )
    quantize_tilt = request.query_params.get("quantize_tilt") == "true"
    quantize_pan = request.query_params.get("quantize_pan") == "true"
    reject_inaccessible = request.query_params.get("reject_inaccessible") == "true"
    vertical_movement_multiplier = _parse_vertical_movement_multiplier(request)
    grid = _build_grid(
        input_system=input_system,
        grids=grids,
        quantize_tilt=quantize_tilt,
        tilt_quantization_origin=tilt_origin,
        tilt_quantization_step=tilt_step,
        quantize_pan=quantize_pan,
        pan_quantization_origin=pan_origin,
        pan_quantization_step=pan_step,
        reject_inaccessible=reject_inaccessible,
    )
    grid_info_rows, coincident_point_summaries = (
        _build_grid_info_rows(
            combined_grid=grid,
            input_system=input_system,
            grids=grids,
            quantize_tilt=quantize_tilt,
            tilt_quantization_origin=tilt_origin,
            tilt_quantization_step=tilt_step,
            quantize_pan=quantize_pan,
            pan_quantization_origin=pan_origin,
            pan_quantization_step=pan_step,
            reject_inaccessible=reject_inaccessible,
            vertical_movement_multiplier=(vertical_movement_multiplier),
        )
        if include_info_rows
        else ([], [])
    )
    return (
        grid,
        grid_info_rows,
        coincident_point_summaries,
        vertical_movement_multiplier,
    )


def _experiment_cuts_from_grid(
    grid: DesignedGrid,
) -> dict[str, experiment.CutDefinition]:
    """Convert a regular pan/tilt grid traversal into horizontal cuts."""
    if grid.input_system != "pan_tilt":
        raise GridValidationError(
            "Experiment design currently supports only pan/tilt input grids."
        )

    rows: dict[int, list[GridPoint]] = {}
    for point in grid.points:
        rows.setdefault(point.row, []).append(point)

    cuts: dict[str, experiment.CutDefinition] = {}
    for cut_number, points in enumerate(rows.values(), start=1):
        tilt = points[0].tilt
        if any(
            not math.isclose(point.tilt, tilt, abs_tol=1e-7)
            for point in points
        ):
            raise GridValidationError(
                f"Grid row {cut_number} does not have one fixed absolute tilt."
            )

        pans = [point.pan for point in points]
        if len(pans) == 1:
            step_size = 1.0
        else:
            deltas = [
                current - previous
                for previous, current in zip(pans, pans[1:])
            ]
            if any(math.isclose(delta, 0.0, abs_tol=1e-9) for delta in deltas):
                raise GridValidationError(
                    f"Grid row {cut_number} contains duplicate pan positions."
                )
            step_size = abs(deltas[0])
            irregular_spacing = any(
                not math.isclose(abs(delta), step_size, abs_tol=1e-7)
                for delta in deltas[1:]
            )

        cut_id = f"row-{cut_number:03d}-tilt-{tilt:+g}"
        cut = experiment.CutDefinition(
            direction="horizontal",
            start_angle=pans[0],
            end_angle=pans[-1],
            step_size=step_size,
            fixed_angle=tilt,
            reset_before=False,
            angles=pans if len(pans) > 1 and irregular_spacing else None,
        )
        generated = cut.coordinates
        if len(generated) != len(points) or any(
            not math.isclose(coordinate.pan, pan, abs_tol=1e-7)
            or not math.isclose(coordinate.tilt, tilt, abs_tol=1e-7)
            for coordinate, pan in zip(generated, pans)
        ):
            raise GridValidationError(
                f"Grid row {cut_number} cannot be represented exactly as an "
                "experiment cut."
            )
        cuts[cut_id] = cut
    return cuts


def _experiment_design_parameters(
    request: Request,
    grid: DesignedGrid,
    *,
    relative_folder_path: Path,
) -> experiment.ExperimentParameters:
    folder_name = request.query_params.get("folder_name", "").strip()
    short_description = (
        request.query_params.get("short_description", "").strip()
        or folder_name
    )
    long_description = request.query_params.get("long_description", "").strip()
    center_frequency = _parse_number(
        request.query_params.get("center_frequency", "8457300000"),
        label="center frequency",
    )
    signal_power = _parse_number(
        request.query_params.get("signal_power", "10"),
        label="signal generator power",
    )
    vernier_power = _parse_number(
        request.query_params.get("vernier_power", "0"),
        label="signal generator vernier power",
    )
    reference_level = _parse_number(
        request.query_params.get("reference_level", "-40"),
        label="spectrum analyzer reference level",
    )
    span = _parse_number(
        request.query_params.get("span", "10000"),
        label="spectrum analyzer span",
    )
    if center_frequency <= 0:
        raise GridValidationError("Center frequency must be greater than zero.")
    if span <= 0:
        raise GridValidationError(
            "Spectrum analyzer span must be greater than zero."
        )
    polarization = request.query_params.get("polarization", "horizontal")
    if polarization not in {"horizontal", "vertical"}:
        raise GridValidationError("Select horizontal or vertical polarization.")
    log_level = request.query_params.get("log_level", "DEBUG")
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise GridValidationError("Select a valid log level.")

    return experiment.ExperimentParameters(
        short_description=short_description,
        long_description=long_description,
        relative_folder_path=relative_folder_path,
        cuts=_experiment_cuts_from_grid(grid),
        sig_gen_config=experiment.SigGenConfig(
            center_frequency=center_frequency,
            power=signal_power,
            vernier_power=vernier_power,
        ),
        spec_an_config=experiment.SpecAnConfig(
            center_frequency=center_frequency,
            reference_level=reference_level,
            span=span,
        ),
        polarization_config=experiment.PolarizationConfig(kind=polarization),
        log_level=log_level,
        collect_center_frequency_data=(
            request.query_params.get("collect_center_frequency_data") == "true"
        ),
        collect_peak_data=request.query_params.get("collect_peak_data") == "true",
        collect_trace_data=request.query_params.get("collect_trace_data") == "true",
    )


def _save_experiment_design(
    request: Request,
    *,
    experiments_root: Path | None = None,
) -> tuple[Path, experiment.ExperimentParameters]:
    folder_name = request.query_params.get("folder_name", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", folder_name):
        raise GridValidationError(
            "Folder name must start with a letter or number and contain only "
            "letters, numbers, dots, underscores, or hyphens."
        )
    grid, _, _, _ = _requested_grid(request, include_info_rows=False)
    root = (experiments_root or experiment.EXPERIMENTS_FOLDER_PATH).resolve()
    output_folder = root / folder_name
    if output_folder.exists():
        raise GridValidationError(
            f"Experiment folder already exists: {output_folder}"
        )
    try:
        relative_folder = output_folder.relative_to(Path.cwd())
    except ValueError:
        relative_folder = output_folder
    parameters = _experiment_design_parameters(
        request,
        grid,
        relative_folder_path=relative_folder,
    )
    parameters_json = parameters.model_dump_json(indent=4, exclude_none=True)
    root.mkdir(parents=True, exist_ok=True)
    output_folder.mkdir()
    parameters_path = output_folder / "parameters.json"
    parameters_path.write_text(parameters_json + "\n", encoding="utf-8")
    return parameters_path, parameters


def _parse_optimization_time(request: Request) -> float:
    max_seconds = _parse_number(
        request.query_params.get(
            "optimization_max_time",
            str(DEFAULT_OPTIMIZATION_TIME_SECONDS),
        ),
        label="maximum optimization time",
    )
    if max_seconds <= 0.0:
        raise GridValidationError("Maximum optimization time must be greater than zero.")
    if max_seconds > MAX_OPTIMIZATION_TIME_SECONDS:
        raise GridValidationError("Maximum optimization time cannot exceed 60 seconds.")
    return max_seconds


def _parse_vertical_movement_multiplier(request: Request) -> float:
    multiplier = _parse_number(
        request.query_params.get(
            "vertical_movement_multiplier",
            str(DEFAULT_VERTICAL_MOVEMENT_MULTIPLIER),
        ),
        label="vertical movement multiplier",
    )
    if multiplier <= 0.0:
        raise GridValidationError("Vertical movement multiplier must be greater than zero.")
    if multiplier > MAX_VERTICAL_MOVEMENT_MULTIPLIER:
        raise GridValidationError("Vertical movement multiplier cannot exceed 100.")
    return multiplier


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={},
    )


@app.get("/grid-designer", response_class=HTMLResponse)
def grid_designer(request: Request) -> HTMLResponse:
    simple_grids = (
        _simple_grid_definition(
            DEFAULTS["input_system"],
            DEFAULTS,
        ),
    )
    grid = _build_grid(
        input_system=DEFAULTS["input_system"],
        grids=simple_grids,
        quantize_tilt=DEFAULTS["quantize_tilt"],
        tilt_quantization_origin=DEFAULTS["tilt_quantization_origin"],
        tilt_quantization_step=DEFAULTS["tilt_quantization_step"],
        quantize_pan=DEFAULTS["quantize_pan"],
        pan_quantization_origin=DEFAULTS["pan_quantization_origin"],
        pan_quantization_step=DEFAULTS["pan_quantization_step"],
        reject_inaccessible=DEFAULTS["reject_inaccessible"],
    )
    (
        grid_info_rows,
        coincident_point_summaries,
    ) = _build_grid_info_rows(
        combined_grid=grid,
        input_system=DEFAULTS["input_system"],
        grids=simple_grids,
        quantize_tilt=DEFAULTS["quantize_tilt"],
        tilt_quantization_origin=DEFAULTS["tilt_quantization_origin"],
        tilt_quantization_step=DEFAULTS["tilt_quantization_step"],
        quantize_pan=DEFAULTS["quantize_pan"],
        pan_quantization_origin=DEFAULTS["pan_quantization_origin"],
        pan_quantization_step=DEFAULTS["pan_quantization_step"],
        reject_inaccessible=DEFAULTS["reject_inaccessible"],
        vertical_movement_multiplier=(DEFAULT_VERTICAL_MOVEMENT_MULTIPLIER),
    )
    return templates.TemplateResponse(
        request=request,
        name="grid_designer.html",
        context={
            **DEFAULTS,
            "simple_grids": [dict(DEFAULTS)],
            **_preview_context(
                grid,
                grid_info_rows=grid_info_rows,
                vertical_movement_multiplier=(DEFAULT_VERTICAL_MOVEMENT_MULTIPLIER),
                coincident_point_summaries=(coincident_point_summaries),
            ),
        },
    )


@app.get("/experiment/design", response_class=HTMLResponse)
def experiment_designer(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="experiment_designer.html",
        context={},
    )


class _TurntablePositionCommand(BaseModel):
    pan: float
    tilt: float
    timeout: float | None = None


class _ExperimentLoadRequest(BaseModel):
    definition: dict[str, object]
    filename: str | None = None


class _ExperimentServerLoadRequest(BaseModel):
    path: str


class _ExperimentStartRequest(BaseModel):
    output_mode: Literal["new", "continue", "append", "overwrite"] = "new"


@app.get("/experiment", response_class=HTMLResponse)
def experiment_control(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="experiment.html",
        context={
            "available_definitions": experiment_service.available_definitions(),
        },
    )


@app.get("/experiment/graphs", response_class=HTMLResponse)
def experiment_graphs(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="experiment_graphs.html",
    )


@app.get("/experiment/status")
def experiment_status() -> dict:
    return experiment_service.snapshot()


@app.get("/experiment/results")
def experiment_results() -> dict:
    try:
        return experiment_service.results_payload()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/experiment/plan")
def experiment_plan() -> dict:
    try:
        return experiment_service.plan_payload()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/experiment/load")
def load_experiment(command: _ExperimentLoadRequest) -> dict:
    try:
        return experiment_service.load_definition(command.definition, source_name=command.filename)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/experiment/load-server")
def load_server_experiment(command: _ExperimentServerLoadRequest) -> dict:
    try:
        return experiment_service.load_server_definition(command.path)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/experiment/start")
def start_experiment(command: _ExperimentStartRequest) -> dict:
    try:
        return experiment_service.start(output_mode=command.output_mode)
    except (RuntimeError, TurntableError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/experiment/abort")
def abort_experiment() -> dict:
    try:
        return experiment_service.abort()
    except (RuntimeError, TurntableError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/turntable", response_class=HTMLResponse)
def turntable_control(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="turntable.html",
        context={
            "history_max_time": DEFAULT_HISTORY_MAX_TIME,
            "history_rate": DEFAULT_HISTORY_RATE,
            "recent_history_time": DEFAULT_RECENT_HISTORY_TIME,
            "recent_history_rate": DEFAULT_RECENT_HISTORY_RATE,
            "refresh_interval": DEFAULT_REFRESH_INTERVAL,
            "timeout_safety_factor": MOVE_TIMEOUT_SAFETY_FACTOR,
            "timeout_minimum": MOVE_TIMEOUT_MINIMUM,
        },
    )


@app.get("/turntable/status")
def turntable_status(
    max_time: float = DEFAULT_HISTORY_MAX_TIME,
    max_points: int = DEFAULT_HISTORY_MAX_POINTS,
    after: datetime.datetime | None = None,
) -> dict:
    try:
        return turntable_service.status_payload(max_time=max_time, max_points=max_points, after=after)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/turntable/set")
def set_turntable_position(command: _TurntablePositionCommand) -> dict:
    try:
        turntable_service.set_position(pan=command.pan, tilt=command.tilt)
    except (RuntimeError, TurntableError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": f"Queued SET for pan={command.pan:g}°, tilt={command.tilt:g}°."}


@app.post("/turntable/move")
def move_turntable(command: _TurntablePositionCommand) -> dict:
    try:
        timing = turntable_service.move_to(
            pan=command.pan,
            tilt=command.tilt,
            timeout=command.timeout,
        )
    except (RuntimeError, TurntableError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "message": (
            f"Queued move to pan={command.pan:g}°, tilt={command.tilt:g}° "
            f"with a {timing['timeout']:.2f} sec timeout."
        ),
        **timing,
    }


@app.post("/turntable/confirm")
def confirm_turntable_position() -> dict:
    try:
        turntable_service.confirm_position()
    except (RuntimeError, TurntableError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "message": "Confirmed the currently reported position without sending SET.",
    }


@app.post("/turntable/abort")
def abort_turntable() -> dict:
    try:
        turntable_service.abort()
    except (RuntimeError, TurntableError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": "Emergency stop sent."}


@app.get("/grid-designer/preview", response_class=HTMLResponse)
def grid_designer_preview(request: Request) -> HTMLResponse:
    try:
        (
            grid,
            grid_info_rows,
            coincident_point_summaries,
            vertical_movement_multiplier,
        ) = _requested_grid(request)
        context = _preview_context(
            grid,
            grid_info_rows=grid_info_rows,
            vertical_movement_multiplier=(vertical_movement_multiplier),
            coincident_point_summaries=(coincident_point_summaries),
        )
    except GridValidationError as exc:
        context = {"grid": None, "error": str(exc)}

    return templates.TemplateResponse(
        request=request,
        name="_grid_preview.html",
        context=context,
    )


@app.post("/experiment/design")
def save_experiment_design(request: Request) -> dict:
    try:
        parameters_path, parameters = _save_experiment_design(request)
    except (GridValidationError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "path": str(parameters_path),
        "folder": str(parameters_path.parent),
        "cut_count": len(parameters.cuts or {}),
        "point_count": sum(
            len(cut) for cut in (parameters.cuts or {}).values()
        ),
    }


@app.get("/grid-designer/optimize", response_class=HTMLResponse)
def optimize_grid_path(request: Request) -> HTMLResponse:
    try:
        (
            grid,
            _,
            _,
            vertical_movement_multiplier,
        ) = _requested_grid(request, include_info_rows=False)
        max_seconds = _parse_optimization_time(request)
        requested_session_id = request.query_params.get(
            "optimization_session_id",
            "",
        )
        session = _get_optimization_session(requested_session_id, grid)
        if session is None:
            session_id, session = _new_optimization_session(
                grid,
                vertical_movement_multiplier=(vertical_movement_multiplier),
            )
        else:
            session_id = requested_session_id

        evaluated_paths = [
            (
                index,
                path,
                _ordered_grid_cost(
                    grid.points,
                    path.order,
                    vertical_movement_multiplier=(vertical_movement_multiplier),
                ),
            )
            for index, path in enumerate(session.paths)
        ]
        (
            starting_path_index,
            starting_path,
            starting_cost,
        ) = min(evaluated_paths, key=lambda item: item[2])
        calculation_started = time.perf_counter()
        optimized_order, optimized_cost = _optimize_grid_route(
            grid,
            starting_order=starting_path.order,
            max_seconds=max_seconds,
            vertical_movement_multiplier=(vertical_movement_multiplier),
            random_seed=secrets.randbits(64),
        )
        calculation_seconds = time.perf_counter() - calculation_started
        estimated_seconds = _ordered_grid_travel_time(
            grid.points,
            optimized_order,
        )

        cost_improved = optimized_cost < starting_cost - 1e-6
        multiplier_changed = not math.isclose(
            starting_path.vertical_movement_multiplier,
            vertical_movement_multiplier,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        if cost_improved or multiplier_changed:
            path = _OptimizationPath(
                name=(f"Optimized path #{session.next_optimization_number}"),
                order=optimized_order,
                estimated_seconds=estimated_seconds,
                cost=optimized_cost,
                vertical_movement_multiplier=(vertical_movement_multiplier),
                calculation_seconds=calculation_seconds,
            )
            with _optimization_sessions_lock:
                session.next_optimization_number += 1
                session.paths.append(path)
                if len(session.paths) > MAX_OPTIMIZATION_HISTORY:
                    session.paths = [
                        session.paths[0],
                        *session.paths[-(MAX_OPTIMIZATION_HISTORY - 1) :],
                    ]
                session.active_path_index = len(session.paths) - 1
            if cost_improved:
                improvement = starting_cost - optimized_cost
                status = f"Found a path with {_format_duration(improvement)} lower cost."
            else:
                status = (
                    "Saved the best known path with a "
                    f"{vertical_movement_multiplier:g}× vertical "
                    "movement multiplier; no lower-cost route was found."
                )
        else:
            with _optimization_sessions_lock:
                session.active_path_index = starting_path_index
            path = starting_path
            status = f"No lower-cost path found in {max_seconds:g} seconds."

        optimized_grid = _grid_with_order(grid, path.order)
        context = _preview_context(
            optimized_grid,
            grid_info_rows=[
                _grid_info_row(
                    path.name,
                    optimized_grid,
                    vertical_movement_multiplier=(vertical_movement_multiplier),
                )
            ],
            vertical_movement_multiplier=(vertical_movement_multiplier),
            optimization_context=_optimization_context(
                optimized_grid,
                session_id=session_id,
                session=session,
                max_time_seconds=max_seconds,
                vertical_movement_multiplier=(vertical_movement_multiplier),
                status=status,
            ),
        )
    except (GridValidationError, ValueError) as exc:
        context = {"grid": None, "error": str(exc)}

    return templates.TemplateResponse(
        request=request,
        name="_grid_preview.html",
        context=context,
    )


@app.get("/grid-designer/optimization/load", response_class=HTMLResponse)
def load_optimized_grid_path(request: Request) -> HTMLResponse:
    try:
        (
            grid,
            _,
            _,
            vertical_movement_multiplier,
        ) = _requested_grid(request, include_info_rows=False)
        max_seconds = _parse_optimization_time(request)
        session_id = request.query_params.get(
            "optimization_session_id",
            "",
        )
        session = _get_optimization_session(session_id, grid)
        if session is None:
            raise GridValidationError(
                "This optimization history has expired or no longer matches the grid. Calculate a new path."
            )
        try:
            path_index = int(request.query_params.get("optimization_path", ""))
            path = session.paths[path_index]
        except (ValueError, IndexError) as exc:
            raise GridValidationError("Select a valid optimized path to load.") from exc
        if path_index < 0:
            raise GridValidationError("Select a valid optimized path to load.")

        with _optimization_sessions_lock:
            session.active_path_index = path_index
        loaded_grid = _grid_with_order(grid, path.order)
        context = _preview_context(
            loaded_grid,
            grid_info_rows=[
                _grid_info_row(
                    path.name,
                    loaded_grid,
                    vertical_movement_multiplier=(vertical_movement_multiplier),
                )
            ],
            vertical_movement_multiplier=(vertical_movement_multiplier),
            optimization_context=_optimization_context(
                loaded_grid,
                session_id=session_id,
                session=session,
                max_time_seconds=max_seconds,
                vertical_movement_multiplier=(vertical_movement_multiplier),
                status=f"Loaded {path.name}.",
            ),
        )
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

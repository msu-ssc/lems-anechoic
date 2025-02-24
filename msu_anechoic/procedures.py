from __future__ import annotations

from typing import Callable
from typing import Literal

import numpy as np
import scipy.interpolate

from msu_anechoic import AzEl
from msu_anechoic import spec_an
from msu_anechoic import turn_table


def generate_grid(
    *,
    azimuth_min: float,
    azimuth_max: float,
    elevation_min: float,
    elevation_max: float,
    azimuth_step_count: int = 5,
    elevation_step_count: int = 5,
    starting_point: AzEl | None = None,
    preferred_travel: Literal["azimuth", "elevation"] | None = None,
) -> list[AzEl]:
    """Generate a grid of AzEl points."""
    azimuths = np.linspace(azimuth_min, azimuth_max, azimuth_step_count)
    elevations = np.linspace(elevation_min, elevation_max, elevation_step_count)

    if not preferred_travel:
        azimuth_distance = azimuth_max - azimuth_min
        elevation_distance = elevation_max - elevation_min
        azimuth_preferred_distance = (elevation_step_count - 1) * azimuth_distance + elevation_distance
        elevation_preferred_distance = (azimuth_step_count - 1) * elevation_distance + azimuth_distance
        if azimuth_preferred_distance < elevation_preferred_distance:
            preferred_travel = "azimuth"
        else:
            preferred_travel = "elevation"

    # Determine which corner to start in, if a starting point is given
    if starting_point is not None:
        corners = {
            "UL": AzEl(azimuth=azimuth_min, elevation=elevation_max),
            "UR": AzEl(azimuth=azimuth_max, elevation=elevation_max),
            "LL": AzEl(azimuth=azimuth_min, elevation=elevation_min),
            "LR": AzEl(azimuth=azimuth_max, elevation=elevation_min),
        }
        best_distnce = float("inf")
        best_corner = None
        for corner_name, corner in corners.items():
            # EUCLIDEAN DISTANCE:
            # distance_to_corner = np.sqrt(
            #     (starting_point.azimuth - corner.azimuth) ** 2
            #     + (starting_point.elevation - corner.elevation) ** 2
            # )

            # TAXICAB DISTANCE:
            distance_to_corner = abs(starting_point.azimuth - corner.azimuth) + abs(
                starting_point.elevation - corner.elevation
            )

            # MAXIMUM DISTANCE:
            # distance_to_corner = max(abs(starting_point.azimuth - corner.azimuth), abs(starting_point.elevation - corner.elevation))

            if distance_to_corner < best_distnce:
                best_distnce = distance_to_corner
                best_corner = corner_name

        assert best_corner is not None
        if best_corner[0] == "U":
            elevations = list(reversed(elevations))
        if best_corner[1] == "R":
            azimuths = list(reversed(azimuths))

    return_value = []

    if preferred_travel == "azimuth":
        for elevation_index, elevation in enumerate(elevations):
            # Want to go in reverse order of azimuths on alternate elevation to minimize travel distance
            if elevation_index % 2 == 1:
                this_row_azimuths = list(reversed(azimuths))
            else:
                this_row_azimuths = list(azimuths)

            for azimuth in this_row_azimuths:
                return_value.append(AzEl(azimuth=float(azimuth), elevation=float(elevation)))
    elif preferred_travel == "elevation":
        for azimuth_index, azimuth in enumerate(azimuths):
            # Want to go in reverse order of elevations on alternate azimuth to minimize travel distance
            if azimuth_index % 2 == 1:
                this_row_elevations = list(reversed(elevations))
            else:
                this_row_elevations = list(elevations)

            for elevation in this_row_elevations:
                return_value.append(AzEl(azimuth=float(azimuth), elevation=float(elevation)))
    return return_value


def user_guided_box_scan(
    *,
    spec_an: spec_an.SpectrumAnalyzerHP8563E,
    turn_table: turn_table.Turntable,
    azimuth_min: float,
    azimuth_max: float,
    elevation_min: float,
    elevation_max: float,
    azimuth_step_count: int = 5,
    elevation_step_count: int = 5,
    function_to_maximize: Callable[
        [spec_an.SpectrumAnalyzerHP8563E], float
    ] = spec_an.SpectrumAnalyzerHP8563E.get_center_frequency_amplitude,
) -> AzEl:
    """Perform a user-guided box scan."""

    # Prompt the user for the azimuth and elevation ranges
    azimuth_min = float(input("Enter the minimum azimuth: "))
    azimuth_max = float(input("Enter the maximum azimuth: "))
    elevation_min = float(input("Enter the minimum elevation: "))
    elevation_max = float(input("Enter the maximum elevation: "))

    # Prompt the user for the number of steps in each direction
    azimuth_step_count = int(input("Enter the number of azimuth steps (i.e., number of grid columns): "))
    elevation_step_count = int(input("Enter the number of elevation steps (i.e., number of grid rows): "))

    # # Prompt user for current location, if known
    # if input("Do you know the current location of the turntable? (y/n): ").lower() == "y":
    #     azimuth = float(input("Enter the current azimuth: "))
    #     elevation = float(input("Enter the current elevation: "))
    #     starting_point = AzEl(azimuth=azimuth, elevation=elevation)
    # else:
    #     starting_point = None
    try:
        starting_point = turn_table.get_position()
    except Exception:
        starting_point = None

    grid = generate_grid(
        azimuth_min=azimuth_min,
        azimuth_max=azimuth_max,
        elevation_min=elevation_min,
        elevation_max=elevation_max,
        azimuth_step_count=azimuth_step_count,
        elevation_step_count=elevation_step_count,
        starting_point=starting_point,
    )

    print(f"Doing grid search on {len(grid)} points. Measuring with method {function_to_maximize.__name__}")

    # Perform the box scan
    data: dict[AzEl, float] = {}
    for point in grid:
        turn_table.move_to(azimuth=point.azimuth, elevation=point.elevation)
        amplitude = function_to_maximize(spec_an)
        data[point] = amplitude

    # Plot the data
    xs = [point.azimuth for point in grid]
    ys = [point.elevation for point in grid]

    xi = np.linspace(min(xs), max(xs), 100)
    yi = np.linspace(min(ys), max(ys), 100)
    X, Y = np.meshgrid(xi, yi)
    Z = scipy.interpolate.griddata((xs, ys), list(data.values()), (X, Y), method="nearest")

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(layout="constrained")
    ax.plot(xs, ys, "o", color="black")
    for index in range(len(grid)):
        ax.text(xs[index], ys[index], f"{list(data.values())[index]:.2f}")

    c = ax.pcolormesh(X, Y, Z, cmap="coolwarm")
    fig.colorbar(c, label="Signal Strength", ax=ax)

    ax.set_xlabel("Azimuth")
    ax.set_ylabel("Elevation")
    ax.set_xlim(azimuth_min - 0.5, azimuth_max + 0.5)
    ax.set_ylim(elevation_min - 0.5, elevation_max + 0.5)

    # Find the point with the strongest signal
    strongest_signal_index = np.argmax(list(data.values()))
    strongest_signal_point = grid[strongest_signal_index]
    strongest_signal = list(data.values())[strongest_signal_index]

    ax.set_title(
        f"Box scan (azimuth: [{azimuth_min:.2f}, {azimuth_max:.2f}], elevation: [{elevation_min:.2f}, {elevation_max:.2f}])"
        + f"\nStrongest observed signal ({strongest_signal:.2f}) at {strongest_signal_point}"
    )

    print(f"Strongest observed signal ({strongest_signal:.2f}) at {strongest_signal_point}")
    print(f"Displaying graph of {len(grid)} points. Close the graph to continue. Close the graph to continue.")
    plt.show()

    return strongest_signal_point


# def box_scan(
#     *,
#     spec_an: spec_an.SpectrumAnalyzerHP8563E,
#     turn_table: turn_table.TurnTable,v
#     azimuth_min: float,
#     azimuth_max: float,
#     elevation_min: float,
#     elevation_max: float,
#     azimuth_step_count: int = 5,
#     elevation_step_count: int = 5,
#     function_to_maximize: Callable[
#         [spec_an.SpectrumAnalyzerHP8563E], float
#     ] = spec_an.SpectrumAnalyzerHP8563E.get_center_frequency_amplitude,
# ):
#     """Perform a box scan."""
#     azimuths = np.linspace(azimuth_min, azimuth_max, azimuth_step_count)
#     elevations = np.linspace(elevation_min, elevation_max, elevation_step_count)

#     data: dict[AzEl, float] = {}
#     for elevation_index, elevation in enumerate(elevations):
#         # Want to go in reverse order of azimuths on alternate elevation to minimize travel distance

#         if elevation_index % 2 == 0:
#             this_row_azimuths = reversed(azimuths)
#         else:
#             this_row_azimuths = azimuths

#         for azimuth_index, azimuth in enumerate(this_row_azimuths):
#             az_el = AzEl(azimuth=azimuth, elevation=elevation)

#             turn_table.move_to(azimuth=azimuth, elevation=elevation)
#             amplitude = function_to_maximize(spec_an)
#             data[az_el] = amplitude

#     pass


if __name__ == "__main__":
    from msu_ssc import ssc_log
    ssc_log.init(level="DEBUG")
    logger = ssc_log.logger.getChild("procedures")

    tt = turn_table.Turntable(
        port="COM5",
        logger=logger,
    )
    with spec_an.SpectrumAnalyzerHP8563E.find(
        logger=logger
    ) as spectrum_analyzer:
        print(spectrum_analyzer)
        print(tt)

        

        print(f"{tt=}")
        print(f"{spectrum_analyzer=}")
        spectrum_analyzer.set_center_frequency(8_450_000_453)
        spectrum_analyzer.set_span(1_000)
        print(f"{spectrum_analyzer.get_center_frequency_amplitude()=}")
        print(f"{spectrum_analyzer.get_center_frequency()=}")
        print(f"{spectrum_analyzer.get_span()=}")
        # exit()
        tt.interactively_center()
        user_guided_box_scan(
            spec_an=spectrum_analyzer,
            turn_table=tt,
            azimuth_max=10,
            azimuth_min=-10,
            elevation_max=10,
            elevation_min=-10,
            azimuth_step_count=5,
            elevation_step_count=3,
            function_to_maximize=spec_an.SpectrumAnalyzerHP8563E.get_highest_amplitude,
        )
    exit()
    import random

    rand = random.Random(40351)

    turn_table_starting_point = AzEl(azimuth=-1.5, elevation=-3.5)
    azimuth_min = -5
    azimuth_max = 5
    elevation_min = -2
    elevation_max = 2
    grid = generate_grid(
        azimuth_min=azimuth_min,
        azimuth_max=azimuth_max,
        elevation_min=elevation_min,
        elevation_max=elevation_max,
        azimuth_step_count=7,
        elevation_step_count=3,
        starting_point=turn_table_starting_point,
    )
    from rich.pretty import pprint

    pprint(grid)

    strongest_signal_point = AzEl(azimuth=0.2, elevation=0.7)
    powers = []
    for point in grid:
        # Signal strengh is 30 minus (Euclidean distance to the strongest signal point)
        # NOTE: THIS IS NOT REALISITC!! BUT IT'S EASY TO IMPLEMENT IN CODE
        max_signal = 30
        distance_to_best = np.sqrt(
            (point.azimuth - strongest_signal_point.azimuth) ** 2
            + (point.elevation - strongest_signal_point.elevation) ** 2
        )
        signal = max_signal - distance_to_best

        # Add noise
        signal += rand.gauss(0, 0.1)

        powers.append(signal)

    xs = [point.azimuth for point in grid]
    ys = [point.elevation for point in grid]

    xi = np.linspace(min(xs), max(xs), 100)
    yi = np.linspace(min(ys), max(ys), 100)
    X, Y = np.meshgrid(xi, yi)
    Z = scipy.interpolate.griddata((xs, ys), powers, (X, Y), method="nearest")

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(layout="constrained")
    ax.plot(xs, ys, "o", color="black")
    for index in range(len(grid)):
        ax.text(xs[index], ys[index], f"{powers[index]:.2f}")
    # if turn_table_starting_point:
    #     ax.plot(turn_table_starting_point.azimuth, turn_table_starting_point.elevation, "X", color="red", markersize=10)

    c = ax.pcolormesh(X, Y, Z, cmap="coolwarm")
    # c = ax.tricontourf(xs, ys, powers, cmap="coolwarm", levels=100)
    # fig.colorbar(c, label="Signal Strength", ax=ax)

    ax.set_xlabel("Azimuth")
    ax.set_ylabel("Elevation")
    ax.set_xlim(azimuth_min - 0.5, azimuth_max + 0.5)
    ax.set_ylim(elevation_min - 0.5, elevation_max + 0.5)
    # ax.pcolormesh(xs, ys, zs, cmap="viridis")

    # Find the point with the strongest signal
    strongest_signal_index = np.argmax(powers)
    strongest_signal_point = grid[strongest_signal_index]
    strongest_signal = powers[strongest_signal_index]

    ax.set_title(
        f"Box scan (azimuth: [{azimuth_min:.2f}, {azimuth_max:.2f}], elevation: [{elevation_min:.2f}, {elevation_max:.2f}])"
        + f"\nStrongest observed signal ({strongest_signal:.2f}) at {strongest_signal_point}"
    )
    ax.axhline(strongest_signal_point.elevation, color="white", linestyle="--")
    ax.axvline(strongest_signal_point.azimuth, color="white", linestyle="--")
    ax.plot(strongest_signal_point.azimuth, strongest_signal_point.elevation, "o", color="white", markersize=10)

    # ax.plot(strongest_signal_point.azimuth, strongest_signal_point.elevation, "o", color="white", markersize=10)
    plt.show()

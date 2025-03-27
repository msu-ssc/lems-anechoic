from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Literal

import numpy as np

from msu_anechoic import AzEl

if TYPE_CHECKING:
    import matplotlib.pyplot as plt


def estimated_step_time(
    *,
    azimuth: float,
    elevation: float,
) -> float:
    """Estimate the time it will take to move a given step in  azimuth and elevation.

    This function is a simple linear model based on the data in `turntable_move_times.csv`.
    These values were empirically measured by David Mayo in February 2025.

    IMPORTANT: If azimuth or elevation is less than 0.1, it is treated as not moving. This reflects the turntable firmware code,
    where that 0.1 margin is hardcoded.
    """
    azimuth_time = 0.0
    elevation_time = 0.0
    if abs(azimuth) > 0.1:
        azimuth_time = 0.39 * abs(azimuth) + 2.71
    if abs(elevation) > 0.1:
        elevation_time = 0.94 * abs(elevation) + 3.25
    return max(azimuth_time, elevation_time)


class GridPattern:
    def __init__(
        self,
        *,
        azimuth_min: float,
        azimuth_max: float,
        elevation_min: float,
        elevation_max: float,
        azimuth_step_count: int | None = None,
        azimuth_step_size: float | None = None,
        elevation_step_count: int | None = None,
        elevation_step_size: float | None = None,
        start_corner: Literal["UL", "UR", "LL", "LR"],
        initial_position: AzEl | None = None,
        direction: Literal["HORIZONTAL", "VERTICAL"],
    ):
        self.azimuth_min = azimuth_min
        self.azimuth_max = azimuth_max
        self.elevation_min = elevation_min
        self.elevation_max = elevation_max

        # AZIMUTH STEPS
        if azimuth_step_count is None and azimuth_step_size is None:
            raise ValueError("Must provide either `azimuth_step_count` or `azimuth_step_size`")
        if azimuth_step_count is not None and azimuth_step_size is not None:
            raise ValueError("Cannot provide both `azimuth_step_count` and `azimuth_step_size`")
        if azimuth_step_count is not None:
            self.azimuth_step_count = azimuth_step_count
            self._azimuth_step_size = (self.azimuth_max - self.azimuth_min) / (self.azimuth_step_count - 1)
        else:
            self._azimuth_step_size = azimuth_step_size
            self.azimuth_step_count: int = int(
                np.round((self.azimuth_max - self.azimuth_min) / self._azimuth_step_size) + 1
            )

        # self.azimuth_step_count = azimuth_step_count

        # ELEVATION STEPS
        if elevation_step_count is None and elevation_step_size is None:
            raise ValueError("Must provide either `elevation_step_count` or `elevation_step_size`")
        if elevation_step_count is not None and elevation_step_size is not None:
            raise ValueError("Cannot provide both `elevation_step_count` and `elevation_step_size`")
        if elevation_step_count is not None:
            self.elevation_step_count = elevation_step_count
            self._elevation_step_size = (self.elevation_max - self.elevation_min) / (self.elevation_step_count - 1)
        else:
            self._elevation_step_size = elevation_step_size
            self.elevation_step_count: int = int(
                np.round((self.elevation_max - self.elevation_min) / self._elevation_step_size) + 1
            )

        # self.elevation_step_count = elevation_step_count
        self.direction = direction

        self.points: list[AzEl] = []
        self.initial_position = initial_position
        self.azimuth_values = [
            float(x) for x in np.linspace(self.azimuth_min, self.azimuth_max, self.azimuth_step_count)
        ]
        self.elevation_values = [
            float(x) for x in np.linspace(self.elevation_min, self.elevation_max, self.elevation_step_count)
        ]

        self.start_corner = start_corner
        if self.start_corner[0] == "U":
            self.elevation_values.reverse()
        if self.start_corner[1] == "R":
            self.azimuth_values.reverse()

        if self.direction == "HORIZONTAL":
            for elevation_index, elevation in enumerate(self.elevation_values):
                row_azimuths = self.azimuth_values[:]
                if elevation_index % 2 == 1:
                    row_azimuths.reverse()
                for azimuth_index, azimuth in enumerate(row_azimuths):
                    self.points.append(AzEl(azimuth, elevation))
        elif self.direction == "VERTICAL":
            for azimuth_index, azimuth in enumerate(self.azimuth_values):
                column_elevations = self.elevation_values[:]
                if azimuth_index % 2 == 1:
                    column_elevations.reverse()
                for elevation_index, elevation in enumerate(column_elevations):
                    self.points.append(AzEl(azimuth, elevation))
        else:
            raise ValueError(f"Invalid direction: {self.direction}")

    def height(self) -> float:
        return abs(self.elevation_max - self.elevation_min)

    def width(self) -> float:
        return abs(self.azimuth_max - self.azimuth_min)

    def elevation_step_size(self) -> float:
        return self._elevation_step_size
        # if self.elevation_step_count == 1:
        #     return 0
        # return self.height() / (self.elevation_step_count - 1)

    def azimuth_step_size(self) -> float:
        return self._azimuth_step_size
        # if self.azimuth_step_count == 1:
        #     return 0
        # return self.width() / (self.azimuth_step_count - 1)

    def elevation_steps(self) -> int:
        if self.direction == "HORIZONTAL":
            return self.elevation_step_count - 1
        elif self.direction == "VERTICAL":
            total_steps = self.azimuth_step_count * self.elevation_step_count
            return total_steps - self.azimuth_step_count

    def azimuth_steps(self) -> int:
        if self.direction == "HORIZONTAL":
            total_steps = self.azimuth_step_count * self.elevation_step_count
            return total_steps - self.elevation_step_count
        elif self.direction == "VERTICAL":
            return self.azimuth_step_count - 1

    def azimuth_step_time(self) -> float:
        return estimated_step_time(azimuth=self.azimuth_step_size(), elevation=0)

    def elevation_step_time(self) -> float:
        return estimated_step_time(azimuth=0, elevation=self.elevation_step_size())

    def total_azimuth_time(self) -> float:
        return self.azimuth_steps() * self.azimuth_step_time()

    def total_elevation_time(self) -> float:
        return self.elevation_steps() * self.elevation_step_time()

    def total_grid_time(self) -> float:
        return self.total_azimuth_time() + self.total_elevation_time()

    def cuts(self) -> list[list[AzEl]]:
        """Return a list of cuts, where each cut is a list of AzEl points.

        In a horizontal grid, each cut is a row.
        In a vertical grid, each cut is a column."""
        if self.direction == "HORIZONTAL":
            cuts = [
                self.points[i : i + self.azimuth_step_count]
                for i in range(0, len(self.points), self.azimuth_step_count)
            ]
        elif self.direction == "VERTICAL":
            cuts = [
                self.points[i : i + self.elevation_step_count]
                for i in range(0, len(self.points), self.elevation_step_count)
            ]
        else:
            raise ValueError(f"Invalid direction: {self.direction}")
        return cuts

    def plot(self, ax: "plt.Axes"):
        azimuths = [point.azimuth for point in self.points]
        elevations = [point.elevation for point in self.points]
        ax.plot(azimuths, elevations, label="Grid Pattern", marker="o", color="black")

        first_point = self.points[0]
        last_point = self.points[-1]

        for point_index, point in enumerate(self.points):
            ax.text(
                point.azimuth,
                point.elevation,
                f"{point_index}",
                # fontsize=8,
                # ha="center",
                # va="center",
            )

        if self.initial_position:
            ax.plot(
                [self.initial_position.azimuth, first_point.azimuth],
                [self.initial_position.elevation, first_point.elevation],
                # label="Start Position",
                # marker="o",
                linestyle="--",
                color="black",
            )
        ax.scatter(
            first_point.azimuth,
            first_point.elevation,
            label="First Point",
            marker="o",
            color="#00ff0088",
            zorder=10,
            s=300,
        )
        ax.scatter(
            last_point.azimuth,
            last_point.elevation,
            label="Last Point",
            marker="o",
            color="#ff000088",
            zorder=10,
            s=300,
        )
        ax.set_xlabel("Azimuth (degrees)")
        ax.set_ylabel("Elevation (degrees)")
        # ax.set_xlabel("Azimuth (degrees)")
        # ax.set_ylabel("Elevation (degrees)")
        # ax.grid(which="both")

    @classmethod
    def best_grid(
        cls,
        *,
        azimuth_min: float,
        azimuth_max: float,
        elevation_min: float,
        elevation_max: float,
        azimuth_step_count: int | None = None,
        azimuth_step_size: float | None = None,
        elevation_step_count: float | None = None,
        elevation_step_size: float | None = None,
        # start_corner: Literal["UL", "UR", "LL", "LR"] = "UL",
        initial_position: AzEl | None = None,
        # direction: Literal["HORIZONTAL", "VERTICAL"] = "HORIZONTAL"
    ) -> "GridPattern":
        """Return the best grid for the current setup."""
        best_time = float("inf")
        best_grid = None
        for start_corner in ["UL", "UR", "LL", "LR"]:
            for direction in ["HORIZONTAL", "VERTICAL"]:
                grid = cls(
                    azimuth_min=azimuth_min,
                    azimuth_max=azimuth_max,
                    elevation_min=elevation_min,
                    elevation_max=elevation_max,
                    azimuth_step_count=azimuth_step_count,
                    azimuth_step_size=azimuth_step_size,
                    elevation_step_count=elevation_step_count,
                    elevation_step_size=elevation_step_size,
                    start_corner=start_corner,
                    initial_position=initial_position,
                    direction=direction,
                )
                if grid.total_grid_time() < best_time:
                    best_time = grid.total_grid_time()
                    best_grid = grid
        return best_grid


if __name__ == "__main__":
    fine_grid = GridPattern(
        azimuth_min=-20,
        azimuth_max=20,
        elevation_min=-20,
        elevation_max=20,
        azimuth_step_size=0.25,
        elevation_step_size=0.25,
        start_corner="UL",
        # initial_position=AzEl(0, 0),
        # direction="VERTICAL",
        direction="HORIZONTAL",
    )
    coarse_grid = GridPattern(
        azimuth_min=-180,
        azimuth_max=180,
        elevation_min=-20,
        elevation_max=20,
        azimuth_step_size=1,
        elevation_step_size=2,
        start_corner="UL",
        # initial_position=AzEl(0, 0),
        # direction="VERTICAL",
        direction="HORIZONTAL",
    )
    small_grid = GridPattern(
        azimuth_min=-20,
        azimuth_max=20,
        elevation_min=-10,
        elevation_max=10,
        # azimuth_step_count=11,
        azimuth_step_size=5.0,
        elevation_step_count=7,
        start_corner="UL",
        # initial_position=AzEl(0, 0),
        # direction="VERTICAL",
        direction="HORIZONTAL",
    )
    grid = fine_grid
    # grid = coarse_grid
    # grid=small_grid
    print(grid.azimuth_values)
    print(grid.elevation_values)
    print(grid.points)
    print("Done")

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    # grid.plot(ax)
    print(f"{grid.height()=}")
    print(f"{grid.width()=}")
    print(f"{grid.elevation_step_size()=}")
    print(f"{grid.azimuth_step_size()=}")
    print(f"{grid.elevation_steps()=}")
    print(f"{grid.azimuth_steps()=}")
    print(f"{grid.azimuth_step_time()=}")
    print(f"{grid.elevation_step_time()=}")
    print(f"{grid.total_azimuth_time()=}")
    print(f"{grid.total_elevation_time()=}")
    print(f"{grid.total_grid_time()        = }")
    print(f"{grid.total_grid_time() / 60   = }")
    print(f"{grid.total_grid_time() / 3600 = }")
    print(f"{len(grid.cuts())=}")
    print(f"{len(grid.cuts()[0])=}")
    cut_time = grid.total_grid_time() / len(grid.cuts())
    print(f"{cut_time=}")
    exit()
    point_index = 0
    for cut_index, cut in enumerate(grid.cuts()):
        for within_cut_index, point in enumerate(cut):
            print(f"{cut_index=}, {within_cut_index=}, {within_cut_index=} {point=}")
            point_index += 1

    plt.show()

    # COARSE
    for step_size in [1, 2, 3, 5, 10]:
        grid = GridPattern.best_grid(
            azimuth_min=-180,
            azimuth_max=180,
            elevation_min=0,
            elevation_max=0,
            azimuth_step_size=step_size,
            elevation_step_size=step_size,
            # start_corner="UL",
            # direction="HORIZONTAL",
        )
        grid_minutes = grid.total_grid_time() / 60.0
        grid_cuts = len(grid.cuts())
        cut_size = len(grid.cuts()[0])
        cut_time_minutes = grid.total_grid_time() / grid_cuts / 60.0
        print(
            f"{step_size=:.2f}deg, {grid_minutes=:.2f} minutes, {grid_cuts=}, {cut_size=}, {cut_time_minutes=:.2f} minutes per cut"
        )
        # print(f"{step_size=:.2f}deg, {grid_minutes=:.2f} minutes, {grid_cuts=}, {cut_size=}, {cut_time=:.2f} seconds per cut")
        # print(f"{step_size=:.2f}deg, {grid.total_grid_time() / 3600.0=:.2f} hours")

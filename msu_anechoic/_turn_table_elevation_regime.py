"""
Scratchpad for the new turn table decades thing.
"""

import dataclasses
import functools


@functools.total_ordering
@dataclasses.dataclass
class TurnTableElevationRegime:
    """Represents a regime of elevation angles for the turn table.

    All angles in DEGREES, and ideally they will be integers."""

    center_angle: float
    allowable_offset: float
    waypoint_offset: float

    def is_in_allowable_range(self, angle: float) -> bool:
        """Check if an angle is within the allowable elevation range.

        This will be the center angle +/- the allowable offset, which is usually 29 degrees."""
        return abs(angle - self.center_angle) <= self.allowable_offset

    def __contains__(self, angle: float) -> bool:
        return self.is_in_allowable_range(angle)

    def get_allowable_range(self) -> tuple[float, float]:
        """Get the allowable range for this elevation regime."""
        return (
            self.center_angle - self.allowable_offset,
            self.center_angle + self.allowable_offset,
        )

    def get_waypoints(self) -> tuple[float, float]:
        """Get the waypoints for this elevation regime.

        Theses are the points where the turntable to will start/stop and reconfigure itself
        when entering/exiting a regime.

        NOTE: This will always give the lower waypoint first"""
        return (
            self.center_angle - self.waypoint_offset,
            self.center_angle + self.waypoint_offset,
        )

    def get_closest_waypoint(self, angle: float) -> float:
        """Get the closest waypoint to a given angle."""
        lower, upper = self.get_waypoints()
        return lower if abs(angle - lower) < abs(angle - upper) else upper

    def __lt__(self, other: "TurnTableElevationRegime") -> bool:
        if not isinstance(other, TurnTableElevationRegime):
            return NotImplemented
        return self.center_angle < other.center_angle

    def __eq__(self, other: "TurnTableElevationRegime") -> bool:
        if not isinstance(other, TurnTableElevationRegime):
            return NotImplemented
        return self.center_angle == other.center_angle
    
    def __str__(self) -> str:
        return f"{self.center_angle:+.0f}°±{self.allowable_offset:.0f}°"


elevation_regimes = tuple(
    TurnTableElevationRegime(
        center_angle=angle,
        allowable_offset=29,
        waypoint_offset=13,
    )
    for angle in [
        -75,
        -50,
        -25,
        0,
        25,
        50,
        75,
    ]
)
"""The valid elevation regimes for the turn table."""


def find_best_regime(angle: float) -> TurnTableElevationRegime:
    """Find the best elevation regime for a given angle."""
    best_fit = min(elevation_regimes, key=lambda regime: abs(angle - regime.center_angle))
    if angle in best_fit:
        return best_fit
    else:
        raise ValueError(f"Angle {angle} is not in any elevation regime.")


def find_next_regime(
    destination_angle: float,
    current_regime: TurnTableElevationRegime,
) -> TurnTableElevationRegime:
    """Find the next elevation regime to move to along the path to the destination angle.
    
    If the destination is in the current regime, the current regime is returned."""
    if destination_angle in current_regime:
        return current_regime
    
    # NOTE: This assumes that the regimes are sorted in ascending order (which they are)
    # This could be written more robustly.
    current_regime_index = elevation_regimes.index(current_regime)
    if destination_angle > current_regime.center_angle:
        return elevation_regimes[current_regime_index + 1]
    else:
        return elevation_regimes[current_regime_index - 1]


if __name__ == "__main__":
    import matplotlib.pyplot as plt
    import numpy as np
    from rich.pretty import pprint

    fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
    colors = [
        "#880000",
        "#008800",
        "#000088",
        "#888800",
        "#880088",
        "#008888",
        "#888888",
    ]
    # for regime in elevation_regimes.values():
    #     lower, upper = regime.get_allowable_range()
    #     waypoints = regime.get_waypoints()

    #     # Plot allowable range
    #     ax.plot([np.deg2rad(lower), np.deg2rad(upper)], [1, 1], label=f"Regime {regime.center_angle}°")

    #     # Plot waypoints
    #     ax.plot(np.deg2rad(waypoints[0]), 1, 'ro')  # Lower waypoint
    #     ax.plot(np.deg2rad(waypoints[1]), 1, 'go')  # Upper waypoint

    # ax.set_rmax(1.5)
    # ax.set_rticks([])  # Remove radial ticks
    # ax.set_theta_zero_location('N')
    # ax.set_theta_direction(-1)
    # ax.legend(loc='upper right')
    # plt.show()
    np.random.seed(40351)
    radius = 1
    for regime_index, regime in enumerate(elevation_regimes):
        color = colors[regime_index % len(colors)]
        lower_limit, upper_limit = regime.get_allowable_range()
        lower_waypoint, upper_waypoint = regime.get_waypoints()

        # Plot shaded circle segment
        theta = np.linspace(np.radians(lower_limit), np.radians(upper_limit), 100)
        radius += 0.1
        # r = np.ones_like(theta)
        r = [radius] * len(theta)
        # r *= np.random.uniform(0.5, 1.5)
        ax.fill_between(theta, 0, r, color=color, alpha=0.3)
        radius = r[0]
        # Plot waypoints
        # Plot waypoints with lines from the origin
        # ax.plot(
        #     [0, np.radians(lower_waypoint)],
        #     [0, radius],
        #     color=color,
        #     linestyle="--",
        # )
        # ax.plot(
        #     [0, np.radians(upper_waypoint)],
        #     [0, radius],
        #     color=color,
        #     linestyle="--",
        # )
        # plot center as a line
        ax.plot(
            [0, np.radians(regime.center_angle)],
            [0, 2],
            color="black",
            linestyle="--",
        )
        # Plot waypoints as markers
        # ax.plot(
        #     [np.radians(lower_waypoint), np.radians(upper_waypoint)],
        #     [radius, radius],
        #     color=color,
        #     marker="o",
        #     linestyle="",
        # )
        ax.text(
            np.radians(regime.center_angle),
            radius * 0.7,
            # f"[{regime_index}]",
            str(regime),
            color="black",
            ha="center",
            va="center",
        )

        # # Plot allowable range
        # ax.plot(
        #     [0, np.radians(lower_limit), np.radians(upper_limit), 0],
        #     [0, 1, 1, 0],
        #     color=color,
        # )

        # # Plot center
        # ax.plot(
        #     [0, np.radians(regime.center_angle)],
        #     [0, 1],
        #     color=color,
        # )
        print(f"{regime_index=}")
        pprint(regime)
        print(f"{regime.is_in_allowable_range(0)=}")
        print(f"{regime.get_closest_waypoint(0)=}")
        print(f"{regime.get_waypoints()=}")
        print(f"{regime.get_waypoints()=}")

        # pprint(regime.get_waypoints())
        # pprint(regime.get_closest_waypoint(0))
        # pprint(regime.get_closest_waypoint(10))
        # pprint(regime.get_closest_waypoint(-10))
        # pprint(regime.get_closest_waypoint(-30))
        # pprint(regime.get_closest_waypoint(-50))
        # pprint(regime.get_closest_waypoint(-70))
        print()

    # Limit theta to -90 to 90
    ax.set_thetamin(-180)
    ax.set_thetamax(180)
    ax.set_yticklabels([])  # Remove radial scale labels
    ax.set_xticks(np.radians(np.arange(-180, 181, 15)))
    ax.set_xticks(np.radians(np.arange(-180, 181, 90)))
    plt.show()

    start_angle = -90
    destination_angle = -50

    current_regime = find_best_regime(start_angle)
    print(f"START {current_regime=!s}")
    next_regime = find_next_regime(destination_angle, current_regime)
    while current_regime != next_regime:
        print(f"{current_regime=!s} -> {next_regime=!s}")
        current_regime = next_regime
        next_regime = find_next_regime(destination_angle, current_regime)
    print(f"FINAL {current_regime=!s}")
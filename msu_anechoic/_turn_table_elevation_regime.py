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
    )
    for angle in [
        -81,
        -54,
        -27,
        0,
        27,
        54,
        81,
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
        "#ff0000",
        "#00ff00",
        "#0000ff",
        "#ffff00",
        "#ff00ff",
        "#00ffff",
        # "#ffffff",
    ]
    np.random.seed(40351)
    radius = 1
    for regime_index, regime in enumerate(elevation_regimes):
        color = colors[regime_index % len(colors)]
        lower_limit, upper_limit = regime.get_allowable_range()

        # Plot shaded circle segment
        theta = np.linspace(np.radians(lower_limit), np.radians(upper_limit), 100)
        radius += 0.1
        r = [radius] * len(theta)
        ax.fill_between(theta, 0, r, color=color, alpha=0.3)
        radius = r[0]
        ax.plot(
            [0, np.radians(regime.center_angle)],
            [0, 2],
            color="black",
            linestyle="--",
        )
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

        print()

    # Limit theta to -90 to 90
    ax.set_thetamin(-180)
    ax.set_thetamax(180)
    ax.set_yticklabels([])  # Remove radial scale labels
    # ax.set_xticks(np.radians(np.arange(-180, 181, 15)))
    ax.set_xticks(np.radians(np.arange(-180, 180, 90)))
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

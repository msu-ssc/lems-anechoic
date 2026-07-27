"""Tilt regimes for safely spanning the turntable's physical range."""

from __future__ import annotations

import dataclasses
import functools


@functools.total_ordering
@dataclasses.dataclass(frozen=True)
class TiltRegime:
    """A physical tilt range represented by relative firmware pitch values."""

    center_tilt: float
    allowable_offset: float

    def __contains__(self, tilt: float) -> bool:
        return abs(tilt - self.center_tilt) <= self.allowable_offset

    @property
    def minimum_tilt(self) -> float:
        return self.center_tilt - self.allowable_offset

    @property
    def maximum_tilt(self) -> float:
        return self.center_tilt + self.allowable_offset

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, TiltRegime):
            return NotImplemented
        return self.center_tilt < other.center_tilt

    def __str__(self) -> str:
        return f"{self.center_tilt:+.0f}°±{self.allowable_offset:.0f}°"


TILT_REGIMES = tuple(
    TiltRegime(center_tilt=tilt, allowable_offset=29.0)
    for tilt in (
        -81.0,
        -54.0,
        -27.0,
        0.0,
        27.0,
        54.0,
        81.0,
    )
)


def find_best_regime(tilt: float) -> TiltRegime:
    regime = min(TILT_REGIMES, key=lambda candidate: abs(tilt - candidate.center_tilt))
    if tilt in regime:
        return regime
    raise ValueError(f"Tilt {tilt} is not in any turntable regime")


def find_next_regime(*, destination_tilt: float, current_regime: TiltRegime) -> TiltRegime:
    if destination_tilt in current_regime:
        return current_regime

    current_index = TILT_REGIMES.index(current_regime)
    if destination_tilt > current_regime.center_tilt:
        return TILT_REGIMES[current_index + 1]
    return TILT_REGIMES[current_index - 1]

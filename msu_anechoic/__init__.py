from __future__ import annotations

from typing import NamedTuple

import numpy as np


class AzEl(NamedTuple):
    """Azimuth and elevation in degrees."""

    azimuth: float
    elevation: float

    @property
    def azimuth_degrees(self) -> float:
        """Return the azimuth in degrees."""
        return self.azimuth

    @property
    def elevation_degrees(self) -> float:
        """Return the elevation in degrees."""
        return self.elevation

    @property
    def azimuth_radians(self) -> float:
        """Return the azimuth in radians."""
        return np.radians(self.azimuth)

    @property
    def elevation_radians(self) -> float:
        """Return the elevation in radians."""
        return np.radians(self.elevation)


def create_null_logger() -> "logging.Logger":  # type: ignore # noqa: F821
    """Create a null logger."""
    import logging

    logger = logging.getLogger("null")
    logger.addHandler(logging.NullHandler())
    return logger

from __future__ import annotations

from typing import TYPE_CHECKING

from msu_anechoic.util.azel import AzEl
from msu_anechoic.util.azel import AzElSpherical
from msu_anechoic.util.azel import AzElTurntable
from msu_anechoic.util.coordinate import Coordinate

if TYPE_CHECKING:
    import logging


def create_null_logger() -> "logging.Logger":  # type: ignore # noqa: F821
    """Create a null logger."""
    import logging

    logger = logging.getLogger("null")
    logger.addHandler(logging.NullHandler())
    return logger

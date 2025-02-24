from msu_anechoic.util.azel import AzEl
from msu_anechoic.util.azel import AzElSpherical
from msu_anechoic.util.azel import AzElTurntable


def create_null_logger() -> "logging.Logger":  # type: ignore # noqa: F821
    """Create a null logger."""
    import logging

    logger = logging.getLogger("null")
    logger.addHandler(logging.NullHandler())
    return logger

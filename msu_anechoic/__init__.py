from __future__ import annotations


def _create_null_logger() -> "logging.Logger":  # type: ignore # noqa: F821
    """Create a null logger."""
    import logging

    logger = logging.getLogger("null")
    logger.addHandler(logging.NullHandler())
    return logger

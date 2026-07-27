"""Messages received from the turntable."""

from __future__ import annotations

import datetime
import re
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

_POSITION_PATTERN = re.compile(rb"Pos= El: (?P<elevation>-?\d{1,3}\.\d{2}) , Az: (?P<azimuth>-?\d{1,3}\.\d{2})")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)


class ReceivedMessage(BaseModel):
    """An immutable line received from the turntable."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["position", "other"] = "other"
    message: bytes
    timestamp: datetime.datetime = Field(default_factory=_utc_now)


class ReceivedMessagePosition(ReceivedMessage):
    """A received position report.

    ``azimuth`` and ``elevation`` are ``None`` only when a caller constructs an
    event manually. The serial parser only creates position events after both
    values have been parsed successfully.
    """

    kind: Literal["position"] = "position"
    azimuth: float | None = None
    elevation: float | None = None


def parse_received_message(
    message: bytes,
    *,
    timestamp: datetime.datetime | None = None,
) -> ReceivedMessage:
    """Parse one wire message into the smallest useful event."""

    timestamp = timestamp or _utc_now()
    match = _POSITION_PATTERN.search(message)
    if match is None:
        return ReceivedMessage(message=message, timestamp=timestamp)

    try:
        azimuth = float(match.group("azimuth"))
        elevation = float(match.group("elevation"))
    except (TypeError, ValueError):
        return ReceivedMessage(message=message, timestamp=timestamp)

    return ReceivedMessagePosition(
        message=message,
        timestamp=timestamp,
        azimuth=azimuth,
        elevation=elevation,
    )

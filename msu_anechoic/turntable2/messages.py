"""Messages received from the turntable."""

from __future__ import annotations

import datetime
import re
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

_POSITION_PATTERN = re.compile(rb"Pos= El: (?P<pitch>-?\d{1,3}\.\d{2}) , Az: (?P<yaw>-?\d{1,3}\.\d{2})")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)


class ReceivedMessage(BaseModel):
    """An immutable line received from the turntable."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["position", "other"] = "other"
    message: bytes
    timestamp: datetime.datetime = Field(default_factory=_utc_now)


class ReceivedMessagePosition(ReceivedMessage):
    """A raw position report containing the firmware's relative coordinates.

    The firmware labels these values ``Az`` and ``El`` on the wire. Within
    ``turntable2`` they are called yaw and pitch to distinguish them from the
    regime-compensated physical pan and tilt.
    """

    kind: Literal["position"] = "position"
    yaw: float | None = None
    pitch: float | None = None


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
        yaw = float(match.group("yaw"))
        pitch = float(match.group("pitch"))
    except (TypeError, ValueError):
        return ReceivedMessage(message=message, timestamp=timestamp)

    return ReceivedMessagePosition(
        message=message,
        timestamp=timestamp,
        yaw=yaw,
        pitch=pitch,
    )

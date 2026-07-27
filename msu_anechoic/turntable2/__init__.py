"""Threaded turntable controller.

Typical use::

    from msu_anechoic import turntable2

    with turntable2.find() as turntable:
        turntable.set_position(azimuth=0, elevation=0)
        turntable.move_to(azimuth=30, elevation=10)
"""

from msu_anechoic.turntable2.controller import ALLOWABLE_DISCREPANCY_DEG
from msu_anechoic.turntable2.controller import ControllerThread
from msu_anechoic.turntable2.controller import TurntableError
from msu_anechoic.turntable2.controller import TurntableState
from msu_anechoic.turntable2.messages import ReceivedMessage
from msu_anechoic.turntable2.messages import ReceivedMessagePosition
from msu_anechoic.turntable2.messages import parse_received_message
from msu_anechoic.turntable2.serial_listener import SerialListener
from msu_anechoic.turntable2.turntable import Turntable
from msu_anechoic.turntable2.turntable import find

__all__ = [
    "ALLOWABLE_DISCREPANCY_DEG",
    "ControllerThread",
    "ReceivedMessage",
    "ReceivedMessagePosition",
    "SerialListener",
    "Turntable",
    "TurntableError",
    "TurntableState",
    "find",
    "parse_received_message",
]

"""Public turntable interface."""

from __future__ import annotations

import logging
import queue
import time
from typing import Literal
from typing import overload

import serial

from msu_anechoic import create_null_logger
from msu_anechoic.turntable2.controller import ControllerThread
from msu_anechoic.turntable2.controller import PositionSample
from msu_anechoic.turntable2.controller import TurntableCompleteState
from msu_anechoic.turntable2.controller import TurntableError
from msu_anechoic.turntable2.controller import TurntableState
from msu_anechoic.turntable2.messages import ReceivedMessage
from msu_anechoic.turntable2.messages import ReceivedMessagePosition
from msu_anechoic.turntable2.positions import PanTilt
from msu_anechoic.turntable2.serial_listener import SerialConnection
from msu_anechoic.turntable2.serial_listener import SerialListener


class Turntable:
    """A thread-safe, non-blocking interface to the two-axis turntable.

    Public commands are placed on a controller queue. The controller thread
    sends them in order while a separate listener thread continuously receives
    position reports.
    """

    def __init__(
        self,
        *,
        port: str | None = None,
        baudrate: int = 9_600,
        timeout: float = 0.1,
        communication_timeout: float = 1.0,
        command_repetitions: int = 3,
        event_history_size: int = 1_000,
        poll_interval: float = 0.01,
        logger: logging.Logger | None = None,
        serial_connection: SerialConnection | None = None,
    ) -> None:
        if serial_connection is None and port is None:
            raise ValueError("port is required when serial_connection is not provided")
        if serial_connection is not None and port is not None:
            raise ValueError("Provide either port or serial_connection, not both")

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.logger = logger or create_null_logger()
        self._closed = False

        if serial_connection is None:
            serial_connection = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        self._serial = serial_connection

        received_messages: "queue.Queue[ReceivedMessage]" = queue.Queue()
        self._listener = SerialListener(
            serial_connection=self._serial,
            output_queue=received_messages,
            poll_interval=poll_interval,
            logger=self.logger.getChild("listener"),
        )
        self._controller = ControllerThread(
            serial_connection=self._serial,
            received_messages=received_messages,
            communication_timeout=communication_timeout,
            command_repetitions=command_repetitions,
            event_history_size=event_history_size,
            poll_interval=poll_interval,
            logger=self.logger.getChild("controller"),
        )
        self._listener.start()
        self._controller.start()

    @classmethod
    def find(
        cls,
        *,
        baudrate: int = 9_600,
        timeout: float = 0.1,
        communication_timeout: float = 1.0,
        discovery_timeout: float = 2.0,
        command_repetitions: int = 3,
        event_history_size: int = 1_000,
        poll_interval: float = 0.01,
        logger: logging.Logger | None = None,
    ) -> "Turntable":
        """Find the first serial port that emits a valid position report."""

        if discovery_timeout <= 0:
            raise ValueError("discovery_timeout must be greater than zero")

        from serial.tools.list_ports import comports

        logger = logger or create_null_logger()
        for port_info in comports():
            turntable: Turntable | None = None
            try:
                logger.debug("Trying turntable serial port %s", port_info.device)
                turntable = cls(
                    port=port_info.device,
                    baudrate=baudrate,
                    timeout=timeout,
                    communication_timeout=communication_timeout,
                    command_repetitions=command_repetitions,
                    event_history_size=event_history_size,
                    poll_interval=poll_interval,
                    logger=logger,
                )
                deadline = time.monotonic() + discovery_timeout
                while time.monotonic() < deadline:
                    if turntable.most_recent_event(kind="position") is not None:
                        logger.info("Found turntable on serial port %s", port_info.device)
                        return turntable
                    time.sleep(poll_interval)
            except Exception:
                logger.debug("Serial port %s is not the turntable", port_info.device, exc_info=True)
            if turntable is not None:
                turntable.close()

        raise TurntableError("Failed to find the turntable on any serial port")

    def set_position(
        self,
        *,
        pan: float,
        tilt: float,
        timeout: float = 5.0,
    ) -> None:
        """Queue a SET command.

        The firmware ignores values other than zero, so this method rejects
        them instead of providing a false impression that they were applied.
        """

        self._controller.submit_set(pan=pan, tilt=tilt, timeout=timeout)

    def move_to(
        self,
        *,
        pan: float,
        tilt: float,
        move_timeout: float = 120.0,
    ) -> None:
        """Queue a safe move and return immediately."""

        self._controller.submit_move(pan=pan, tilt=tilt, timeout=move_timeout)

    def abort(self) -> None:
        """Immediately stop movement and invalidate all queued commands."""

        self._controller.submit_abort()

    def current_state(self) -> TurntableState:
        return self._controller.current_state()

    def current_position(self) -> PanTilt | None:
        """Return the most recently reported, regime-compensated position."""

        return self._controller.current_position()

    def get_complete_state(self) -> TurntableCompleteState:
        """Return a detailed, immutable diagnostic snapshot."""

        return self._controller.get_complete_state()

    @overload
    def most_recent_event(self, *, kind: Literal["position"]) -> ReceivedMessagePosition | None: ...

    @overload
    def most_recent_event(self, *, kind: Literal["other"]) -> ReceivedMessage | None: ...

    @overload
    def most_recent_event(self, *, kind: None = None) -> ReceivedMessage | None: ...

    def most_recent_event(self, *, kind: str | None = None) -> ReceivedMessage | None:
        """Return the newest raw receive event, optionally filtered by kind."""

        return self._controller.most_recent_event(kind=kind)

    def events(self) -> tuple[ReceivedMessage, ...]:
        """Return a snapshot of the bounded receive-event history."""

        return self._controller.events()

    def position_history(self) -> tuple[PositionSample, ...]:
        """Return timestamped raw and corrected position samples."""

        return self._controller.position_history()

    def time_since_last_communication(self) -> float:
        return self._controller.time_since_last_communication()

    def last_error(self) -> Exception | None:
        """Return the most recent asynchronous controller error, if any."""

        return self._controller.last_error()

    def close(self, *, join_timeout: float = 2.0) -> None:
        """Stop both threads and close the serial connection."""

        if self._closed:
            return
        self._closed = True
        self._listener.stop()
        self._controller.stop()
        self._listener.join(timeout=join_timeout)
        self._controller.join(timeout=join_timeout)
        self._serial.close()

    def __enter__(self) -> "Turntable":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


find = Turntable.find

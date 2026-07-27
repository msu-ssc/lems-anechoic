"""The low-level serial receive thread."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Protocol

from msu_anechoic.turntable2.messages import ReceivedMessage
from msu_anechoic.turntable2.messages import parse_received_message


class SerialConnection(Protocol):
    """The subset of :mod:`pyserial` used by the controller."""

    @property
    def in_waiting(self) -> int: ...

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


class SerialListener(threading.Thread):
    """Read and frame serial data without interpreting controller state."""

    def __init__(
        self,
        serial_connection: SerialConnection,
        output_queue: "queue.Queue[ReceivedMessage]",
        *,
        poll_interval: float = 0.01,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(name="turntable-serial-listener", daemon=True)
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than zero")
        self._serial = serial_connection
        self._output_queue = output_queue
        self._poll_interval = poll_interval
        self._logger = logger or logging.getLogger(__name__)
        self._stop_event = threading.Event()
        self._buffer = bytearray()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                waiting = self._serial.in_waiting
                if waiting <= 0:
                    self._stop_event.wait(self._poll_interval)
                    continue
                data = self._serial.read(waiting)
            except Exception:
                self._logger.exception("Failed to read from the turntable serial connection")
                self._stop_event.wait(self._poll_interval)
                continue

            if not data:
                self._stop_event.wait(self._poll_interval)
                continue

            self._buffer.extend(data)
            self._emit_complete_lines()

            # Do not retain corrupt, unterminated input forever.
            if len(self._buffer) > 65_536:
                message = bytes(self._buffer)
                self._buffer.clear()
                self._output_queue.put(parse_received_message(message))

        if self._buffer:
            self._output_queue.put(parse_received_message(bytes(self._buffer)))
            self._buffer.clear()

    def _emit_complete_lines(self) -> None:
        while True:
            newline_index = self._buffer.find(b"\n")
            if newline_index < 0:
                return
            end = newline_index + 1
            message = bytes(self._buffer[:end])
            del self._buffer[:end]
            self._output_queue.put(parse_received_message(message))

"""Stateful, non-blocking turntable controller."""

from __future__ import annotations

import dataclasses
import enum
import logging
import math
import queue
import threading
import time
from collections import deque
from typing import Literal
from typing import overload

from msu_anechoic import AzEl
from msu_anechoic import _turn_table_elevation_regime as _regime
from msu_anechoic.turntable2.messages import ReceivedMessage
from msu_anechoic.turntable2.messages import ReceivedMessagePosition
from msu_anechoic.turntable2.serial_listener import SerialConnection

ALLOWABLE_DISCREPANCY_DEG = 0.11
ABSOLUTE_AZIMUTH_BOUNDS = (-180.0, 180.0)
ABSOLUTE_ELEVATION_BOUNDS = (-90.0, 45.0)
REGIME_ELEVATION_BOUNDS = (-29.5, 29.5)


class TurntableError(Exception):
    """Base exception for the asynchronous turntable controller."""


class TurntableState(str, enum.Enum):
    """Observable controller states."""

    NOT_SET = "not_set"
    STOPPED = "stopped"
    MOVING = "moving"
    NO_COMMUNICATION = "no_communication"
    TIMED_OUT = "timed_out"
    ERROR = "error"
    CLOSED = "closed"


@dataclasses.dataclass(frozen=True)
class _SetCommand:
    azimuth: float
    elevation: float
    timeout: float


@dataclasses.dataclass(frozen=True)
class _MoveCommand:
    azimuth: float
    elevation: float
    timeout: float


@dataclasses.dataclass(frozen=True)
class _AbortCommand:
    pass


@dataclasses.dataclass(frozen=True)
class _CloseCommand:
    pass


_Command = _SetCommand | _MoveCommand | _AbortCommand | _CloseCommand


@dataclasses.dataclass
class _SetOperation:
    deadline: float


@dataclasses.dataclass
class _MoveOperation:
    azimuth: float
    elevation: float
    deadline: float
    phase: Literal["starting", "regime_move", "regime_set", "final"] = "starting"
    raw_target: AzEl | None = None
    next_regime: _regime.TurnTableElevationRegime | None = None
    next_offset: float | None = None


_Operation = _SetOperation | _MoveOperation


class ControllerThread(threading.Thread):
    """Consume receive events and commands, and own all serial writes."""

    def __init__(
        self,
        serial_connection: SerialConnection,
        received_messages: "queue.Queue[ReceivedMessage]",
        *,
        communication_timeout: float = 1.0,
        command_repetitions: int = 3,
        event_history_size: int = 1_000,
        poll_interval: float = 0.01,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(name="turntable-controller", daemon=True)
        if communication_timeout <= 0:
            raise ValueError("communication_timeout must be greater than zero")
        if command_repetitions < 1:
            raise ValueError("command_repetitions must be at least one")
        if event_history_size < 1:
            raise ValueError("event_history_size must be at least one")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than zero")

        self._serial = serial_connection
        self._received_messages = received_messages
        self._communication_timeout = communication_timeout
        self._command_repetitions = command_repetitions
        self._poll_interval = poll_interval
        self._logger = logger or logging.getLogger(__name__)

        self._command_queue: "queue.Queue[_Command]" = queue.Queue()
        self._queued_commands: "deque[_SetCommand | _MoveCommand]" = deque()
        self._operation: _Operation | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

        self._state = TurntableState.NOT_SET
        self._has_been_set = False
        self._set_requested = False
        self._current_regime: _regime.TurnTableElevationRegime | None = None
        self._regime_elevation_offset: float | None = None
        self._raw_position: AzEl | None = None
        self._current_position: AzEl | None = None
        self._most_recent_communication = float("-inf")
        self._started_at = time.monotonic()
        self._events: "deque[ReceivedMessage]" = deque(maxlen=event_history_size)
        self._most_recent_by_kind: dict[str, ReceivedMessage] = {}
        self._last_error: Exception | None = None

    def submit_set(self, *, azimuth: float, elevation: float, timeout: float) -> None:
        if azimuth != 0 or elevation != 0:
            raise ValueError("The turntable firmware only supports setting azimuth=0 and elevation=0")
        _validate_timeout(timeout)
        with self._lock:
            self._ensure_open()
            self._set_requested = True
            self._command_queue.put(_SetCommand(azimuth=azimuth, elevation=elevation, timeout=timeout))

    def submit_move(self, *, azimuth: float, elevation: float, timeout: float) -> None:
        _validate_position(azimuth=azimuth, elevation=elevation)
        _validate_timeout(timeout)
        with self._lock:
            self._ensure_open()
            if not (self._has_been_set or self._set_requested):
                raise TurntableError("The turntable position must be set before it can move")
            self._command_queue.put(_MoveCommand(azimuth=azimuth, elevation=elevation, timeout=timeout))

    def submit_abort(self) -> None:
        with self._lock:
            self._ensure_open()
            self._command_queue.put(_AbortCommand())

    def stop(self) -> None:
        self._command_queue.put(_CloseCommand())

    def current_state(self) -> TurntableState:
        with self._lock:
            return self._state

    def current_position(self) -> AzEl | None:
        with self._lock:
            return self._current_position

    @overload
    def most_recent_event(self, *, kind: Literal["position"]) -> ReceivedMessagePosition | None: ...

    @overload
    def most_recent_event(self, *, kind: Literal["other"]) -> ReceivedMessage | None: ...

    @overload
    def most_recent_event(self, *, kind: None = None) -> ReceivedMessage | None: ...

    def most_recent_event(self, *, kind: str | None = None) -> ReceivedMessage | None:
        with self._lock:
            if kind is None:
                return self._events[-1] if self._events else None
            if kind not in {"position", "other"}:
                raise ValueError(f"Unknown event kind: {kind!r}")
            return self._most_recent_by_kind.get(kind)

    def events(self) -> tuple[ReceivedMessage, ...]:
        with self._lock:
            return tuple(self._events)

    def last_error(self) -> Exception | None:
        with self._lock:
            return self._last_error

    def time_since_last_communication(self) -> float:
        with self._lock:
            return time.monotonic() - self._most_recent_communication

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._drain_commands()
                if self._stop_event.is_set():
                    break
                self._drain_messages()
                self._check_timeouts()
                self._start_next_command()
            except Exception as exc:
                self._logger.exception("Unexpected turntable controller error")
                with self._lock:
                    self._last_error = exc
                    self._operation = None
                    self._queued_commands.clear()
                    self._set_requested = self._has_been_set
                    self._state = TurntableState.ERROR
            self._stop_event.wait(self._poll_interval)

        with self._lock:
            self._state = TurntableState.CLOSED

    def _drain_commands(self) -> None:
        while True:
            try:
                command = self._command_queue.get_nowait()
            except queue.Empty:
                return

            if isinstance(command, _CloseCommand):
                self._stop_event.set()
                return
            if isinstance(command, _AbortCommand):
                self._abort()
                continue
            self._queued_commands.append(command)

    def _drain_messages(self) -> None:
        while True:
            try:
                event = self._received_messages.get_nowait()
            except queue.Empty:
                return
            self._handle_received_message(event)

    def _handle_received_message(self, event: ReceivedMessage) -> None:
        if not isinstance(event, ReceivedMessagePosition):
            self._record_event(event)
            return
        if event.azimuth is None or event.elevation is None:
            self._record_event(event)
            return

        raw_position = AzEl(azimuth=event.azimuth, elevation=event.elevation)
        with self._lock:
            self._most_recent_communication = time.monotonic()
            self._raw_position = raw_position
            offset = self._regime_elevation_offset or 0.0
            actual_position = AzEl(
                azimuth=raw_position.azimuth,
                elevation=raw_position.elevation + offset,
            )
            self._current_position = actual_position

        actual_event = ReceivedMessagePosition(
            message=event.message,
            timestamp=event.timestamp,
            azimuth=actual_position.azimuth,
            elevation=actual_position.elevation,
        )
        self._record_event(actual_event)

        if isinstance(self._operation, _SetOperation):
            if _position_matches(raw_position, AzEl(0.0, 0.0)):
                with self._lock:
                    self._has_been_set = True
                    self._set_requested = any(isinstance(command, _SetCommand) for command in self._queued_commands)
                    self._current_regime = _regime.find_best_regime(0.0)
                    self._regime_elevation_offset = 0.0
                    self._current_position = raw_position
                    self._operation = None
                    self._state = TurntableState.STOPPED
            return

        if not isinstance(self._operation, _MoveOperation):
            with self._lock:
                self._state = TurntableState.STOPPED if self._has_been_set else TurntableState.NOT_SET
            return

        operation = self._operation
        if operation.raw_target is None or not _position_matches(raw_position, operation.raw_target):
            return

        if operation.phase == "regime_move":
            assert operation.next_regime is not None
            operation.next_offset = raw_position.elevation + (self._regime_elevation_offset or 0.0)
            operation.phase = "regime_set"
            operation.raw_target = AzEl(0.0, 0.0)
            self._write_command(_format_set_command(azimuth=0.0, elevation=0.0))
            return

        if operation.phase == "regime_set":
            assert operation.next_regime is not None
            assert operation.next_offset is not None
            with self._lock:
                self._regime_elevation_offset = operation.next_offset
                self._current_regime = operation.next_regime
                self._current_position = AzEl(
                    azimuth=raw_position.azimuth,
                    elevation=raw_position.elevation + operation.next_offset,
                )
            self._continue_move(operation)
            return

        if operation.phase == "final":
            with self._lock:
                self._operation = None
                self._state = TurntableState.STOPPED
            return

    def _record_event(self, event: ReceivedMessage) -> None:
        with self._lock:
            self._events.append(event)
            self._most_recent_by_kind[event.kind] = event

    def _check_timeouts(self) -> None:
        now = time.monotonic()
        with self._lock:
            last_communication = self._most_recent_communication
            operation = self._operation

        reference = last_communication if math.isfinite(last_communication) else self._started_at
        if now - reference > self._communication_timeout:
            with self._lock:
                already_disconnected = self._state == TurntableState.NO_COMMUNICATION
            if not already_disconnected:
                if isinstance(operation, _MoveOperation):
                    self._write_command(b"p", repetitions=1)
                with self._lock:
                    self._state = TurntableState.NO_COMMUNICATION
                    self._has_been_set = False
                    self._set_requested = False
                    self._current_regime = None
                    self._regime_elevation_offset = None
                    self._operation = None
                    self._queued_commands.clear()
            return

        if operation is not None and now > operation.deadline:
            self._write_command(b"p", repetitions=1)
            error = TimeoutError("Turntable command timed out")
            with self._lock:
                self._last_error = error
                self._operation = None
                self._queued_commands.clear()
                self._set_requested = self._has_been_set
                self._state = TurntableState.TIMED_OUT

    def _start_next_command(self) -> None:
        with self._lock:
            if (
                self._operation is not None
                or not self._queued_commands
                or self._state == TurntableState.NO_COMMUNICATION
            ):
                return
            command = self._queued_commands.popleft()

        if isinstance(command, _SetCommand):
            self._begin_set(command)
        else:
            self._begin_move(command)

    def _begin_set(self, command: _SetCommand) -> None:
        with self._lock:
            self._operation = _SetOperation(deadline=time.monotonic() + command.timeout)
            self._state = TurntableState.NOT_SET
        self._write_command(_format_set_command(azimuth=command.azimuth, elevation=command.elevation))

    def _begin_move(self, command: _MoveCommand) -> None:
        with self._lock:
            if not self._has_been_set or self._current_regime is None or self._regime_elevation_offset is None:
                self._last_error = TurntableError("The turntable position is not set")
                self._state = TurntableState.ERROR
                self._set_requested = False
                return
            operation = _MoveOperation(
                azimuth=command.azimuth,
                elevation=command.elevation,
                deadline=time.monotonic() + command.timeout,
            )
            self._operation = operation
            self._state = TurntableState.MOVING
        self._continue_move(operation)

    def _continue_move(self, operation: _MoveOperation) -> None:
        with self._lock:
            current_regime = self._current_regime
            offset = self._regime_elevation_offset
        assert current_regime is not None
        assert offset is not None

        if operation.elevation not in current_regime:
            next_regime = _regime.find_next_regime(
                destination_angle=operation.elevation,
                current_regime=current_regime,
            )
            raw_elevation = next_regime.center_angle - offset
            _validate_regime_elevation(raw_elevation)
            operation.phase = "regime_move"
            operation.next_regime = next_regime
            operation.raw_target = AzEl(azimuth=0.0, elevation=raw_elevation)
            self._write_command(_format_move_command(azimuth=0.0, elevation=raw_elevation))
            return

        raw_elevation = operation.elevation - offset
        _validate_regime_elevation(raw_elevation)
        operation.phase = "final"
        operation.raw_target = AzEl(azimuth=operation.azimuth, elevation=raw_elevation)
        self._write_command(_format_move_command(azimuth=operation.azimuth, elevation=raw_elevation))

    def _abort(self) -> None:
        self._write_command(b"p", repetitions=1)
        with self._lock:
            self._operation = None
            self._queued_commands.clear()
            self._set_requested = self._has_been_set
            self._state = TurntableState.STOPPED if self._has_been_set else TurntableState.NOT_SET

    def _write_command(self, command: bytes, *, repetitions: int | None = None) -> None:
        repetitions = repetitions if repetitions is not None else self._command_repetitions
        try:
            for _ in range(repetitions):
                self._serial.write(command)
        except Exception as exc:
            self._logger.exception("Failed to write command to the turntable")
            with self._lock:
                self._last_error = exc
                self._operation = None
                self._state = TurntableState.ERROR

    def _ensure_open(self) -> None:
        if self._state == TurntableState.CLOSED or self._stop_event.is_set():
            raise TurntableError("The turntable controller is closed")


def _validate_timeout(timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite number greater than zero")


def _validate_position(*, azimuth: float, elevation: float) -> None:
    if not math.isfinite(azimuth) or not ABSOLUTE_AZIMUTH_BOUNDS[0] <= azimuth <= ABSOLUTE_AZIMUTH_BOUNDS[1]:
        raise ValueError(f"azimuth must be within {ABSOLUTE_AZIMUTH_BOUNDS}")
    if not math.isfinite(elevation) or not ABSOLUTE_ELEVATION_BOUNDS[0] <= elevation <= ABSOLUTE_ELEVATION_BOUNDS[1]:
        raise ValueError(f"elevation must be within {ABSOLUTE_ELEVATION_BOUNDS}")


def _validate_regime_elevation(elevation: float) -> None:
    if not REGIME_ELEVATION_BOUNDS[0] <= elevation <= REGIME_ELEVATION_BOUNDS[1]:
        raise TurntableError(
            f"Internal elevation {elevation} is outside the safe regime bounds {REGIME_ELEVATION_BOUNDS}"
        )


def _position_matches(actual: AzEl, expected: AzEl) -> bool:
    return (
        abs(actual.azimuth - expected.azimuth) <= ALLOWABLE_DISCREPANCY_DEG
        and abs(actual.elevation - expected.elevation) <= ALLOWABLE_DISCREPANCY_DEG
    )


def _format_set_command(*, azimuth: float, elevation: float) -> bytes:
    return f"CMD:SET:{azimuth:.3f},{elevation:.3f};".encode("ascii")


def _format_move_command(*, azimuth: float, elevation: float) -> bytes:
    return f"CMD:MOV:{azimuth:.3f},{elevation:.3f};".encode("ascii")

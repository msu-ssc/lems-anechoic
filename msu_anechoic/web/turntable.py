"""Web-facing access to the threaded turntable controller."""

from __future__ import annotations

import datetime
import math
import threading
import time
from collections.abc import Callable
from typing import Protocol

from msu_anechoic import experiment
from msu_anechoic import turntable2
from msu_anechoic.util.coordinate import Coordinate

DEFAULT_RECENT_HISTORY_TIME = 60.0
DEFAULT_RECENT_HISTORY_RATE = 10.0
DEFAULT_HISTORY_MAX_TIME = 7_200.0
DEFAULT_HISTORY_RATE = 0.5
DEFAULT_HISTORY_MAX_POINTS = 50_000
DEFAULT_REFRESH_INTERVAL = 1.0
MAX_HISTORY_MAX_TIME = 86_400.0
MAX_HISTORY_MAX_POINTS = 50_000
MOVE_TIMEOUT_SAFETY_FACTOR = 1.5
MOVE_TIMEOUT_MINIMUM = 5.0


class TurntableLike(Protocol):
    def get_complete_state(self) -> turntable2.TurntableCompleteState: ...

    def position_history(self) -> tuple[turntable2.PositionSample, ...]: ...

    def command_history(self) -> tuple[turntable2.CommandWrite, ...]: ...

    def set_position(self, *, pan: float, tilt: float, timeout: float = 5.0) -> None: ...

    def move_to(self, *, pan: float, tilt: float, move_timeout: float = 120.0) -> None: ...

    def confirm_position(self) -> None: ...

    def abort(self) -> None: ...


def _find_turntable() -> turntable2.Turntable:
    return turntable2.find(event_history_size=MAX_HISTORY_MAX_POINTS)


class TurntableWebService:
    """Own lazy hardware discovery and provide consistent web snapshots."""

    def __init__(
        self,
        *,
        turntable: TurntableLike | None = None,
        finder: Callable[[], TurntableLike] = _find_turntable,
        retry_interval: float = 5.0,
    ) -> None:
        self._turntable = turntable
        self._finder = finder
        self._retry_interval = retry_interval
        self._next_connection_attempt = 0.0
        self._connection_error: str | None = None
        self._lock = threading.RLock()

    def set_turntable(self, turntable: TurntableLike | None) -> None:
        """Replace the managed controller, primarily for embedding and tests."""

        with self._lock:
            self._turntable = turntable
            self._connection_error = None
            self._next_connection_attempt = 0.0

    def ensure_connected(self) -> TurntableLike | None:
        with self._lock:
            if self._turntable is not None:
                if self._turntable.get_complete_state().state != turntable2.TurntableState.CLOSED:
                    return self._turntable
                self._turntable = None

            now = time.monotonic()
            if now < self._next_connection_attempt:
                return None
            self._next_connection_attempt = now + self._retry_interval
            try:
                self._turntable = self._finder()
                self._connection_error = None
            except Exception as exc:
                self._connection_error = f"{type(exc).__name__}: {exc}"
                self._turntable = None
            return self._turntable

    def require_connected(self) -> TurntableLike:
        turntable = self.ensure_connected()
        if turntable is None:
            raise RuntimeError(self.connection_error or "Turntable is not connected")
        return turntable

    @property
    def connection_error(self) -> str | None:
        with self._lock:
            return self._connection_error

    def set_position(self, *, pan: float, tilt: float) -> None:
        turntable = self.require_connected()
        permissions = _control_permissions(turntable.get_complete_state())
        if not permissions["set_enabled"]:
            raise turntable2.TurntableError("SET is not available in the current controller state")
        turntable.set_position(pan=pan, tilt=tilt)

    def confirm_position(self) -> None:
        turntable = self.require_connected()
        permissions = _control_permissions(turntable.get_complete_state())
        if not permissions["confirm_enabled"]:
            raise turntable2.TurntableError("CONFIRM requires an idle controller with a reported position")
        turntable.confirm_position()

    def move_to(self, *, pan: float, tilt: float, timeout: float | None = None) -> dict[str, float]:
        turntable = self.require_connected()
        state = turntable.get_complete_state()
        permissions = _control_permissions(state)
        if not permissions["move_enabled"]:
            raise turntable2.TurntableError("MOVE requires a connected controller with its position set")
        if state.corrected_position is None:
            raise turntable2.TurntableError("MOVE requires a reported current position")

        estimated_travel_time = experiment.estimate_move_time(
            (state.corrected_position.pan, state.corrected_position.tilt),
            (pan, tilt),
        )
        automatic_timeout = estimated_travel_time * MOVE_TIMEOUT_SAFETY_FACTOR + MOVE_TIMEOUT_MINIMUM
        selected_timeout = automatic_timeout if timeout is None else timeout
        if not math.isfinite(selected_timeout) or selected_timeout <= 0:
            raise ValueError("timeout must be a finite number greater than zero")
        turntable.move_to(pan=pan, tilt=tilt, move_timeout=selected_timeout)
        return {
            "estimated_travel_time": estimated_travel_time,
            "timeout": selected_timeout,
        }

    def abort(self) -> None:
        """Synchronously send the controller's immediate stop command."""

        self.require_connected().abort()

    def status_payload(
        self,
        *,
        max_time: float,
        max_points: int,
        after: datetime.datetime | None = None,
    ) -> dict:
        _validate_history_options(max_time=max_time, max_points=max_points)
        if after is not None and after.tzinfo is None:
            raise ValueError("after must include a timezone")
        turntable = self.ensure_connected()
        if turntable is None:
            return _disconnected_payload(self.connection_error)

        with self._lock:
            complete_state = turntable.get_complete_state()
            history = turntable.position_history()
            commands = turntable.command_history()

        if history:
            largest_received_timestamp = max(sample.timestamp for sample in history)
            cutoff = largest_received_timestamp - datetime.timedelta(seconds=max_time)
            history = tuple(sample for sample in history if sample.timestamp >= cutoff)
        if after is not None:
            history = tuple(sample for sample in history if sample.timestamp > after)
        history = history[-max_points:]
        return {
            "connected": True,
            "connection_error": None,
            "state": _complete_state_payload(complete_state),
            "controls": _control_permissions(complete_state),
            "history": [_sample_payload(sample) for sample in history],
            "commands": [_command_payload(command) for command in commands],
        }


def _control_permissions(state: turntable2.TurntableCompleteState) -> dict[str, bool]:
    is_open = state.state != turntable2.TurntableState.CLOSED
    is_idle = state.activity == turntable2.TurntableActivity.IDLE
    has_live_position = (
        state.state not in {turntable2.TurntableState.CLOSED, turntable2.TurntableState.NO_COMMUNICATION}
        and state.uncorrected_position is not None
    )
    return {
        "set_enabled": is_open,
        "move_enabled": is_open and (state.has_been_set or state.set_requested),
        "confirm_enabled": is_idle and has_live_position,
        "abort_enabled": is_open,
    }


def _validate_history_options(*, max_time: float, max_points: int) -> None:
    if not math.isfinite(max_time) or max_time <= 0 or max_time > MAX_HISTORY_MAX_TIME:
        raise ValueError(f"max_time must be greater than 0 and at most {MAX_HISTORY_MAX_TIME:g} seconds")
    if max_points <= 0 or max_points > MAX_HISTORY_MAX_POINTS:
        raise ValueError(f"max_points must be between 1 and {MAX_HISTORY_MAX_POINTS}")


def _disconnected_payload(error: str | None) -> dict:
    return {
        "connected": False,
        "connection_error": error or "No turntable connection is available",
        "state": {
            "state": "disconnected",
            "activity": "idle",
            "activity_phase": None,
            "uncorrected_position": None,
            "corrected_position": None,
            "current_regime": None,
            "regime_offset": None,
            "most_recent_position_event": None,
            "last_communication_at": None,
            "seconds_since_last_communication": None,
            "communication_timeout": None,
            "activity_timeout_at": None,
            "target_position": None,
            "internal_target": None,
            "queued_command_count": 0,
            "has_been_set": False,
            "set_requested": False,
            "last_error": None,
            "event_count": 0,
            "position_history_count": 0,
            "position_history_generation": 0,
        },
        "controls": {
            "set_enabled": False,
            "move_enabled": False,
            "confirm_enabled": False,
            "abort_enabled": False,
        },
        "history": [],
        "commands": [],
    }


def _complete_state_payload(state: turntable2.TurntableCompleteState) -> dict:
    position_event = state.most_recent_position_event
    az_el_position = _az_el_payload(state.corrected_position)
    az_el_target = _az_el_payload(state.target_position)
    return {
        "captured_at": state.captured_at.isoformat(),
        "state": state.state.value,
        "activity": state.activity.value,
        "activity_phase": state.activity_phase,
        "uncorrected_position": _yaw_pitch_payload(state.uncorrected_position),
        "corrected_position": _pan_tilt_payload(state.corrected_position),
        "az_el_position": az_el_position,
        "current_regime": (
            {
                "center_tilt": state.current_regime.center_tilt,
                "minimum_tilt": state.current_regime.minimum_tilt,
                "maximum_tilt": state.current_regime.maximum_tilt,
            }
            if state.current_regime is not None
            else None
        ),
        "regime_offset": _pan_tilt_payload(state.regime_offset),
        "most_recent_position_event": (
            {
                "timestamp": position_event.timestamp.isoformat(),
                "yaw": position_event.yaw,
                "pitch": position_event.pitch,
            }
            if position_event is not None
            else None
        ),
        "last_communication_at": (
            state.last_communication_at.isoformat() if state.last_communication_at is not None else None
        ),
        "seconds_since_last_communication": (
            state.seconds_since_last_communication
            if math.isfinite(state.seconds_since_last_communication)
            else None
        ),
        "communication_timeout": state.communication_timeout,
        "activity_timeout_at": (
            state.activity_timeout_at.isoformat() if state.activity_timeout_at is not None else None
        ),
        "target_position": _pan_tilt_payload(state.target_position),
        "az_el_target": az_el_target,
        "internal_target": _yaw_pitch_payload(state.internal_target),
        "queued_command_count": state.queued_command_count,
        "has_been_set": state.has_been_set,
        "set_requested": state.set_requested,
        "last_error": state.last_error,
        "event_count": state.event_count,
        "position_history_count": state.position_history_count,
        "position_history_generation": state.position_history_generation,
    }


def _sample_payload(sample: turntable2.PositionSample) -> dict:
    az_el = _az_el_payload(sample.corrected_position)
    assert az_el is not None
    return {
        "timestamp": sample.timestamp.isoformat(),
        "yaw": sample.internal_position.yaw,
        "pitch": sample.internal_position.pitch,
        "pan": sample.corrected_position.pan,
        "tilt": sample.corrected_position.tilt,
        "azimuth": az_el["azimuth"],
        "elevation": az_el["elevation"],
    }


def _command_payload(command: turntable2.CommandWrite) -> dict:
    return {
        "timestamp": command.timestamp.isoformat(),
        "bytes": repr(command.command),
        "hex": command.command.hex(" "),
        "byte_count": len(command.command),
    }


def _yaw_pitch_payload(position: turntable2.YawPitch | None) -> dict | None:
    if position is None:
        return None
    return {"yaw": position.yaw, "pitch": position.pitch}


def _pan_tilt_payload(position: turntable2.PanTilt | None) -> dict | None:
    if position is None:
        return None
    return {"pan": position.pan, "tilt": position.tilt}


def _az_el_payload(position: turntable2.PanTilt | None) -> dict | None:
    if position is None:
        return None
    coordinate = Coordinate.from_turntable(
        azimuth=position.pan,
        elevation=position.tilt,
    )
    return {
        "azimuth": coordinate.antenna_azimuth,
        "elevation": coordinate.antenna_elevation,
    }


turntable_service = TurntableWebService()

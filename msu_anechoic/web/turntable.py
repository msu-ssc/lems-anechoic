"""Web-facing access to the threaded turntable controller."""

from __future__ import annotations

import datetime
import math
import threading
import time
from collections.abc import Callable
from typing import Protocol

from msu_anechoic import turntable2

DEFAULT_HISTORY_MAX_TIME = 3_600.0
DEFAULT_HISTORY_MAX_POINTS = 1_000
DEFAULT_REFRESH_INTERVAL = 1.0
MAX_HISTORY_MAX_TIME = 86_400.0
MAX_HISTORY_MAX_POINTS = 50_000


class TurntableLike(Protocol):
    def get_complete_state(self) -> turntable2.TurntableCompleteState: ...

    def position_history(self) -> tuple[turntable2.PositionSample, ...]: ...

    def set_position(self, *, pan: float, tilt: float, timeout: float = 5.0) -> None: ...

    def move_to(self, *, pan: float, tilt: float, move_timeout: float = 120.0) -> None: ...

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

    def move_to(self, *, pan: float, tilt: float) -> None:
        turntable = self.require_connected()
        permissions = _control_permissions(turntable.get_complete_state())
        if not permissions["move_enabled"]:
            raise turntable2.TurntableError("MOVE requires a connected controller with its position set")
        turntable.move_to(pan=pan, tilt=tilt)

    def abort(self) -> None:
        """Synchronously send the controller's immediate stop command."""

        self.require_connected().abort()

    def status_payload(self, *, max_time: float, max_points: int) -> dict:
        _validate_history_options(max_time=max_time, max_points=max_points)
        turntable = self.ensure_connected()
        if turntable is None:
            return _disconnected_payload(self.connection_error)

        with self._lock:
            complete_state = turntable.get_complete_state()
            history = turntable.position_history()

        cutoff = complete_state.captured_at - datetime.timedelta(seconds=max_time)
        history = tuple(sample for sample in history if sample.timestamp >= cutoff)[-max_points:]
        return {
            "connected": True,
            "connection_error": None,
            "state": _complete_state_payload(complete_state),
            "controls": _control_permissions(complete_state),
            "history": [_sample_payload(sample) for sample in history],
        }


def _control_permissions(state: turntable2.TurntableCompleteState) -> dict[str, bool]:
    is_open = state.state != turntable2.TurntableState.CLOSED
    return {
        "set_enabled": is_open,
        "move_enabled": is_open and (state.has_been_set or state.set_requested),
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
        },
        "controls": {
            "set_enabled": False,
            "move_enabled": False,
            "abort_enabled": False,
        },
        "history": [],
    }


def _complete_state_payload(state: turntable2.TurntableCompleteState) -> dict:
    position_event = state.most_recent_position_event
    return {
        "captured_at": state.captured_at.isoformat(),
        "state": state.state.value,
        "activity": state.activity.value,
        "activity_phase": state.activity_phase,
        "uncorrected_position": _yaw_pitch_payload(state.uncorrected_position),
        "corrected_position": _pan_tilt_payload(state.corrected_position),
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
        "internal_target": _yaw_pitch_payload(state.internal_target),
        "queued_command_count": state.queued_command_count,
        "has_been_set": state.has_been_set,
        "set_requested": state.set_requested,
        "last_error": state.last_error,
        "event_count": state.event_count,
        "position_history_count": state.position_history_count,
    }


def _sample_payload(sample: turntable2.PositionSample) -> dict:
    return {
        "timestamp": sample.timestamp.isoformat(),
        "yaw": sample.internal_position.yaw,
        "pitch": sample.internal_position.pitch,
        "pan": sample.corrected_position.pan,
        "tilt": sample.corrected_position.tilt,
    }


def _yaw_pitch_payload(position: turntable2.YawPitch | None) -> dict | None:
    if position is None:
        return None
    return {"yaw": position.yaw, "pitch": position.pitch}


def _pan_tilt_payload(position: turntable2.PanTilt | None) -> dict | None:
    if position is None:
        return None
    return {"pan": position.pan, "tilt": position.tilt}


turntable_service = TurntableWebService()

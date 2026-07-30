import threading
import time
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from msu_anechoic import turntable2


class FakeSerial:
    def __init__(self, *, respond_to_moves=True, respond_to_sets=True):
        self.respond_to_moves = respond_to_moves
        self.respond_to_sets = respond_to_sets
        self.writes = []
        self.closed = False
        self._input = bytearray()
        self._lock = threading.Lock()

    @property
    def in_waiting(self):
        with self._lock:
            return len(self._input)

    def read(self, size=1):
        with self._lock:
            data = bytes(self._input[:size])
            del self._input[:size]
            return data

    def write(self, data):
        with self._lock:
            self.writes.append(data)
        if data.startswith(b"CMD:SET:") and self.respond_to_sets:
            coordinates = data.removeprefix(b"CMD:SET:").removesuffix(b";")
            yaw, pitch = (float(value) for value in coordinates.split(b","))
            self.emit_internal_position(yaw=yaw, pitch=pitch)
        elif data.startswith(b"CMD:MOV:") and self.respond_to_moves:
            coordinates = data.removeprefix(b"CMD:MOV:").removesuffix(b";")
            yaw, pitch = (float(value) for value in coordinates.split(b","))
            self.emit_internal_position(yaw=yaw, pitch=pitch)
        return len(data)

    def close(self):
        self.closed = True

    def emit(self, message):
        with self._lock:
            self._input.extend(message)

    def emit_internal_position(self, *, yaw, pitch):
        self.emit(f"Pos= El: {pitch:.2f} , Az: {yaw:.2f} \r\n".encode())


def wait_for(predicate, *, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError("condition was not met before timeout")


def make_turntable(fake, **kwargs):
    return turntable2.Turntable(
        serial_connection=fake,
        poll_interval=0.001,
        communication_timeout=kwargs.pop("communication_timeout", 1.0),
        **kwargs,
    )


def test_received_messages_are_immutable_and_hashable():
    event = turntable2.parse_received_message(b"Pos= El: -12.34 , Az: 56.78 \r\n")

    assert isinstance(event, turntable2.ReceivedMessagePosition)
    assert event.kind == "position"
    assert event.yaw == 56.78
    assert event.pitch == -12.34
    assert event.timestamp.tzinfo is not None
    assert hash(event)
    with pytest.raises(ValidationError):
        event.yaw = 0


def test_non_position_input_becomes_an_other_event():
    event = turntable2.parse_received_message(b"garbage\r\n")

    assert type(event) is turntable2.ReceivedMessage
    assert event.kind == "other"
    assert event.message == b"garbage\r\n"


def test_serial_listener_frames_fragmented_lines():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit(b"junk\r\nPos= El: 1")
        fake.emit(b"2.34 , Az: -5.67 \r\n")

        event = wait_for(lambda: turntable.most_recent_event(kind="position"))

        assert event.yaw == -5.67
        assert event.pitch == 12.34
        assert turntable.most_recent_event(kind="other").message == b"junk\r\n"
    finally:
        turntable.close()


def test_set_and_move_are_queued_and_tilt_regimes_are_transparent():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=4, pitch=2)
        wait_for(lambda: turntable.current_position() is not None)

        assert turntable.current_state() == turntable2.TurntableState.NOT_SET
        turntable.set_position(pan=0, tilt=0)
        turntable.move_to(pan=15, tilt=-40)

        wait_for(
            lambda: (
                turntable.current_state() == turntable2.TurntableState.STOPPED
                and turntable.current_position() == turntable2.PanTilt(15, -40)
            )
        )

        assert b"CMD:SET:0.000,0.000;" in fake.writes
        assert b"CMD:MOV:0.000,-27.000;" in fake.writes
        assert b"CMD:MOV:15.000,-13.000;" in fake.writes
        assert turntable.most_recent_event(kind="position").pitch == -13
        command_history = turntable.command_history()
        assert [write.command for write in command_history] == fake.writes
        assert all(write.timestamp.tzinfo is not None for write in command_history)
        assert list(command_history) == sorted(
            command_history,
            key=lambda write: write.timestamp,
        )

        complete_state = turntable.get_complete_state()
        assert complete_state.uncorrected_position == turntable2.YawPitch(yaw=15, pitch=-13)
        assert complete_state.corrected_position == turntable2.PanTilt(pan=15, tilt=-40)
        assert complete_state.current_regime == turntable2.TiltRegime(center_tilt=-27, allowable_offset=29)
        assert complete_state.regime_offset == turntable2.PanTilt(pan=0, tilt=-27)
        assert complete_state.most_recent_position_event.pitch == -13
        assert complete_state.activity == turntable2.TurntableActivity.IDLE
        assert complete_state.activity_timeout_at is None
        assert complete_state.position_history_count == len(turntable.position_history())
        assert complete_state.position_history_generation == 1
        assert turntable.position_history()[-1] == turntable2.PositionSample(
            timestamp=complete_state.most_recent_position_event.timestamp,
            internal_position=turntable2.YawPitch(yaw=15, pitch=-13),
            corrected_position=turntable2.PanTilt(pan=15, tilt=-40),
        )
        assert any(
            sample.internal_position == turntable2.YawPitch(yaw=0, pitch=0)
            and sample.corrected_position == turntable2.PanTilt(pan=0, tilt=-27)
            for sample in turntable.position_history()
        )
        assert all(
            sample.internal_position != turntable2.YawPitch(yaw=4, pitch=2)
            for sample in turntable.position_history()
        )
    finally:
        turntable.close()


def test_confirm_trusts_the_current_position_without_sending_set():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=4, pitch=2)
        wait_for(lambda: turntable.current_position() is not None)

        turntable.confirm_position()

        state = turntable.get_complete_state()
        assert state.state == turntable2.TurntableState.STOPPED
        assert state.has_been_set
        assert state.corrected_position == turntable2.PanTilt(4, 2)
        assert state.regime_offset == turntable2.PanTilt(0, 0)
        assert not any(command.startswith(b"CMD:SET:") for command in fake.writes)

        turntable.move_to(pan=5, tilt=3)
        wait_for(lambda: b"CMD:MOV:5.000,3.000;" in fake.writes)
    finally:
        turntable.close()


def test_complete_state_describes_active_move_and_timeout():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        turntable.move_to(pan=10, tilt=5, move_timeout=10)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.MOVING)
        complete_state = turntable.get_complete_state()

        assert complete_state.state == turntable2.TurntableState.MOVING
        assert complete_state.activity == turntable2.TurntableActivity.MOVING
        assert complete_state.activity_phase == "final"
        assert complete_state.uncorrected_position == turntable2.YawPitch(yaw=0, pitch=0)
        assert complete_state.corrected_position == turntable2.PanTilt(pan=0, tilt=0)
        assert complete_state.current_regime.center_tilt == 0
        assert complete_state.regime_offset == turntable2.PanTilt(pan=0, tilt=0)
        assert complete_state.most_recent_position_event.yaw == 0
        assert complete_state.most_recent_position_event.pitch == 0
        assert complete_state.activity_timeout_at.tzinfo is not None
        assert complete_state.activity_timeout_at > complete_state.captured_at
        assert complete_state.communication_timeout == 1.0
        assert complete_state.target_position == turntable2.PanTilt(pan=10, tilt=5)
        assert complete_state.internal_target == turntable2.YawPitch(yaw=10, pitch=5)
        assert complete_state.queued_command_count == 0
        assert complete_state.has_been_set
        assert not complete_state.set_requested
        assert complete_state.last_error is None
        assert complete_state.event_count >= 1
        with pytest.raises(FrozenInstanceError):
            complete_state.state = turntable2.TurntableState.STOPPED
    finally:
        turntable.close()


def test_regime_change_tracks_pan_and_tilt_offsets():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        turntable.move_to(pan=15, tilt=-40)
        wait_for(lambda: b"CMD:MOV:0.000,-27.000;" in fake.writes)
        # The firmware stopped just inside the accepted yaw margin before the
        # regime-reset SET command. That residual becomes part of the offset.
        fake.emit_internal_position(yaw=0.05, pitch=-27)
        wait_for(lambda: b"CMD:MOV:14.950,-13.000;" in fake.writes)

        complete_state = turntable.get_complete_state()
        assert complete_state.current_regime.center_tilt == -27
        assert complete_state.regime_offset == turntable2.PanTilt(pan=0.05, tilt=-27)
        assert complete_state.target_position == turntable2.PanTilt(pan=15, tilt=-40)
        assert complete_state.internal_target == turntable2.YawPitch(yaw=14.95, pitch=-13)
    finally:
        turntable.close()


@pytest.mark.parametrize(
    ("destination", "final_wire_pitch"),
    [(-90, -9), (45, 18)],
)
def test_move_crosses_multiple_regimes(destination, final_wire_pitch):
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        turntable.move_to(pan=12, tilt=destination)

        wait_for(
            lambda: (
                turntable.current_state() == turntable2.TurntableState.STOPPED
                and turntable.current_position() == turntable2.PanTilt(12, destination)
            )
        )

        expected_command = f"CMD:MOV:12.000,{final_wire_pitch:.3f};".encode()
        assert expected_command in fake.writes
    finally:
        turntable.close()


def test_move_requires_set_and_valid_physical_bounds():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(turntable2.TurntableError, match="must be set"):
            turntable.move_to(pan=0, tilt=0)
        turntable.set_position(pan=0, tilt=0)
        with pytest.raises(ValueError, match="pan"):
            turntable.move_to(pan=181, tilt=0)
        with pytest.raises(ValueError, match="tilt"):
            turntable.move_to(pan=0, tilt=46)
    finally:
        turntable.close()


def test_nonzero_set_position_is_accepted_and_applied():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        turntable.set_position(pan=20, tilt=10)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        assert b"CMD:SET:20.000,10.000;" in fake.writes
        state = turntable.get_complete_state()
        assert state.corrected_position == turntable2.PanTilt(20, 10)
        assert state.current_regime == turntable2.TiltRegime(center_tilt=0, allowable_offset=29)
        assert state.regime_offset == turntable2.PanTilt(0, 0)
    finally:
        turntable.close()


@pytest.mark.parametrize(
    ("pan", "tilt"),
    [
        (-180, -90),
        (180, 90),
    ],
)
def test_set_position_accepts_inclusive_boundaries(pan, tilt):
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        turntable.set_position(pan=pan, tilt=tilt)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        assert turntable.current_position() == turntable2.PanTilt(pan, tilt)
    finally:
        turntable.close()


@pytest.mark.parametrize(
    ("pan", "tilt", "message"),
    [
        (-180.001, 0, "pan"),
        (180.001, 0, "pan"),
        (0, -90.001, "tilt"),
        (0, 90.001, "tilt"),
        (float("nan"), 0, "pan"),
        (0, float("inf"), "tilt"),
    ],
)
def test_invalid_set_position_is_rejected_without_a_write(pan, tilt, message):
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(ValueError, match=message):
            turntable.set_position(pan=pan, tilt=tilt)
        assert fake.writes == []
    finally:
        turntable.close()


def test_complete_state_describes_active_nonzero_set():
    fake = FakeSerial(respond_to_sets=False)
    turntable = make_turntable(fake)
    try:
        turntable.set_position(pan=20, tilt=10, timeout=10)
        wait_for(lambda: turntable.get_complete_state().activity == turntable2.TurntableActivity.SETTING_POSITION)

        state = turntable.get_complete_state()
        assert state.target_position == turntable2.PanTilt(20, 10)
        assert state.internal_target == turntable2.YawPitch(20, 10)
    finally:
        turntable.close()


def test_abort_stops_the_active_move_and_cancels_queued_moves():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        turntable.move_to(pan=10, tilt=0)
        turntable.move_to(pan=20, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.MOVING)

        turntable.abort()

        # ABORT bypasses the queue and performs the stop write before returning.
        assert fake.writes[-1] == b"p"
        assert turntable.command_history()[-1].command == b"p"
        assert turntable.current_state() == turntable2.TurntableState.STOPPED
        time.sleep(0.03)
        assert b"CMD:MOV:20.000,0.000;" not in fake.writes
    finally:
        turntable.close()


def test_move_timeout_aborts_and_is_observable():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake, communication_timeout=1.0)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        turntable.move_to(pan=10, tilt=0, move_timeout=0.03)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.TIMED_OUT)
        assert isinstance(turntable.last_error(), TimeoutError)
        assert b"p" in fake.writes
    finally:
        turntable.close()


def test_set_timeout_cancels_a_move_queued_behind_it():
    fake = FakeSerial(respond_to_moves=False)

    def ignore_commands(data):
        with fake._lock:
            fake.writes.append(data)
        return len(data)

    fake.write = ignore_commands
    turntable = make_turntable(fake, communication_timeout=1.0)
    try:
        fake.emit_internal_position(yaw=5, pitch=5)
        wait_for(lambda: turntable.current_position() is not None)
        turntable.set_position(pan=0, tilt=0, timeout=0.03)
        turntable.move_to(pan=10, tilt=0)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.TIMED_OUT)

        assert not any(command.startswith(b"CMD:MOV:") for command in fake.writes)
    finally:
        turntable.close()


def test_communication_timeout_resets_controller_to_not_set():
    fake = FakeSerial()
    turntable = make_turntable(fake, communication_timeout=0.03)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.NO_COMMUNICATION)
        with pytest.raises(turntable2.TurntableError, match="must be set"):
            turntable.move_to(pan=0, tilt=0)

        fake.emit_internal_position(yaw=0, pitch=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.NOT_SET)
    finally:
        turntable.close()


def test_close_stops_threads_and_closes_serial_connection():
    fake = FakeSerial()
    turntable = make_turntable(fake)

    turntable.close()

    assert fake.closed
    assert turntable.current_state() == turntable2.TurntableState.CLOSED
    turntable.close()

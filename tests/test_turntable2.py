import threading
import time

import pytest
from pydantic import ValidationError

from msu_anechoic import AzEl
from msu_anechoic import turntable2


class FakeSerial:
    def __init__(self, *, respond_to_moves=True):
        self.respond_to_moves = respond_to_moves
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
        if data.startswith(b"CMD:SET:"):
            self.emit_position(azimuth=0, elevation=0)
        elif data.startswith(b"CMD:MOV:") and self.respond_to_moves:
            coordinates = data.removeprefix(b"CMD:MOV:").removesuffix(b";")
            azimuth, elevation = (float(value) for value in coordinates.split(b","))
            self.emit_position(azimuth=azimuth, elevation=elevation)
        return len(data)

    def close(self):
        self.closed = True

    def emit(self, message):
        with self._lock:
            self._input.extend(message)

    def emit_position(self, *, azimuth, elevation):
        self.emit(f"Pos= El: {elevation:.2f} , Az: {azimuth:.2f} \r\n".encode())


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
    assert event.azimuth == 56.78
    assert event.elevation == -12.34
    assert event.timestamp.tzinfo is not None
    assert hash(event)
    with pytest.raises(ValidationError):
        event.azimuth = 0


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

        assert event.azimuth == -5.67
        assert event.elevation == 12.34
        assert turntable.most_recent_event(kind="other").message == b"junk\r\n"
    finally:
        turntable.close()


def test_set_and_move_are_queued_and_elevation_regimes_are_transparent():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_position(azimuth=4, elevation=2)
        wait_for(lambda: turntable.current_position() is not None)

        assert turntable.current_state() == turntable2.TurntableState.NOT_SET
        turntable.set_position(azimuth=0, elevation=0)
        turntable.move_to(azimuth=15, elevation=-40)

        wait_for(
            lambda: (
                turntable.current_state() == turntable2.TurntableState.STOPPED
                and turntable.current_position() == AzEl(15, -40)
            )
        )

        assert b"CMD:SET:0.000,0.000;" in fake.writes
        assert b"CMD:MOV:0.000,-27.000;" in fake.writes
        assert b"CMD:MOV:15.000,-13.000;" in fake.writes
        assert turntable.most_recent_event(kind="position").elevation == -40
    finally:
        turntable.close()


@pytest.mark.parametrize(
    ("destination", "final_wire_elevation"),
    [(-90, -9), (45, 18)],
)
def test_move_crosses_multiple_regimes(destination, final_wire_elevation):
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_position(azimuth=0, elevation=0)
        turntable.set_position(azimuth=0, elevation=0)
        turntable.move_to(azimuth=12, elevation=destination)

        wait_for(
            lambda: (
                turntable.current_state() == turntable2.TurntableState.STOPPED
                and turntable.current_position() == AzEl(12, destination)
            )
        )

        expected_command = f"CMD:MOV:12.000,{final_wire_elevation:.3f};".encode()
        assert expected_command in fake.writes
    finally:
        turntable.close()


def test_move_requires_set_and_valid_physical_bounds():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(turntable2.TurntableError, match="must be set"):
            turntable.move_to(azimuth=0, elevation=0)
        turntable.set_position(azimuth=0, elevation=0)
        with pytest.raises(ValueError, match="azimuth"):
            turntable.move_to(azimuth=181, elevation=0)
        with pytest.raises(ValueError, match="elevation"):
            turntable.move_to(azimuth=0, elevation=46)
    finally:
        turntable.close()


def test_invalid_set_position_is_rejected_without_a_write():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(ValueError, match="only supports"):
            turntable.set_position(azimuth=1, elevation=0)
        assert fake.writes == []
    finally:
        turntable.close()


def test_abort_stops_the_active_move_and_cancels_queued_moves():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_position(azimuth=0, elevation=0)
        turntable.set_position(azimuth=0, elevation=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        turntable.move_to(azimuth=10, elevation=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.MOVING)

        turntable.abort()

        wait_for(lambda: b"p" in fake.writes)
        assert turntable.current_state() == turntable2.TurntableState.STOPPED
    finally:
        turntable.close()


def test_move_timeout_aborts_and_is_observable():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake, communication_timeout=1.0)
    try:
        fake.emit_position(azimuth=0, elevation=0)
        turntable.set_position(azimuth=0, elevation=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        turntable.move_to(azimuth=10, elevation=0, move_timeout=0.03)

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
        fake.emit_position(azimuth=5, elevation=5)
        wait_for(lambda: turntable.current_position() is not None)
        turntable.set_position(azimuth=0, elevation=0, timeout=0.03)
        turntable.move_to(azimuth=10, elevation=0)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.TIMED_OUT)

        assert not any(command.startswith(b"CMD:MOV:") for command in fake.writes)
    finally:
        turntable.close()


def test_communication_timeout_resets_controller_to_not_set():
    fake = FakeSerial()
    turntable = make_turntable(fake, communication_timeout=0.03)
    try:
        fake.emit_position(azimuth=0, elevation=0)
        turntable.set_position(azimuth=0, elevation=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.NO_COMMUNICATION)
        with pytest.raises(turntable2.TurntableError, match="must be set"):
            turntable.move_to(azimuth=0, elevation=0)

        fake.emit_position(azimuth=0, elevation=0)
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

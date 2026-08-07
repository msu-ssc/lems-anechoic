import datetime

import pytest
from fastapi import HTTPException
from fastapi import Request

from msu_anechoic import turntable2
from msu_anechoic.web.app import WEB_ROOT
from msu_anechoic.web.app import _decode_zmq_position_message
from msu_anechoic.web.app import _TurntablePositionCommand
from msu_anechoic.web.app import _validate_zmq_position_endpoint
from msu_anechoic.web.app import abort_turntable
from msu_anechoic.web.app import app
from msu_anechoic.web.app import move_turntable
from msu_anechoic.web.app import set_turntable_position
from msu_anechoic.web.app import three_dimensional_experiment
from msu_anechoic.web.app import turntable_control
from msu_anechoic.web.app import turntable_status
from msu_anechoic.web.turntable import TurntableWebService
from msu_anechoic.web.turntable import turntable_service

UTC = datetime.timezone.utc


def page_request(path):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": [],
            "client": ("test", 123),
            "server": ("test", 80),
            "app": app,
            "router": app.router,
        }
    )


class FakeTurntable:
    def __init__(self, state, history=()):
        self.state = state
        self.history = tuple(history)
        self.commands = []

    def get_complete_state(self):
        return self.state

    def position_history(self):
        return self.history

    def set_position(self, *, pan, tilt, timeout=5.0):
        self.commands.append(("set", pan, tilt))

    def move_to(self, *, pan, tilt, move_timeout=120.0):
        self.commands.append(("move", pan, tilt))

    def abort(self):
        self.commands.append(("abort",))


def complete_state(
    *,
    captured_at=None,
    state=turntable2.TurntableState.STOPPED,
    activity=turntable2.TurntableActivity.IDLE,
    has_been_set=True,
    set_requested=False,
):
    captured_at = captured_at or datetime.datetime.now(tz=UTC)
    position_event = turntable2.ReceivedMessagePosition(
        message=b"Pos= El: -13.00 , Az: 15.00 \r\n",
        timestamp=captured_at - datetime.timedelta(seconds=1),
        yaw=15,
        pitch=-13,
    )
    return turntable2.TurntableCompleteState(
        captured_at=captured_at,
        state=state,
        activity=activity,
        activity_phase="final" if state == turntable2.TurntableState.MOVING else None,
        uncorrected_position=turntable2.YawPitch(15, -13),
        corrected_position=turntable2.PanTilt(15, -40),
        current_regime=turntable2.TiltRegime(center_tilt=-27, allowable_offset=29),
        regime_offset=turntable2.PanTilt(0, -27),
        most_recent_position_event=position_event,
        most_recent_event=position_event,
        last_communication_at=position_event.timestamp,
        seconds_since_last_communication=1,
        communication_timeout=2,
        activity_timeout_at=(
            captured_at + datetime.timedelta(seconds=30)
            if state == turntable2.TurntableState.MOVING
            else None
        ),
        target_position=(
            turntable2.PanTilt(30, -50) if state == turntable2.TurntableState.MOVING else None
        ),
        internal_target=(
            turntable2.YawPitch(30, -23) if state == turntable2.TurntableState.MOVING else None
        ),
        queued_command_count=2,
        has_been_set=has_been_set,
        set_requested=set_requested,
        last_error=None,
        event_count=4,
        position_history_count=3,
    )


@pytest.fixture
def fake_turntable():
    captured_at = datetime.datetime.now(tz=UTC)
    state = complete_state(
        captured_at=captured_at,
        state=turntable2.TurntableState.MOVING,
        activity=turntable2.TurntableActivity.CHANGING_REGIME,
    )
    history = [
        turntable2.PositionSample(
            timestamp=captured_at - datetime.timedelta(seconds=4_000),
            internal_position=turntable2.YawPitch(0, 0),
            corrected_position=turntable2.PanTilt(0, 0),
        ),
        turntable2.PositionSample(
            timestamp=captured_at - datetime.timedelta(seconds=10),
            internal_position=turntable2.YawPitch(5, -5),
            corrected_position=turntable2.PanTilt(5, -32),
        ),
        turntable2.PositionSample(
            timestamp=captured_at - datetime.timedelta(seconds=1),
            internal_position=turntable2.YawPitch(15, -13),
            corrected_position=turntable2.PanTilt(15, -40),
        ),
    ]
    fake = FakeTurntable(state, history)
    turntable_service.set_turntable(fake)
    yield fake
    turntable_service.set_turntable(None)


def test_turntable_page_contains_status_history_and_controls():
    response = turntable_control(page_request("/turntable"))
    body = response.body.decode()

    assert response.status_code == 200
    assert "<h1>Turntable</h1>" in body
    assert 'id="history-max-time"' in body
    assert 'value="3600"' in body
    assert 'id="history-max-points"' in body
    assert 'value="1000"' in body
    assert 'id="refresh-interval"' in body
    assert 'value="1.0"' in body
    assert 'id="pan-tilt-plot"' in body
    assert 'id="yaw-pitch-plot"' in body
    assert 'data-command-form="set"' in body
    assert 'data-command-form="move"' in body
    assert "Emergency stop" in body
    assert '<a class="breadcrumb-home" href="/">MSU Anechoic Chamber</a>' in body
    assert 'aria-current="page">Turntable</span>' in body
    assert any(getattr(route, "path", None) == "/turntable" for route in app.routes)


def test_three_dimensional_page_contains_zmq_follow_controls():
    response = three_dimensional_experiment(page_request("/3d"))
    body = response.body.decode()

    assert response.status_code == 200
    assert 'id="follow-toggle"' in body
    assert 'id="follow-status"' in body
    assert 'id="follow-endpoint"' in body
    assert 'value="tcp://127.0.0.1:8005"' in body
    assert 'data-position-stream-url="http://test/3d/position-stream"' in body
    assert 'id="follow-file-input"' not in body
    assert any(getattr(route, "path", None) == "/3d/position-stream" for route in app.routes)


def test_zmq_position_message_matches_turntable_publisher_contract():
    message = (
        b'{"timestamp":"2027-01-01T00:00:00.000000+00:00",'
        b'"state":"moving","pan":123.456,"tilt":-87.654}'
    )

    assert _decode_zmq_position_message(message) == {
        "timestamp": "2027-01-01T00:00:00.000000+00:00",
        "state": "moving",
        "pan": 123.456,
        "tilt": -87.654,
    }


@pytest.mark.parametrize(
    "message",
    [
        b"not-json",
        b"[]",
        b'{"timestamp":"now","state":"moving","pan":null,"tilt":1}',
        b'{"timestamp":"now","state":"moving","pan":1,"tilt":"2"}',
    ],
)
def test_zmq_position_message_rejects_malformed_payloads(message):
    with pytest.raises(ValueError):
        _decode_zmq_position_message(message)


def test_zmq_position_endpoint_accepts_tcp_and_rejects_other_transports():
    assert _validate_zmq_position_endpoint("tcp://127.0.0.1:8005") == "tcp://127.0.0.1:8005"
    assert _validate_zmq_position_endpoint("tcp://turntable.local:9000") == "tcp://turntable.local:9000"

    for endpoint in ["udp://127.0.0.1:8005", "tcp://127.0.0.1", "tcp://127.0.0.1:99999"]:
        with pytest.raises(ValueError):
            _validate_zmq_position_endpoint(endpoint)


def test_three_dimensional_page_contains_camera_editor():
    response = three_dimensional_experiment(page_request("/3d"))
    body = response.body.decode()

    assert response.status_code == 200
    assert 'id="cameras-toggle"' in body
    assert 'id="cameras-panel"' in body
    assert 'id="camera-name"' in body
    assert 'id="camera-fov"' in body
    assert 'id="camera-aspect"' in body
    assert 'id="camera-view-indicator"' in body
    assert 'id="scene-view-select"' in body
    assert 'id="aut-toggle"' in body
    assert 'aria-controls="aut-panel"' in body
    assert 'id="aut-panel"' in body
    assert 'id="annotations-enabled" type="checkbox" checked' in body
    assert not any(getattr(route, "path", None) == "/3d/camera/{camera_name}" for route in app.routes)


def test_status_returns_paired_filtered_history_and_move_targets(fake_turntable):
    payload = turntable_status(max_time=3600, max_points=1000)
    assert payload["connected"] is True
    assert payload["state"]["state"] == "moving"
    assert payload["state"]["corrected_position"] == {"pan": 15, "tilt": -40}
    assert payload["state"]["uncorrected_position"] == {"yaw": 15, "pitch": -13}
    assert payload["state"]["target_position"] == {"pan": 30, "tilt": -50}
    assert payload["state"]["internal_target"] == {"yaw": 30, "pitch": -23}
    assert payload["controls"] == {
        "set_enabled": True,
        "move_enabled": True,
        "abort_enabled": True,
    }
    assert [(point["pan"], point["tilt"]) for point in payload["history"]] == [(5, -32), (15, -40)]
    assert [(point["yaw"], point["pitch"]) for point in payload["history"]] == [(5, -5), (15, -13)]


def test_status_honors_max_points_and_rejects_invalid_history_options(fake_turntable):
    payload = turntable_status(max_time=5000, max_points=1)
    assert len(payload["history"]) == 1
    assert payload["history"][0]["pan"] == 15

    with pytest.raises(HTTPException) as exc_info:
        turntable_status(max_time=0, max_points=1)
    assert exc_info.value.status_code == 400
    with pytest.raises(HTTPException) as exc_info:
        turntable_status(max_time=10, max_points=0)
    assert exc_info.value.status_code == 400


def test_set_move_and_emergency_stop_routes_call_controller(fake_turntable):
    assert set_turntable_position(_TurntablePositionCommand(pan=0, tilt=0))["ok"]
    assert move_turntable(_TurntablePositionCommand(pan=30, tilt=-50))["ok"]
    assert abort_turntable()["ok"]
    assert fake_turntable.commands == [
        ("set", 0.0, 0.0),
        ("move", 30.0, -50.0),
        ("abort",),
    ]


def test_move_is_disabled_and_rejected_until_set_is_requested(fake_turntable):
    fake_turntable.state = complete_state(
        state=turntable2.TurntableState.NOT_SET,
        has_been_set=False,
        set_requested=False,
    )
    status = turntable_status()
    assert status["controls"]["set_enabled"] is True
    assert status["controls"]["move_enabled"] is False
    assert status["controls"]["abort_enabled"] is True
    with pytest.raises(HTTPException) as exc_info:
        move_turntable(_TurntablePositionCommand(pan=5, tilt=5))
    assert exc_info.value.status_code == 400
    assert "requires" in exc_info.value.detail


def test_failed_hardware_discovery_returns_a_disconnected_snapshot():
    attempts = []

    def fail_to_find():
        attempts.append(True)
        raise turntable2.TurntableError("No USB turntable found")

    service = TurntableWebService(finder=fail_to_find, retry_interval=30)
    payload = service.status_payload(max_time=3600, max_points=1000)

    assert payload["connected"] is False
    assert payload["state"]["state"] == "disconnected"
    assert payload["controls"] == {
        "set_enabled": False,
        "move_enabled": False,
        "abort_enabled": False,
    }
    assert "No USB turntable found" in payload["connection_error"]
    service.status_payload(max_time=3600, max_points=1000)
    assert len(attempts) == 1


def test_turntable_script_marks_current_green_target_red_and_posts_abort():
    script = (WEB_ROOT / "static" / "turntable.js").read_text()

    assert 'cssColor("--status-green"' in script
    assert 'cssColor("--target-red"' in script
    assert 'state.state === "moving"' in script
    assert 'sendCommand("/turntable/abort")' in script
    assert 'document.querySelector(\'[data-control="set"]\').disabled' in script

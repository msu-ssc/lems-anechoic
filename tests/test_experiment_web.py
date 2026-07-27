import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi import Request

from msu_anechoic import experiment
from msu_anechoic import turntable2
from msu_anechoic.util.coordinate import Coordinate
from msu_anechoic.web.app import WEB_ROOT
from msu_anechoic.web.app import _ExperimentLoadRequest
from msu_anechoic.web.app import app
from msu_anechoic.web.app import experiment_control
from msu_anechoic.web.app import load_experiment
from msu_anechoic.web.experiment import ExperimentWebService
from msu_anechoic.web.experiment import experiment_service


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


def experiment_definition(**updates):
    definition = {
        "short_description": "web-test",
        "long_description": "A test loaded through the web interface.",
        "relative_folder_path": "experiments/web-test",
        "neutral_elevation": 5,
        "cuts": {
            "AZIMUTH": {
                "direction": "horizontal",
                "start_angle": -10,
                "end_angle": 10,
                "step_size": 10,
                "fixed_angle": 0,
            }
        },
    }
    definition.update(updates)
    return definition


@pytest.fixture(autouse=True)
def reset_global_experiment_service():
    experiment_service.reset_for_tests()
    yield
    experiment_service.reset_for_tests()


def test_experiment_page_has_load_run_and_abort_controls():
    response = experiment_control(page_request("/experiment"))
    body = response.body.decode()

    assert response.status_code == 200
    assert "<h1>Experiment</h1>" in body
    assert 'data-file-load-form' in body
    assert 'data-start-form' in body
    assert 'data-abort' in body
    assert 'data-results-panel' in body
    assert '<script src="/vendor/plotly.min.js" defer></script>' in body
    assert any(getattr(route, "path", None) == "/experiment" for route in app.routes)


def test_load_endpoint_validates_and_summarizes_definition():
    payload = load_experiment(
        _ExperimentLoadRequest(
            definition=experiment_definition(),
            filename="experiment.json",
        )
    )

    assert payload["state"] == "ready"
    assert payload["source_name"] == "experiment.json"
    assert payload["experiment"]["short_description"] == "web-test"
    assert payload["experiment"]["total_points"] == 3
    assert payload["experiment"]["cuts"][0]["point_count"] == 3


def test_load_endpoint_rejects_output_outside_experiments_folder():
    with pytest.raises(HTTPException) as exc_info:
        load_experiment(
            _ExperimentLoadRequest(
                definition=experiment_definition(relative_folder_path="../outside"),
                filename="unsafe.json",
            )
        )

    assert exc_info.value.status_code == 400
    assert "inside the experiments folder" in exc_info.value.detail


def test_available_definitions_and_server_load(tmp_path):
    root = tmp_path / "experiments"
    definition_path = root / "saved" / "metadata.json"
    definition_path.parent.mkdir(parents=True)
    definition = experiment_definition(relative_folder_path="saved")
    definition_path.write_text(experiment.ExperimentParameters(**definition).model_dump_json())
    service = ExperimentWebService(
        experiments_root=root,
        turntable_provider=lambda: None,
    )

    assert service.available_definitions() == [{"path": "saved/metadata.json", "name": "web-test"}]
    payload = service.load_server_definition("saved/metadata.json")

    assert payload["state"] == "ready"
    assert payload["source_name"] == "saved/metadata.json"


def test_sample_results_are_returned_as_normalized_polar_cuts():
    service = ExperimentWebService(
        experiments_root=Path("experiments").resolve(),
        turntable_provider=lambda: None,
    )
    loaded = service.load_server_definition("sample/parameters.json")

    assert loaded["results"]["available"] is True
    payload = service.results_payload()
    cuts = {cut["id"]: cut for cut in payload["cuts"]}
    assert set(cuts) == {"horizontal", "vertical"}
    assert len(cuts["horizontal"]["angles"]) == 21
    assert len(cuts["vertical"]["angles"]) == 11
    assert cuts["horizontal"]["angles"][0] == pytest.approx(-49.89)
    assert cuts["vertical"]["angles"][-1] == pytest.approx(24.9, abs=0.01)
    assert max(cuts["horizontal"]["peak"]["normalized_db"]) == 0
    assert max(cuts["vertical"]["center"]["normalized_db"]) == 0
    assert cuts["horizontal"]["peak"]["absolute_dbm"][0] == pytest.approx(-119)


class FakeExperimentTurntable:
    def __init__(self):
        self.commands = []
        self.position = turntable2.PanTilt(0, 0)

    def set_position(self, *, pan, tilt, timeout=5.0):
        self.commands.append(("set", pan, tilt, timeout))
        self.position = turntable2.PanTilt(pan, tilt)

    def move_to(self, *, pan, tilt, move_timeout=120.0):
        self.commands.append((pan, tilt, move_timeout))
        self.position = turntable2.PanTilt(pan, tilt)

    def abort(self):
        pass

    def get_complete_state(self):
        return SimpleNamespace(
            state=turntable2.TurntableState.STOPPED,
            activity=turntable2.TurntableActivity.IDLE,
            corrected_position=self.position,
            queued_command_count=0,
            last_error=None,
            has_been_set=True,
        )


class FakeSpectrumAnalyzer:
    def get_center_frequency_amplitude(self):
        return -42

    def get_center_frequency(self):
        return 1_000

    def get_peak_frequency_and_amplitude(self):
        return 1_001, -40


def test_experiment_point_uses_turntable2_pan_tilt_and_observed_position(tmp_path):
    parameters = experiment.ExperimentParameters(
        short_description="point",
        relative_folder_path=tmp_path,
        neutral_elevation=5,
    )
    runner = experiment.Experiment(parameters=parameters)
    runner.turntable = FakeExperimentTurntable()
    runner.spec_an = FakeSpectrumAnalyzer()
    runner.results = experiment.ExperimentResults()
    runner.cancel_event = threading.Event()
    runner.progress_callback = None
    point = Coordinate.from_absolute_turntable(azimuth=12, elevation=-7, neutral_elevation=5)

    runner._run_experiment_at_point(point=point, cut_id="cut", point_index=1)

    assert runner.turntable.commands == [(12, -7, 120.0)]
    assert runner.results.datapoints[0].actual_coordinate.absolute_turntable_azimuth == 12
    assert runner.results.datapoints[0].actual_coordinate.absolute_turntable_elevation == -7
    assert parameters.raw_data_csv_path.is_file()


def test_background_service_reports_progress_and_completion():
    finished = threading.Event()
    turntable = FakeExperimentTurntable()

    class FakeRunner:
        def __init__(self, *, parameters):
            self.parameters = parameters

        def run(self, **options):
            options["progress_callback"]({"completed_points": 3, "total_points": 3})
            finished.set()

    service = ExperimentWebService(
        turntable_provider=lambda: turntable,
        experiment_factory=FakeRunner,
    )
    service.load_definition(experiment_definition())
    service.start()

    assert finished.wait(timeout=1)
    assert service._thread is not None
    service._thread.join(timeout=1)
    payload = service.snapshot()
    assert payload["state"] == "completed"
    assert payload["progress"]["completed_points"] == 3
    assert payload["finished_at"] is not None


def test_background_service_aborts_cooperatively():
    started = threading.Event()
    finished = threading.Event()
    turntable = FakeExperimentTurntable()

    class CancellingRunner:
        def __init__(self, *, parameters):
            self.parameters = parameters

        def run(self, **options):
            started.set()
            options["cancel_event"].wait(timeout=1)
            finished.set()
            raise experiment.ExperimentCancelled()

    service = ExperimentWebService(
        turntable_provider=lambda: turntable,
        experiment_factory=CancellingRunner,
    )
    service.load_definition(experiment_definition())
    service.start()
    assert started.wait(timeout=1)
    service.abort()

    assert finished.wait(timeout=1)
    assert service._thread is not None
    service._thread.join(timeout=1)
    assert service.snapshot()["state"] == "cancelled"


def test_experiment_script_loads_json_and_polls_status():
    script = (WEB_ROOT / "static" / "experiment.js").read_text()

    assert 'requestJson("/experiment/load"' in script
    assert 'requestJson("/experiment/start"' in script
    assert 'requestJson("/experiment/abort"' in script
    assert 'requestJson("/experiment/results"' in script
    assert 'type: "scatterpolar"' in script
    assert 'window.setInterval(refreshStatus, 1000)' in script

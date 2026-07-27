import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
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
from msu_anechoic.web.app import experiment_graphs
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
    assert 'href="/experiment/graphs"' in body
    assert 'name="output_mode" value="continue"' in body
    assert "Overall points visited" in body
    assert "Overall cuts" in body
    assert "Points within current cut" in body
    assert any(getattr(route, "path", None) == "/experiment" for route in app.routes)

    graph_response = experiment_graphs(page_request("/experiment/graphs"))
    graph_body = graph_response.body.decode()
    assert graph_response.status_code == 200
    assert "<h1>Experiment Graphs</h1>" in graph_body
    assert "Configure graphs" in graph_body
    assert "Configure Graphs" in graph_body
    assert 'class="experiment-graphs-page"' in graph_body
    assert "data-graph-grid" in graph_body
    assert "data-graph-settings-overlay" in graph_body
    assert "data-hpbw-enabled" in graph_body
    graph_styles = (WEB_ROOT / "static" / "experiment.css").read_text()
    assert ".experiment-graphs-page main" in graph_styles
    assert "max-width: none" in graph_styles
    assert "repeat(auto-fit" in graph_styles


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
    assert payload["experiment"]["travel_seconds"] > 0
    assert payload["experiment"]["cuts"][0]["travel_seconds"] > 0
    assert payload["experiment"]["heatmap_bin_sizes"] == {
        "horizontal_degrees": 30,
        "vertical_degrees": 3,
    }


def test_measurement_plan_travel_connects_cuts_and_returns_home():
    cuts = {
        "first": experiment.CutDefinition(
            direction="horizontal",
            start_angle=-10,
            end_angle=10,
            step_size=10,
            fixed_angle=0,
        ),
        "second": experiment.CutDefinition(
            direction="vertical",
            start_angle=-5,
            end_angle=5,
            step_size=5,
            fixed_angle=20,
        ),
    }

    estimates = experiment.measurement_plan_estimates(
        cuts,
    )

    first, second = estimates["cuts"]
    transition = experiment.estimate_move_time((10, 0), (20, -5))
    assert second["travel_seconds"] >= transition
    assert estimates["return_home_seconds"] == pytest.approx(
        experiment.estimate_move_time((20, 5), (0, 0))
    )
    assert estimates["travel_seconds"] == pytest.approx(
        first["travel_seconds"]
        + second["travel_seconds"]
        + estimates["return_home_seconds"]
    )


def test_heatmap_bins_target_three_points_and_round_to_whole_degrees():
    payload = load_experiment(
        _ExperimentLoadRequest(
            definition=experiment_definition(
                cuts={
                    "horizontal": {
                        "direction": "horizontal",
                        "start_angle": -20,
                        "end_angle": 20,
                        "step_size": 2.297,
                        "fixed_angle": 0,
                    },
                    "vertical": {
                        "direction": "vertical",
                        "start_angle": -20,
                        "end_angle": 20,
                        "step_size": 1.8,
                        "fixed_angle": 0,
                    },
                }
            ),
            filename="bins.json",
        )
    )

    assert payload["experiment"]["heatmap_bin_sizes"] == {
        "horizontal_degrees": 7,
        "vertical_degrees": 5,
    }


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
    definition = experiment_definition(relative_folder_path="experiments/wrong-folder")
    definition_path.write_text(experiment.ExperimentParameters(**definition).model_dump_json())
    service = ExperimentWebService(
        experiments_root=root,
        turntable_provider=lambda: None,
    )

    assert service.available_definitions() == [{"path": "saved/metadata.json", "name": "web-test"}]
    payload = service.load_server_definition("saved/metadata.json")

    assert payload["state"] == "ready"
    assert payload["source_name"] == "saved/metadata.json"
    assert Path(payload["experiment"]["output_folder"]) == definition_path.parent


def test_results_are_returned_in_both_coordinate_frames(tmp_path):
    root = tmp_path / "experiments"
    folder = root / "sample"
    folder.mkdir(parents=True)
    (folder / "parameters.json").write_text(
        json.dumps(
            experiment_definition(
                relative_folder_path=None,
                cuts={
                    "horizontal": {
                        "direction": "horizontal",
                        "start_angle": -10,
                        "end_angle": 10,
                        "step_size": 10,
                        "fixed_angle": 0,
                    },
                    "vertical": {
                        "direction": "vertical",
                        "start_angle": -10,
                        "end_angle": 10,
                        "step_size": 10,
                        "fixed_angle": 0,
                    },
                },
            )
        )
    )
    csv_path = folder / "raw_data" / "data.csv"
    csv_path.parent.mkdir()
    csv_path.write_text(
        "point_index,timestamp,cut_id,actual_pan,actual_tilt,center_amplitude,peak_amplitude,center_frequency,peak_frequency\n"
        "1,2026-01-01T00:00:00Z,horizontal,-10,0,-42,-40,1000,1001\n"
        "2,2026-01-01T00:00:01Z,horizontal,0,0,-39,-38,1000,1002\n"
        "4,2026-01-01T00:00:02Z,vertical,0,-10,-43,-41,1000,1003\n"
        "5,2026-01-01T00:00:03Z,vertical,0,0,-40,-39,1000,1004\n"
    )
    service = ExperimentWebService(
        experiments_root=root,
        turntable_provider=lambda: None,
    )
    loaded = service.load_server_definition("sample/parameters.json")

    assert loaded["results"]["available"] is True
    payload = service.results_payload()
    plan = service.plan_payload()
    cuts = {cut["id"]: cut for cut in payload["cuts"]}
    plan_cuts = {cut["id"]: cut for cut in plan["cuts"]}
    assert set(cuts) == {"horizontal", "vertical"}
    assert set(plan_cuts) == {"horizontal", "vertical"}
    assert cuts["horizontal"]["pan_angles"] == [-10.0, 0.0]
    assert cuts["vertical"]["tilt_angles"] == [-10.0, 0.0]
    assert cuts["horizontal"]["azimuth_angles"][0] == pytest.approx(-10)
    assert cuts["vertical"]["elevation_angles"][0] == pytest.approx(-10)
    assert len(plan_cuts["horizontal"]["points"]) == 3
    assert len(plan_cuts["vertical"]["points"]) == 3
    assert plan_cuts["horizontal"]["points"][0] == {
        "cut_id": "horizontal",
        "point_index": 1,
        "point_in_cut": 1,
        "pan": -10,
        "tilt": 0,
        "azimuth": -10,
        "elevation": 0,
    }
    assert plan_cuts["vertical"]["points"][0]["point_index"] == 4
    assert plan_cuts["vertical"]["points"][0]["pan"] == 0
    assert plan_cuts["vertical"]["points"][0]["tilt"] == -10
    assert max(cuts["horizontal"]["peak"]["normalized_db"]) == 0
    assert max(cuts["vertical"]["center"]["normalized_db"]) == 0
    assert cuts["horizontal"]["peak"]["absolute_dbm"][0] == pytest.approx(-40)
    assert payload["visited_points"][0] == {"cut_id": "horizontal", "point_index": 1}
    assert payload["visited_points"][-1] == {"cut_id": "vertical", "point_index": 5}
    assert payload["heatmap_bin_sizes"] == {
        "horizontal_degrees": 30,
        "vertical_degrees": 30,
    }
    assert payload["rows"][0]["pan"] == -10
    assert payload["rows"][0]["peak_amplitude"] == -40
    assert payload["rows"][0]["timestamp"] == "2026-01-01T00:00:00Z"
    assert payload["rows"][0]["peak_frequency"] == 1001


def test_server_load_uses_selected_folder_for_results_and_output(tmp_path):
    root = tmp_path / "experiments"
    definition = experiment_definition(
        short_description="sample",
        relative_folder_path=None,
    )
    for folder_name in ("sample", "sample2"):
        folder = root / folder_name
        folder.mkdir(parents=True)
        (folder / "parameters.json").write_text(json.dumps(definition))
    sample_csv = root / "sample" / "raw_data" / "data.csv"
    sample_csv.parent.mkdir()
    sample_csv.write_text("point_index,cut_id,peak_amplitude\n1,AZIMUTH,-40\n")

    service = ExperimentWebService(
        experiments_root=root,
        turntable_provider=lambda: None,
    )
    sample = service.load_server_definition("sample/parameters.json")
    assert sample["results"]["available"] is True
    assert Path(sample["results"]["path"]) == sample_csv

    sample2 = service.load_server_definition("sample2/parameters.json")
    assert sample2["source_name"] == "sample2/parameters.json"
    assert Path(sample2["experiment"]["output_folder"]) == root / "sample2"
    assert sample2["results"] == {
        "available": False,
        "path": str(root / "sample2" / "raw_data" / "data.csv"),
        "version": None,
    }
    with pytest.raises(RuntimeError, match="does not have result data"):
        service.results_payload()


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
    )
    runner = experiment.Experiment(parameters=parameters)
    runner.turntable = FakeExperimentTurntable()
    runner.spec_an = FakeSpectrumAnalyzer()
    runner.results = experiment.ExperimentResults()
    runner.cancel_event = threading.Event()
    runner.progress_callback = None
    point = Coordinate.from_turntable(azimuth=12, elevation=-7)

    runner._run_experiment_at_point(point=point, cut_id="cut", point_index=1)

    assert runner.turntable.commands == [(12, -7, 120.0)]
    assert runner.results.datapoints[0].actual_coordinate.pan == 12
    assert runner.results.datapoints[0].actual_coordinate.tilt == -7
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


def test_continue_mode_loads_existing_points_and_appends(tmp_path):
    finished = threading.Event()
    captured_options = {}
    turntable = FakeExperimentTurntable()
    root = tmp_path / "experiments"

    class FakeRunner:
        def __init__(self, *, parameters):
            self.parameters = parameters

        def run(self, **options):
            captured_options.update(options)
            finished.set()

    service = ExperimentWebService(
        experiments_root=root,
        turntable_provider=lambda: turntable,
        experiment_factory=FakeRunner,
    )
    payload = service.load_definition(
        experiment_definition(relative_folder_path="resume"),
    )
    csv_path = Path(payload["experiment"]["output_folder"]) / "raw_data" / "data.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(
        "point_index,cut_id,peak_amplitude\n"
        "1,AZIMUTH,-40\n"
        "3,AZIMUTH,-41\n"
    )

    service.start(output_mode="continue")

    assert finished.wait(timeout=1)
    assert service._thread is not None
    service._thread.join(timeout=1)
    existing_data = captured_options["existing_data"]
    assert list(zip(existing_data["cut_id"], existing_data["point_index"])) == [
        ("AZIMUTH", 1),
        ("AZIMUTH", 3),
    ]
    assert captured_options["append_csv"] is True
    assert captured_options["overwrite_csv"] is False


def test_continue_mode_requires_a_compatible_existing_csv(tmp_path):
    service = ExperimentWebService(
        experiments_root=tmp_path / "experiments",
        turntable_provider=lambda: FakeExperimentTurntable(),
    )
    service.load_definition(experiment_definition(relative_folder_path="resume"))

    with pytest.raises(ValueError, match="no existing CSV"):
        service.start(output_mode="continue")


def test_experiment_continue_skips_existing_cut_point_pairs(monkeypatch, tmp_path):
    class RecordingExperiment(experiment.Experiment):
        def _run_experiment_at_point(self, **options):
            self.recorded_point_indexes.append(options["point_index"])

        def _move_turntable_and_wait(self, *, pan, tilt, timeout=120.0):
            return turntable2.PanTilt(pan, tilt)

    parameters = experiment.ExperimentParameters(
        short_description="resume",
        relative_folder_path=tmp_path,
        cuts={
            "AZIMUTH": experiment.CutDefinition(
                direction="horizontal",
                start_angle=-10,
                end_angle=10,
                step_size=10,
                fixed_angle=0,
            )
        },
    )
    runner = RecordingExperiment(parameters=parameters)
    runner.recorded_point_indexes = []
    runner.assume_ready = True
    runner.cancel_event = threading.Event()
    progress_updates = []
    runner.progress_callback = progress_updates.append
    runner.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(experiment, "say", lambda *args, **kwargs: None)
    existing_data = pd.DataFrame(
        {
            "cut_id": ["AZIMUTH", "AZIMUTH"],
            "point_index": [1, 3],
        }
    )

    runner._run_cuts_experiment(existing_data=existing_data)

    assert runner.recorded_point_indexes == [2]
    assert any(
        update.get("point_index") == 2
        and update.get("target") == {"pan": 0.0, "tilt": 0.0}
        for update in progress_updates
    )


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
    graph_script = (WEB_ROOT / "static" / "experiment-graphs.js").read_text()

    assert 'requestJson("/experiment/load"' in script
    assert 'requestJson("/experiment/start"' in script
    assert 'requestJson("/experiment/abort"' in script
    assert 'window.setInterval(refreshStatus, 1000)' in script
    assert 'requestJson("/experiment/results"' in graph_script
    assert 'requestJson("/experiment/plan"' in graph_script
    assert 'requestJson("/turntable/status?max_time=1&max_points=1"' in graph_script
    assert 'type: "scatterpolar"' in graph_script
    assert 'name: "Travelling to"' in graph_script
    assert 'name: "Actual position"' in graph_script
    assert 'name: "Pending points"' in graph_script
    assert 'name: "Visited points"' in graph_script
    assert 'pan_angles' in graph_script
    assert 'azimuth_angles' in graph_script
    assert '"power-time"' in graph_script
    assert '"freq-time"' in graph_script
    assert '"az-el-peak-heat"' in graph_script
    assert '"pan-tilt-center-heat"' in graph_script
    assert "computeHpbw" in graph_script
    assert "hpbwTraces" in graph_script
    assert "GRAPH_CONFIG_KEY" in graph_script
    assert "updateConfigFromItems" in graph_script
    assert graph_script.count("window.requestAnimationFrame") >= 2
    assert "width: plot.clientWidth" in graph_script

"""Web-facing experiment loading and background execution."""

from __future__ import annotations

import csv
import datetime
import math
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from typing import Literal

import pandas as pd

from msu_anechoic import experiment
from msu_anechoic import turntable2
from msu_anechoic.web.turntable import TurntableLike
from msu_anechoic.web.turntable import turntable_service

UTC = datetime.timezone.utc
OutputMode = Literal["new", "continue", "append", "overwrite"]


class ExperimentWebService:
    """Own one loaded experiment and its background execution state."""

    def __init__(
        self,
        *,
        turntable_provider: Callable[[], TurntableLike] = turntable_service.require_connected,
        experiment_factory: Callable[..., experiment.Experiment] = experiment.Experiment,
        experiments_root: Path | None = None,
    ) -> None:
        self._turntable_provider = turntable_provider
        self._experiment_factory = experiment_factory
        self._experiments_root = (experiments_root or experiment.EXPERIMENTS_FOLDER_PATH).resolve()
        self._parameters: experiment.ExperimentParameters | None = None
        self._definition_version = 0
        self._source_name: str | None = None
        self._state = "empty"
        self._error: str | None = None
        self._progress: dict[str, Any] = {}
        self._started_at: datetime.datetime | None = None
        self._finished_at: datetime.datetime | None = None
        self._cancel_event: threading.Event | None = None
        self._active_turntable: TurntableLike | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def load_definition(self, definition: dict[str, Any], *, source_name: str | None = None) -> dict[str, Any]:
        parameters = experiment.ExperimentParameters.model_validate(definition)
        self._validate_definition(parameters)
        self._validate_output_path(parameters)
        with self._lock:
            if self._state in {"running", "cancelling"}:
                raise RuntimeError("Cannot load another definition while an experiment is running")
            self._parameters = parameters
            self._definition_version += 1
            self._source_name = source_name
            self._state = "ready"
            self._error = None
            self._progress = {}
            self._started_at = None
            self._finished_at = None
        return self.snapshot()

    def load_server_definition(self, relative_path: str) -> dict[str, Any]:
        path = self._resolve_definition_path(relative_path)
        parameters = experiment.ExperimentParameters.model_validate_json(path.read_text(encoding="utf-8"))
        definition = parameters.model_dump(mode="json")
        definition["relative_folder_path"] = str(path.parent.relative_to(self._experiments_root))
        return self.load_definition(
            definition,
            source_name=str(path.relative_to(self._experiments_root)),
        )

    def available_definitions(self) -> list[dict[str, str]]:
        definitions: list[dict[str, str]] = []
        if not self._experiments_root.exists():
            return definitions
        candidates = {
            *self._experiments_root.rglob("metadata.json"),
            *self._experiments_root.rglob("parameters.json"),
        }
        for path in sorted(candidates):
            try:
                parameters = experiment.ExperimentParameters.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            definitions.append(
                {
                    "path": str(path.relative_to(self._experiments_root)),
                    "name": parameters.short_description,
                }
            )
        return definitions

    def start(self, *, output_mode: OutputMode = "new") -> dict[str, Any]:
        if output_mode not in {"new", "continue", "append", "overwrite"}:
            raise ValueError(f"Unsupported output mode: {output_mode}")
        with self._lock:
            if self._state in {"running", "cancelling"}:
                raise RuntimeError("An experiment is already running")
            if self._parameters is None:
                raise RuntimeError("Load an experiment definition before starting")
            self._validate_for_run(self._parameters)
            existing_data = (
                _load_existing_data(self._parameters.raw_data_csv_path)
                if output_mode == "continue"
                else None
            )
            turntable = self._turntable_provider()
            state = turntable.get_complete_state()
            if not state.has_been_set:
                raise turntable2.TurntableError(
                    "Set the turntable position on the Turntable page before starting the experiment"
                )

            parameters = self._parameters.model_copy(deep=True)
            cancel_event = threading.Event()
            self._cancel_event = cancel_event
            self._active_turntable = turntable
            self._state = "running"
            self._error = None
            self._progress = {
                "completed_points": 0,
                "total_points": _total_points(parameters),
            }
            self._started_at = datetime.datetime.now(tz=UTC)
            self._finished_at = None
            self._thread = threading.Thread(
                target=self._run,
                kwargs={
                    "parameters": parameters,
                    "turntable": turntable,
                    "cancel_event": cancel_event,
                    "output_mode": output_mode,
                    "existing_data": existing_data,
                },
                name="anechoic-experiment",
                daemon=True,
            )
            self._thread.start()
        return self.snapshot()

    def abort(self) -> dict[str, Any]:
        with self._lock:
            if self._state not in {"running", "cancelling"}:
                raise RuntimeError("No experiment is running")
            self._state = "cancelling"
            assert self._cancel_event is not None
            self._cancel_event.set()
            turntable = self._active_turntable
        if turntable is not None:
            turntable.abort()
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            parameters = self._parameters
            return {
                "state": self._state,
                "loaded": parameters is not None,
                "can_start": parameters is not None and self._state not in {"running", "cancelling"},
                "can_abort": self._state in {"running", "cancelling"},
                "source_name": self._source_name,
                "experiment": _parameters_summary(parameters) if parameters is not None else None,
                "plan": {
                    "available": parameters is not None,
                    "version": self._definition_version if parameters is not None else None,
                },
                "results": _results_summary(parameters),
                "progress": dict(self._progress),
                "error": self._error,
                "started_at": self._started_at.isoformat() if self._started_at is not None else None,
                "finished_at": self._finished_at.isoformat() if self._finished_at is not None else None,
            }

    def plan_payload(self) -> dict[str, Any]:
        with self._lock:
            parameters = self._parameters.model_copy(deep=True) if self._parameters is not None else None
            version = self._definition_version
        if parameters is None:
            raise RuntimeError("Load an experiment definition before viewing its path")
        return {
            "version": version,
            "cuts": _plan_cuts(parameters),
        }

    def results_payload(self) -> dict[str, Any]:
        with self._lock:
            parameters = self._parameters.model_copy(deep=True) if self._parameters is not None else None
        if parameters is None:
            raise RuntimeError("Load an experiment definition before viewing results")
        csv_path = parameters.raw_data_csv_path
        if not csv_path.is_file():
            raise RuntimeError("This experiment does not have result data yet")
        return _polar_results(parameters, csv_path)

    def reset_for_tests(self) -> None:
        """Reset idle service state without touching hardware."""
        with self._lock:
            if self._state in {"running", "cancelling"}:
                raise RuntimeError("Cannot reset while an experiment is running")
            self._parameters = None
            self._definition_version = 0
            self._source_name = None
            self._state = "empty"
            self._error = None
            self._progress = {}
            self._started_at = None
            self._finished_at = None
            self._cancel_event = None
            self._active_turntable = None
            self._thread = None

    def _run(
        self,
        *,
        parameters: experiment.ExperimentParameters,
        turntable: TurntableLike,
        cancel_event: threading.Event,
        output_mode: OutputMode,
        existing_data: pd.DataFrame | None,
    ) -> None:
        try:
            runner = self._experiment_factory(parameters=parameters)
            runner.run(
                turntable=turntable,
                assume_ready=True,
                progress_callback=self._update_progress,
                cancel_event=cancel_event,
                existing_data=existing_data,
                overwrite_csv=output_mode == "overwrite",
                append_csv=output_mode in {"continue", "append"},
            )
        except experiment.ExperimentCancelled:
            with self._lock:
                self._state = "cancelled"
                self._error = None
        except Exception as exc:
            with self._lock:
                self._state = "failed"
                self._error = f"{type(exc).__name__}: {exc}"
        else:
            with self._lock:
                self._state = "completed"
                self._error = None
        finally:
            with self._lock:
                self._finished_at = datetime.datetime.now(tz=UTC)
                self._active_turntable = None
                self._cancel_event = None

    def _update_progress(self, updates: dict[str, Any]) -> None:
        with self._lock:
            self._progress.update(updates)

    def _resolve_definition_path(self, relative_path: str) -> Path:
        candidate = (self._experiments_root / relative_path).resolve()
        if not candidate.is_relative_to(self._experiments_root):
            raise ValueError("Experiment definition must be inside the experiments folder")
        if candidate.name not in {"metadata.json", "parameters.json"}:
            raise ValueError("Experiment definition must be named metadata.json or parameters.json")
        if not candidate.is_file():
            raise ValueError("Experiment definition does not exist")
        return candidate

    def _validate_output_path(self, parameters: experiment.ExperimentParameters) -> None:
        output_path = parameters.relative_folder_path
        assert output_path is not None
        if output_path.is_absolute():
            raise ValueError("Experiment output folder must be relative")
        resolved = output_path.resolve()
        if not resolved.is_relative_to(self._experiments_root):
            resolved = (self._experiments_root / output_path).resolve()
        if not resolved.is_relative_to(self._experiments_root):
            raise ValueError("Experiment output folder must be inside the experiments folder")
        try:
            parameters.relative_folder_path = resolved.relative_to(Path.cwd())
        except ValueError:
            parameters.relative_folder_path = resolved

    @staticmethod
    def _validate_definition(parameters: experiment.ExperimentParameters) -> None:
        if parameters.cuts:
            invalid_steps = [str(cut_id) for cut_id, cut in parameters.cuts.items() if cut.step_size <= 0]
            if invalid_steps:
                raise ValueError(f"Cut step_size must be greater than zero: {', '.join(invalid_steps)}")

    @staticmethod
    def _validate_for_run(parameters: experiment.ExperimentParameters) -> None:
        if not parameters.cuts:
            raise ValueError("The loaded experiment must define at least one cut")
        missing_neutral = [
            cut_id
            for cut_id, cut in parameters.cuts.items()
            if cut.neutral_elevation is None and parameters.neutral_elevation is None
        ]
        if missing_neutral:
            raise ValueError(f"Set neutral_elevation for cuts: {', '.join(map(str, missing_neutral))}")


def _total_points(parameters: experiment.ExperimentParameters) -> int:
    if not parameters.cuts:
        return 0
    return sum(_cut_point_count(cut) for cut in parameters.cuts.values())


def _cut_point_count(cut: experiment.CutDefinition) -> int:
    distance = abs(cut.end_angle - cut.start_angle)
    return math.ceil(distance / cut.step_size + 0.5 - 1e-12)


def _parameters_summary(parameters: experiment.ExperimentParameters) -> dict[str, Any]:
    cuts = []
    if parameters.cuts:
        for cut_id, cut in parameters.cuts.items():
            cuts.append(
                {
                    "id": str(cut_id),
                    "direction": cut.direction,
                    "fixed_angle": cut.fixed_angle,
                    "start_angle": cut.start_angle,
                    "end_angle": cut.end_angle,
                    "step_size": cut.step_size,
                    "point_count": _cut_point_count(cut),
                }
            )
    return {
        "short_description": parameters.short_description,
        "long_description": parameters.long_description,
        "output_folder": str(parameters.relative_folder_path),
        "neutral_elevation": parameters.neutral_elevation,
        "cuts": cuts,
        "total_points": _total_points(parameters),
        "collect_center_frequency_data": parameters.collect_center_frequency_data,
        "collect_peak_data": parameters.collect_peak_data,
        "collect_trace_data": parameters.collect_trace_data,
        "sig_gen_config": (
            parameters.sig_gen_config.model_dump(mode="json") if parameters.sig_gen_config is not None else None
        ),
        "polarization_config": (
            parameters.polarization_config.model_dump(mode="json")
            if parameters.polarization_config is not None
            else None
        ),
        "spec_an_config": (
            parameters.spec_an_config.model_dump(mode="json") if parameters.spec_an_config is not None else None
        ),
    }


def _plan_cuts(parameters: experiment.ExperimentParameters) -> list[dict[str, Any]]:
    plan_cuts = []
    point_index = 0
    for cut_id, cut in (parameters.cuts or {}).items():
        neutral_elevation = (
            cut.neutral_elevation
            if cut.neutral_elevation is not None
            else parameters.neutral_elevation
        )
        points = []
        if neutral_elevation is not None:
            resolved_cut = cut.model_copy(update={"neutral_elevation": neutral_elevation})
            for point_in_cut, coordinate in enumerate(resolved_cut.coordinates, start=1):
                point_index += 1
                points.append(
                    {
                        "cut_id": str(cut_id),
                        "point_index": point_index,
                        "point_in_cut": point_in_cut,
                        "pan": coordinate.absolute_turntable_azimuth,
                        "tilt": coordinate.absolute_turntable_elevation,
                    }
                )
        plan_cuts.append(
            {
                "id": str(cut_id),
                "direction": cut.direction,
                "points": points,
            }
        )
    return plan_cuts


def _results_summary(parameters: experiment.ExperimentParameters | None) -> dict[str, Any]:
    if parameters is None:
        return {"available": False, "path": None, "version": None}
    csv_path = parameters.raw_data_csv_path
    try:
        stat = csv_path.stat()
    except OSError:
        return {
            "available": False,
            "path": str(csv_path),
            "version": None,
        }
    return {
        "available": csv_path.is_file(),
        "path": str(csv_path),
        "version": f"{stat.st_mtime_ns}:{stat.st_size}",
    }


def _load_existing_data(csv_path: Path) -> pd.DataFrame:
    if not csv_path.is_file():
        raise ValueError("There is no existing CSV to continue")
    try:
        data = pd.read_csv(csv_path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise ValueError(f"Could not read existing CSV: {exc}") from exc
    required_columns = {"cut_id", "point_index"}
    missing_columns = sorted(required_columns - set(data.columns))
    if missing_columns:
        raise ValueError(
            f"Existing CSV cannot be continued because it is missing: {', '.join(missing_columns)}"
        )
    data["cut_id"] = data["cut_id"].map(str)
    data["point_index"] = pd.to_numeric(data["point_index"], errors="coerce")
    return data


def _polar_results(
    parameters: experiment.ExperimentParameters,
    csv_path: Path,
) -> dict[str, Any]:
    cut_definitions = parameters.cuts or {}
    cuts: dict[str, dict[str, Any]] = {}
    visited_points: set[tuple[str, int]] = set()
    with csv_path.open("r", encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            cut_id = str(row.get("cut_id") or "Unlabeled")
            point_index = _finite_float(row.get("point_index"))
            if point_index is not None and point_index.is_integer():
                visited_points.add((cut_id, int(point_index)))
            definition = cut_definitions.get(cut_id)
            direction = definition.direction if definition is not None else _infer_cut_direction(row)
            angle = _cut_angle(row, direction)
            center_amplitude = _finite_float(row.get("center_amplitude"))
            peak_amplitude = _finite_float(row.get("peak_amplitude"))
            if angle is None or (center_amplitude is None and peak_amplitude is None):
                continue
            cut = cuts.setdefault(
                cut_id,
                {
                    "id": cut_id,
                    "direction": direction,
                    "fixed_angle": definition.fixed_angle if definition is not None else None,
                    "angles": [],
                    "point_indexes": [],
                    "center_amplitudes_dbm": [],
                    "peak_amplitudes_dbm": [],
                },
            )
            cut["angles"].append(angle)
            cut["point_indexes"].append(_finite_float(row.get("point_index")))
            cut["center_amplitudes_dbm"].append(center_amplitude)
            cut["peak_amplitudes_dbm"].append(peak_amplitude)

    payload_cuts = []
    for cut in cuts.values():
        center_amplitudes = cut.pop("center_amplitudes_dbm")
        peak_amplitudes = cut.pop("peak_amplitudes_dbm")
        payload_cuts.append(
            {
                **cut,
                "center": {
                    "absolute_dbm": center_amplitudes,
                    "normalized_db": _normalize_db(center_amplitudes),
                },
                "peak": {
                    "absolute_dbm": peak_amplitudes,
                    "normalized_db": _normalize_db(peak_amplitudes),
                },
            }
        )

    stat = csv_path.stat()
    return {
        "source_path": str(csv_path),
        "version": f"{stat.st_mtime_ns}:{stat.st_size}",
        "visited_points": [
            {"cut_id": cut_id, "point_index": point_index}
            for cut_id, point_index in sorted(visited_points, key=lambda item: item[1])
        ],
        "cuts": payload_cuts,
    }


def _infer_cut_direction(row: dict[str, str | None]) -> str:
    azimuth = _finite_float(row.get("commanded_azimuth"))
    elevation = _finite_float(row.get("commanded_elevation"))
    if azimuth is not None and elevation is not None and abs(azimuth) >= abs(elevation):
        return "horizontal"
    return "vertical"


def _cut_angle(row: dict[str, str | None], direction: str) -> float | None:
    if direction == "horizontal":
        actual = _finite_float(row.get("actual_azimuth"))
        return actual if actual is not None else _finite_float(row.get("commanded_azimuth"))
    actual = _finite_float(row.get("actual_elevation"))
    return actual if actual is not None else _finite_float(row.get("commanded_elevation"))


def _finite_float(value: str | None) -> float | None:
    try:
        number = float(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and math.isfinite(number) else None


def _normalize_db(values: list[float | None]) -> list[float | None]:
    finite_values = [value for value in values if value is not None]
    if not finite_values:
        return [None] * len(values)
    maximum = max(finite_values)
    return [value - maximum if value is not None else None for value in values]


experiment_service = ExperimentWebService()

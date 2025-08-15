import csv
import datetime
from pathlib import Path
from typing import Any
from typing import Generator
from typing import Iterable
from typing import Literal

import numpy as np
import pandas as pd
import pydantic
from msu_ssc import path_util

# from msu_anechoic import AzElTurntable
from msu_anechoic.sound import say
from msu_anechoic.spec_an import SpectrumAnalyzerHP8563E
from msu_anechoic.turn_table import Turntable
from msu_anechoic.util.coordinate import Coordinate

EXPERIMENTS_FOLDER_PATH = Path("./experiments")


_MIN_TRAVEL_TIME_AZ = 1.0
_MIN_TRAVEL_TIME_EL = 1.8
_AVERAGE_TRAVEL_DEG_PER_SEC_AZ = 2.5
_AVERAGE_TRAVEL_DEG_PER_SEC_EL = 1.5
_PAUSE_TIME = 0.2
_PAUSE_TIME_TRACE = 1.0

def _estimate_time(angle: float, kind: Literal["horizontal", "vertical"], trace: bool) -> float:
    """Estimate the time it will take to move a specific angle."""
    if kind == "horizontal":
        travel_time = _MIN_TRAVEL_TIME_AZ + abs(angle) / _AVERAGE_TRAVEL_DEG_PER_SEC_AZ
    elif kind == "vertical":
        travel_time = _MIN_TRAVEL_TIME_EL + abs(angle) / _AVERAGE_TRAVEL_DEG_PER_SEC_EL
    else:
        raise ValueError(f"Invalid kind: {kind}. Must be 'horizontal' or 'vertical'.")
    pause_time = _PAUSE_TIME if trace else _PAUSE_TIME_TRACE
    total_time = travel_time + pause_time
    return total_time


class CutDefinition(pydantic.BaseModel):
    """The definition of a single cut, which is a bunch of points at a fixed tilt or pan"""

    direction: Literal["horizontal", "vertical"]
    start_angle: float
    """On the axis that is not fixed, the starting angle of the cut, in degrees"""
    end_angle: float
    """On the axis that is not fixed, the ending angle of the cut, in degrees"""
    step_size: float
    """On the axis that is not fixed, the step size of the cut, in degrees"""
    fixed_angle: float
    """On the axis that is fixed, the angle of the cut, in degrees"""
    reset_before: bool | None = None
    """Should the turntable reset before starting this cut?"""

    neutral_elevation: float | None = None

    def coordinates(self) -> list[Coordinate]:
        """Get the coordinates of this cut, as a list of `Coordinate` objects."""

        # Reverse the step size if the start angle is greater than the end angle
        step_size = self.step_size
        if self.start_angle > self.end_angle:
            step_size = -step_size
        moving_angles = np.arange(
            self.start_angle,
            self.end_angle + step_size / 2,
            step_size,
        )

        if self.neutral_elevation is None:
            raise ValueError("neutral_elevation must be set for CutDefinition")
        if self.direction == "horizontal":
            return [
                Coordinate.from_turntable(
                    azimuth=angle,
                    elevation=self.fixed_angle,
                    neutral_elevation=self.neutral_elevation,
                )
                for angle in moving_angles
            ]
        elif self.direction == "vertical":
            return [
                Coordinate.from_turntable(
                    azimuth=self.fixed_angle,
                    elevation=angle,
                    neutral_elevation=self.neutral_elevation,
                )
                for angle in moving_angles
            ]
        else:
            raise ValueError(f"Invalid direction: {self.direction}. Must be 'horizontal' or 'vertical'.")

    def rough_time_estimate(self, seconds_per_point: float = 5, *, trace: bool) -> float:
        """A VERY rough estimate of how long this cut will take. Only for ballparking. Doesn't include slew time."""
        return len(self.coordinates()) * _estimate_time(self.step_size, kind=self.direction, trace=False)

    def __len__(self) -> int:
        """The number of points in this cut"""
        return len(self.coordinates())


# class Grid(pydantic.BaseModel):
#     min_azimuth: float
#     max_azimuth: float
#     azimuth_step_size: float
#     min_elevation: float
#     max_elevation: float
#     elevation_step_size: float
#     orientation: Literal["horizontal", "vertical"]
#     kind: Literal["turntable", "antenna"] = "turntable"
#     neutral_elevation: float = 0.0

#     def elevations(self) -> list[float]:
#         return list(
#             np.arange(self.min_elevation, self.max_elevation + self.elevation_step_size / 2, self.elevation_step_size)
#         )

#     def azimuths(self) -> list[float]:
#         return list(np.arange(self.min_azimuth, self.max_azimuth + self.azimuth_step_size / 2, self.azimuth_step_size))

#     def cut_count(self) -> int:
#         return len(self.cut_angles())

#     def size_of_cut(self) -> int:
#         return len(self.cut_points(0))

#     def cut_angles(self) -> list[float]:
#         if self.orientation == "horizontal":
#             return list(self.elevations())
#         else:
#             return list(self.azimuths())

#     def cut_points(self, cut_angle: float, should_reverse: bool = False) -> list[float]:
#         within_cut_angles = self.azimuths() if self.orientation == "horizontal" else self.elevations()
#         if should_reverse:
#             within_cut_angles = reversed(within_cut_angles)

#         points = []

#         for within_cut_angle in within_cut_angles:
#             if self.orientation == "horizontal":
#                 points.append(
#                     Coordinate.from_turntable(
#                         azimuth=within_cut_angle,
#                         elevation=cut_angle,
#                         neutral_elevation=self.neutral_elevation,
#                     )
#                 )
#             else:
#                 points.append(
#                     Coordinate.from_turntable(
#                         azimuth=cut_angle,
#                         elevation=within_cut_angle,
#                         neutral_elevation=self.neutral_elevation,
#                     )
#                 )
#         return points

#     def cuts(self) -> Generator[list[Coordinate], None, None]:
#         should_reverse = False
#         for cut_angle in self.cut_angles():
#             yield list(self.cut_points(cut_angle, should_reverse=should_reverse))
#             should_reverse = not should_reverse

#     def __len__(self) -> int:
#         return len(self.cut_angles()) * len(self.cut_points(0))

#     def __iter__(self) -> Generator[Coordinate, None, None]:
#         for cut in self.cuts():
#             for point in cut:
#                 yield point

#     def rough_time_estimate(self, seconds_per_point: float = 5) -> float:
#         """A VERY rough estimate of how long this grid will take, based on the assumption that each point will take `seconds_per_point` seconds."""
#         return len(self) * seconds_per_point


class SpecAnConfig(pydantic.BaseModel):
    initial_center_frequency: float | None = None
    spans_when_searching: list[float] | None = None
    reference_level: float | None = None
    amplitude_units: str | None = None
    resolution_bandwidth: float | None = None
    video_bandwidth: float | None = None
    center_frequency: float | None = None
    minimum_frequency: float | None = None
    maximum_frequency: float | None = None
    span: float | None = None
    serial_number: str | None = None
    gpib_timeout_ms: int | None = None
    sweep_time: float | None = None

    def get_span(self) -> float | None:
        """The span of the spectrum analyzer, in Hz."""
        if self.span is not None:
            return self.span
        elif self.minimum_frequency is not None and self.maximum_frequency is not None:
            return self.maximum_frequency - self.minimum_frequency
        return None

    def apply_to(self, spec_an: SpectrumAnalyzerHP8563E) -> None:
        """Configure the spectrum analyzer with this configuration."""
        # Do amplitude things first
        if self.amplitude_units is not None:
            spec_an.set_amplitude_units(self.amplitude_units)
        if self.reference_level is not None:
            spec_an.set_reference_level(self.reference_level)

        # Set CF to:
        #   1. `center_frequency` if given
        #   2. `initial_center_frequency` if given
        #   3. Otherwise, take no action.
        center_frequency = None
        if self.center_frequency is not None:
            center_frequency = self.center_frequency
        elif self.initial_center_frequency is not None:
            center_frequency = self.initial_center_frequency
        if center_frequency is not None:
            spec_an.set_center_frequency(center_frequency)

        # Set spans
        # If max and min are given OR span is given, use those
        if self.get_span() is not None:
            spec_an.set_span(self.get_span())
        # Otherwise, if `spans_when_searching` is given, use that
        elif self.spans_when_searching is not None and center_frequency is not None:
            spec_an.move_center_to_peak(
                center_frequency=center_frequency,
                spans=self.spans_when_searching,
            )

        if self.resolution_bandwidth is not None:
            spec_an.set_resolution_bandwidth(self.resolution_bandwidth)
        if self.video_bandwidth is not None:
            spec_an.set_video_bandwidth(self.video_bandwidth)
        if self.sweep_time is not None:
            spec_an.set_sweep_time(self.sweep_time)

        if self.gpib_timeout_ms is not None:
            spec_an.set_gpib_timeout_ms(self.gpib_timeout_ms)

    @classmethod
    def from_spec_an(
        cls,
        spec_an: SpectrumAnalyzerHP8563E,
    ) -> "SpecAnConfig":
        """Create a `SpecAnConfig` object by querying a `SpectrumAnalyzerHP8563E` object."""
        spec_an.take_sweep()
        return cls(
            # initial_center_frequency=spec_an.get_center_frequency(),
            # spans_when_searching=spec_an.spans_when_searching,
            reference_level=spec_an.get_reference_level(),
            amplitude_units=spec_an.get_amplitude_units(),
            resolution_bandwidth=spec_an.get_resolution_bandwidth(),
            video_bandwidth=spec_an.get_video_bandwidth(),
            center_frequency=spec_an.get_center_frequency(),
            minimum_frequency=spec_an.get_lower_frequency(),
            maximum_frequency=spec_an.get_upper_frequency(),
            serial_number=spec_an.get_serial_number(),
            span=spec_an.get_span(),
            gpib_timeout_ms=spec_an.get_gpib_timeout_ms(),
            sweep_time=spec_an.get_sweep_time(),
        )


class SigGenConfig(pydantic.BaseModel):
    center_frequency: float
    power: float
    vernier_power: float


class PolarizationConfig(pydantic.BaseModel):
    kind: Literal["vertical", "horizontal"]


class ExperimentParameters(pydantic.BaseModel):
    short_description: str = "default"
    long_description: str = "default"
    neutral_elevation: float = 0.0
    relative_folder_path: Path | None = None
    cuts: dict[str, CutDefinition] | None = None
    sig_gen_config: SigGenConfig | None = None
    spec_an_config: SpecAnConfig | None = None
    polarization_config: PolarizationConfig | None = None
    # points: list[AzElTurntable] | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "DEBUG"

    collect_center_frequency_data: bool = True
    collect_peak_data: bool = True
    collect_trace_data: bool = False

    @pydantic.model_validator(mode="after")
    def _after_validator(self) -> None:
        if self.relative_folder_path is None:
            self.relative_folder_path = path_util.clean_path(EXPERIMENTS_FOLDER_PATH / self.short_description)

        # if self.grid is not None and self.points is not None:
        #     raise ValueError("Cannot have both `grid` and `points`")
        # elif self.grid is None and self.points is None:
        #     raise ValueError("Must have either `grid` or `points`")
        return self

    # @property
    # def experiment_folder_path(self) -> Path:
    #     return path_util.clean_path(EXPERIMENTS_FOLDER_PATH / self.short_description).expanduser().resolve()

    @property
    def metadata_json_path(self) -> Path:
        return self.relative_folder_path / "metadata.json"

    @property
    def log_folder_path(self) -> Path:
        return self.relative_folder_path / "logs"

    @property
    def log_plaintext_path(self) -> Path:
        return self.log_folder_path / "log.log"

    @property
    def log_jsonl_path(self) -> Path:
        return self.log_folder_path / "log.jsonl"

    @property
    def raw_data_csv_path(self) -> Path:
        return self.relative_folder_path / "raw_data" / "data.csv"

    def run(self) -> "Experiment":
        """Run this experiment."""
        experiment = Experiment(parameters=self)
        experiment.run()
        return experiment

    def write_metadata(self) -> None:
        parent = self.metadata_json_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        self.metadata_json_path.write_text(self.model_dump_json(indent=4))


class ExperimentDatapoint(pydantic.BaseModel):
    cut_id: str | int | None = None
    point_index: int | None = None
    timestamp: datetime.datetime | None = None

    commanded_coordinate: Coordinate | None = None
    actual_coordinate: Coordinate | None = None

    center_frequency: float | None = None
    center_amplitude: float | None = None
    peak_frequency: float | None = None
    peak_amplitude: float | None = None

    trace_lower_bound: float | None = None
    trace_upper_bound: float | None = None
    trace_data: list[float] | None = None

    def to_csv_dict(self) -> dict[str, Any]:
        rv = {
            "point_index": self.point_index,
            "timestamp": self.timestamp,
            "cut_id": self.cut_id,
            # "actual_azimuth": None,
            # "actual_elevation": None,
            "center_frequency": self.center_frequency,
            "center_amplitude": self.center_amplitude,
            "peak_frequency": self.peak_frequency,
            "peak_amplitude": self.peak_amplitude,
            # "trace_lower_bound": self.trace_lower_bound,
            # "trace_upper_bound": self.trace_upper_bound,
            # "trace_data": self.trace_data,
        }

        if self.commanded_coordinate is not None:
            rv["commanded_azimuth"] = self.commanded_coordinate.turntable_azimuth
            rv["commanded_elevation"] = self.commanded_coordinate.turntable_elevation
        if self.actual_coordinate is not None:
            rv["actual_azimuth"] = self.actual_coordinate.turntable_azimuth
            rv["actual_elevation"] = self.actual_coordinate.turntable_elevation
        if self.trace_data:
            rv["trace_data"] = ";".join(str(x) for x in self.trace_data)
            rv["trace_lower_bound"] = self.trace_lower_bound
            rv["trace_upper_bound"] = self.trace_upper_bound

        rv = {k: v for k, v in rv.items() if v is not None}

        return rv


class ExperimentResults(pydantic.BaseModel):
    datapoints: list[ExperimentDatapoint] = pydantic.Field(default_factory=list)

    def append_csv(self, *, csv_path: Path, data: ExperimentDatapoint) -> None:
        """Append a datapoint to a CSV file.

        Have a manual thing for this to avoid Pandas overhead, and also because
        trace data needs to be stringified"""
        data_dict = data.to_csv_dict()
        fieldnames = data_dict.keys()
        if not csv_path.exists():
            csv_path.parent.mkdir(parents=True, exist_ok=True)

            with open(csv_path, "w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames, dialect="unix")
                writer.writeheader()

        with open(csv_path, "a", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames, dialect="unix")
            writer.writerow(data_dict)

    def to_pandas(self) -> pd.DataFrame:
        return pd.DataFrame([datapoint.model_dump() for datapoint in self.datapoints])

    def to_csv(self, path: Path) -> None:
        self.to_pandas().to_csv(path, index=False)


class Experiment(pydantic.BaseModel):
    parameters: ExperimentParameters
    results: ExperimentResults | None = None

    model_config = pydantic.ConfigDict(extra="allow")

    @classmethod
    def from_parameters_file(
        cls,
        path: Path,
        *,
        results: ExperimentResults | None = None,
    ) -> "Experiment":
        """Create an `Experiment` object from a `parameters.json` file."""
        path = Path(path).resolve().absolute()
        if path.is_dir():
            paths = list(path.rglob("parameters.json"))
            if len(paths) == 0:
                raise ValueError(f"No `parameters.json` file found in {path}")
            elif len(paths) > 1:
                raise ValueError(f"Multiple `parameters.json` files found in {path}")
            path = paths[0]
        parameters = ExperimentParameters.model_validate_json(path.read_text(encoding="utf-8"))
        return cls(parameters=parameters, results=results)

    @classmethod
    def run_file(
        cls,
        *,
        path: Path,
        indexes_to_skip: Iterable[int] | None = None,
    ) -> "Experiment":
        parameters = None
        parameters_path = None
        if path.is_file():
            try:
                parameters = ExperimentParameters.model_validate_json(path.read_text(encoding="utf-8"))
                parameters_path = path
            except Exception:
                pass
        else:
            for file_path in path.rglob("parameters.json"):
                try:
                    parameters = ExperimentParameters.model_validate_json(file_path.read_text(encoding="utf-8"))
                    parameters_path = file_path
                except Exception:
                    pass

        if parameters is None:
            raise ValueError(f"No valid parameters.json file found in {path}")

        parameters.relative_folder_path = parameters_path.parent

        print(f"Loaded parameters from {parameters_path}")

        experiment = cls(parameters=parameters)
        experiment.run(
            indexes_to_skip=indexes_to_skip,
        )
        print(f"Experiment finished. Data saved to {parameters.raw_data_csv_path}")

        return experiment

    def run(
        self,
        *,
        indexes_to_skip: Iterable[int] | None = None,
    ) -> "Experiment":
        from msu_ssc import ssc_log

        ssc_log.init(
            level=self.parameters.log_level,
            plain_text_file_path=self.parameters.log_plaintext_path,
            jsonl_file_path=self.parameters.log_jsonl_path,
        )
        self.logger = ssc_log.logger.getChild("experiment")

        # CONNECT TO AND CONFIGURE SPEC AN
        self.spec_an = SpectrumAnalyzerHP8563E.find(
            logger=self.logger.getChild("spec_an"),
        )
        if not self.spec_an:
            raise ValueError("No spectrum analyzer found")

        self.spec_an.set_reference_level(self.parameters.spec_an_config.reference_level)
        self.actual_center_frequency = self.spec_an.move_center_to_peak(
            center_frequency=self.parameters.spec_an_config.initial_center_frequency,
            spans=self.parameters.spec_an_config.spans_when_searching,
        )

        # CONNECT TO AND CONFIGURE SIGNAL GENERATOR
        while True:
            print(f"Configure the signal generator manually:")
            print(f"{self.parameters.sig_gen_config.model_dump_json(indent=4)}")
            user_input = input("Is signal generator configured? [y/n]: ")
            if user_input.lower() == "y":
                break

        # CONNECT TO AND CONFIGURE TURNTABLE
        self.turntable = Turntable.find(
            logger=self.logger.getChild("turntable"),
            timeout=1.0,
            show_move_debug=True,
        )
        if not self.turntable:
            raise ValueError("No turn table found")
        self.turntable.interactively_center()

        # CREATE RESULTS OBJECT
        self.results = ExperimentResults()

        # Delete the CSV, if it exists
        if self.parameters.raw_data_csv_path.exists():
            self.parameters.raw_data_csv_path.unlink()

        # DO THE TEST!
        test_start_time = datetime.datetime.now(datetime.timezone.utc)
        if self.parameters.cuts:
            self._run_cuts_experiment(
                indexes_to_skip=indexes_to_skip,
            )
            pass

        # TEST IS DONE
        test_end_time = datetime.datetime.now(datetime.timezone.utc)
        duration = test_end_time - test_start_time

        print(
            f"Test started at {test_start_time} and ended at {test_end_time}. Total duration: {duration.total_seconds():,.0f} seconds = {duration.total_seconds() / 60:,.1f} minutes = {duration.total_seconds() / 60 / 60:,.2f} hours"
        )
        return self

    def _run_cuts_experiment(
        self,
        *,
        indexes_to_skip: Iterable[int] | None = None,
    ) -> None:
        indexes_to_skip = list(indexes_to_skip or [])
        cuts = self.parameters.cuts
        assert cuts is not None, "Cuts should not be `None` here"
        assert len(cuts) > 0, "Cuts should not be empty here"

        # HACK: Have to manually set the neutral elevation, since it's not
        # part of the cut parameters
        for cut in cuts.values():
            cut.neutral_elevation = self.parameters.neutral_elevation
            print(f"Set neutral elevation to {cut.neutral_elevation}")

        total_points = sum(len(cut.coordinates()) for cut in cuts.values())
        total_rough_time_estimate = sum(cut.rough_time_estimate(trace=self.parameters.collect_trace_data) for cut in cuts.values())

        prompt_string = f"There are {len(cuts):,} cuts, with a total of {total_points:,} points."

        for cut_id, cut in cuts.items():
            prompt_string += f"\n  {cut_id}: {cut.direction} at {cut.fixed_angle}° from {cut.start_angle} to {cut.end_angle}°, step size {cut.step_size}°. {len(cut.coordinates()):,} points, estimated time {cut.rough_time_estimate(trace=self.parameters.collect_trace_data):,.0f} seconds."
        prompt_string += f"\nTotal estimated time for all cuts: {total_rough_time_estimate:,.0f} seconds = {total_rough_time_estimate / 60:,.1f} minutes = {total_rough_time_estimate / 60 / 60:,.2f} hours."

        while True:
            print(prompt_string)
            user_input = input("Do you want to continue? [y/n]: ")
            if user_input.lower() == "y":
                break
            elif user_input.lower() == "n":
                print("Aborting experiment.")
                return
            else:
                print("Did not understand input.")
        say(f"Beginning experiment.")
        from rich.progress import Progress
        try:
            with Progress(transient=True) as progress:
                overall_progress_task = progress.add_task(
                    f"Overall point 1 of {total_points:,}",
                    total=total_points,
                    completed=0,
                )
                cut_progress_task = progress.add_task(
                    f"Cut 1 of {len(cuts):,}",
                    total=len(cuts),
                    completed=0,
                )

                this_cut_progress_task = progress.add_task(
                    f"Cut point 1 of ??",
                    total=100,
                    completed=0,
                )

                point_index = 0
                for cut_index, (cut_id, cut) in enumerate(cuts.items()):
                    cut_id_text = cut_id.lower().replace("_", " ").replace("-", " ")
                    say(f"Begin cut {cut_index + 1} of {len(cuts)}, {cut_id_text}")

                    # Update the progress tasks
                    progress.update(
                        cut_progress_task,
                        completed=cut_index + 1,
                        description=f"Doing cut #{cut_index + 1} of {len(cuts):,} ({cut_id})",
                    )
                    progress.update(
                        this_cut_progress_task,
                        total=len(cut),
                        completed=0,
                    )

                    if cut.reset_before:
                        self.turntable.move_to(azimuth=0, elevation=0)

                    for coordinate_index, coordinate in enumerate(cut.coordinates()):
                        progress.update(
                            this_cut_progress_task,
                            completed=coordinate_index,
                            description=f"Doing point #{coordinate_index + 1} of {len(cut)} within cut",
                        )
                        point_index += 1
                        progress.update(
                            overall_progress_task,
                            completed=point_index,
                            description=f"Overall progress point #{point_index} of {total_points:,} points",
                        )

                        if point_index in indexes_to_skip:
                            self.logger.info(f"Skipping point_index {point_index} {coordinate}")
                            continue

                        # Actually do the danged experiment
                        self._run_experiment_at_point(
                            point=coordinate,
                            cut_id=cut_id,
                            point_index=point_index,
                            neutral_elevation=self.parameters.neutral_elevation,
                        )

                    # Move to 0 0 at the end of each cut
                    # self.turntable.move_to(azimuth=0, elevation=0)
            print(f"FINISHED!!!")
            say(f"Experiment finished!")

            print(f"Data saved to {self.parameters.raw_data_csv_path}")
        except Exception as exc:
            self.logger.error(f"Error during experiment: {exc}")
            say(f"Error during experiment: {type(exc).__name__}")
            raise
        except KeyboardInterrupt:
            self.logger.warning(f"Experiment interrupted by user")
            say(f"Experiment interrupted by user")
        finally:
            # Reset turntable
            say(f"Resetting turntable to 0, 0.")
            self.turntable.move_to(azimuth=0, elevation=0, move_timeout=120)

    # def _run_grid_experiment(
    #     self,
    #     *,
    #     indexes_to_skip: Iterable[int] | None = None,
    # ) -> None:
    #     raise ValueError("Using the `grid` parameter is no longer supported. Use `cuts` instead.")
    #     grid = self.parameters.grid
    #     assert grid is not None, "Grid should not be `None` here"

    #     if isinstance(grid, dict):
    #         grid_dict = grid
    #     else:
    #         grid_dict = {"grid": grid}

    #     indexes_to_skip = set(indexes_to_skip) if indexes_to_skip else set()

    #     # Find total points in all grids
    #     total_points = 0
    #     for grid_value in grid_dict.values():
    #         total_points += len(grid_value)

    #     total_rough_time_estimate = 0
    #     for grid_value in grid_dict.values():
    #         total_rough_time_estimate += grid_value.rough_time_estimate()

    #     while True:
    #         print(
    #             f"This grid has {total_points:,} points and will take approximately {total_rough_time_estimate:,.0f} seconds to complete."
    #         )
    #         user_input = input("Do you want to continue? [y/n]: ")
    #         if user_input.lower() == "y":
    #             break
    #         elif user_input.lower() == "n":
    #             print("Aborting experiment.")
    #             return
    #         else:
    #             print("Did not understand input.")

    #     from rich.progress import Progress

    #     with Progress(transient=True) as progress:
    #         overall_progress_task = progress.add_task(
    #             f"Overall progress point 1 of ({total_points:,} points)",
    #             total=total_points,
    #         )
    #         cut_progress_task = progress.add_task(f"Doing cut #1 of {len(grid_dict):,}", total=len(grid_dict))

    #         this_cut_progress_task = progress.add_task(
    #             # f"Doing point #1 of {grid.size_of_cut()} within cut", total=grid.size_of_cut()
    #             f"TBD",
    #             # total=grid.size_of_cut()
    #             total=100,
    #         )
    #         point_index = 0
    #         for grid_index, (grid_name, grid) in enumerate(grid_dict.items()):
    #             progress.update(
    #                 cut_progress_task,
    #                 completed=1,
    #                 description=f"Doing cut #{grid_index + 1} of {len(grid_dict):,} ({grid_name})",
    #             )
    #             progress.update(
    #                 this_cut_progress_task,
    #                 total=grid.size_of_cut(),
    #                 completed=0,
    #             )
    #             for cut_index, cut in enumerate(grid.cuts()):
    #                 for coordinate_index, coordinate in enumerate(cut):
    #                     if point_index in indexes_to_skip:
    #                         self.logger.info(f"Skipping point_index {point_index} {coordinate}")

    #                         continue
    #                     self._run_experiment_at_point(
    #                         point=coordinate,
    #                         cut_id=grid_name,
    #                         point_index=point_index,
    #                         neutral_elevation=grid.neutral_elevation,
    #                     )
    #                     point_index += 1
    #                     progress.update(
    #                         overall_progress_task,
    #                         completed=point_index,
    #                         description=f"Overall progress point #{point_index} of {total_points:,} points",
    #                     )
    #                     progress.update(
    #                         this_cut_progress_task,
    #                         completed=coordinate_index,
    #                         description=f"Doing point #{coordinate_index + 1} of {grid.size_of_cut()} within cut",
    #                     )

    #             # Move to 0 0
    #             # We have not ever tested or verified beginning a cut anywhere other than the origin.
    #             # Specifically we're not sure across elevation regime boundaries
    #             # For example moving from az = 80, el = 0 to az = 0, el = - 90, would include diagonal travel across elevation regime boundaries.
    #             # This should work, but we have not tested it.
    #             self.turntable.move_to(azimuth=0, elevation=0)

    #         # EXPERIMENT DONE!
    #         # Reset turntable
    #         self.turntable.move_to(azimuth=0, elevation=0)
    #         print(f"FINISHED!!!")
    #         print(f"Data saved to {self.parameters.raw_data_csv_path}")

    def _run_experiment_at_point(
        self,
        *,
        point: Coordinate,
        cut_id: str | int | None = None,
        point_index: int | None = None,
        neutral_elevation: float | None = None,
    ) -> None:
        self.turntable.move_to(azimuth=point.turntable_azimuth, elevation=point.turntable_elevation)
        actual_position = self.turntable.wait_for_position()
        data = ExperimentDatapoint()
        if neutral_elevation is None:
            neutral_elevation = self.parameters.neutral_elevation
        data.actual_coordinate = Coordinate.from_turntable(
            azimuth=actual_position.pan,
            elevation=actual_position.tilt,
            neutral_elevation=neutral_elevation,
        )
        data.commanded_coordinate = point
        data.timestamp = datetime.datetime.now(datetime.timezone.utc)
        data.cut_id = cut_id
        data.point_index = point_index

        if self.parameters.collect_center_frequency_data:
            center_amplitude = self.spec_an.get_center_frequency_amplitude()
            center_frequency = self.spec_an.get_center_frequency()
            data.center_frequency = center_frequency
            data.center_amplitude = center_amplitude

        if self.parameters.collect_peak_data:
            peak_frequency, peak_amplitude = self.spec_an.get_peak_frequency_and_amplitude()
            data.peak_frequency = peak_frequency
            data.peak_amplitude = peak_amplitude

        if self.parameters.collect_trace_data:
            trace_lower_bound = self.spec_an.get_lower_frequency()
            trace_upper_bound = self.spec_an.get_upper_frequency()
            trace_data = self.spec_an.get_trace()
            data.trace_lower_bound = trace_lower_bound
            data.trace_upper_bound = trace_upper_bound
            data.trace_data = list(trace_data)

        print(f"At coordinate {point}, collected data: {data}")

        self.results.datapoints.append(data)
        self.results.append_csv(
            data=data,
            csv_path=self.parameters.raw_data_csv_path,
        )

    def _run_points_experiment(
        self,
        *,
        indexes_to_skip: Iterable[int] | None = None,
    ) -> None:
        raise NotImplementedError("`Experiment._run_points_experiment` not implemented yet")
        # points = self.parameters.points
        # assert points is not None, "Points should not be `None` here"

        # indexes_to_skip = set(indexes_to_skip) if indexes_to_skip else set()

        # from rich.progress import Progress

        # with Progress(transient=True) as progress:
        #     task_id = progress.add_task(f"Collecting data ({len(points):,} points)", total=len(points))
        #     for point_index, point in enumerate(points):
        #         if point_index in indexes_to_skip:
        #             self.logger.info(f"Skipping point_index {point_index} {point}")
        #         self._run_experiment_at_point(point=point, cut_id="none", point_index=point_index)
        #         progress.update(
        #             task_id,
        #             completed=point_index + 1,
        #             description=f"Collecting data ({point_index + 1:,} of {len(points)} points)",
        #         )
        # pass


if __name__ == "__main__":
    spec_an_config = SpecAnConfig(
        initial_center_frequency=8_450_000_000,
        spans_when_searching=[
            1_000_000,
            100_000,
            10_000,
            1_000,
        ],
        reference_level=-10,
    )
    sig_gen_config = SigGenConfig(center_frequency=8_450_000_000, power=-10, vernier_power=0)
    polarization_config = PolarizationConfig(kind="vertical")
    cuts = {
        "COARSE_AZIMUTH": CutDefinition(
            direction="horizontal", fixed_angle=0, start_angle=-10, end_angle=10, step_size=5
        ),
        "COARSE_ELEVATION": CutDefinition(
            direction="vertical", fixed_angle=0, start_angle=-2, end_angle=2, step_size=1
        ),
    }
    # points = {
    #     0: AzElTurntable(azimuth=-5, elevation=5),
    #     1: AzElTurntable(azimuth=5, elevation=5),
    #     # 2: AzElTurntable(azimuth=-5, elevation=-5),
    #     # 3: AzElTurntable(azimuth=5, elevation=-5),
    # }
    # grid = Grid(
    #     min_azimuth=-10,
    #     max_azimuth=10,
    #     azimuth_step_size=10,
    #     min_elevation=-2,
    #     max_elevation=2,
    #     elevation_step_size=2,
    #     orientation="horizontal",
    # )
    experiment_parameters = ExperimentParameters(
        short_description="3x3 8.45 GHz",
        long_description="Initial test of a 3x3 grid at 8.45 GHz",
        spec_an_config=spec_an_config,
        sig_gen_config=sig_gen_config,
        # points=points,
        # grid=grid,
        cuts=cuts,
        polarization_config=polarization_config,
        # folder=Path("./experiments/mayo01"),
        # az_el_cls="AzElSpherical",
        collect_center_frequency_data=True,
        collect_peak_data=True,
        collect_trace_data=True,
    )
    print(f"{experiment_parameters=}")
    print(experiment_parameters.model_dump_json(indent=4))

    with open("params.json", "w", encoding="utf8") as file:
        file.write(experiment_parameters.model_dump_json(indent=4))

    Experiment.run_file(path=Path("./experiments/mayo_experiment"))
    exit()
    # exit()
    # experiment_2 = ExperimentParameters.model_validate_json(experiment_parameters.model_dump_json())
    # print(f"{experiment_2=}")

    # experiment_parameters.write_metadata()

    print("+++++++++++++++++")
    # print(f"{experiment_parameters=}")
    experiment = Experiment(parameters=experiment_parameters)
    print("--------")
    print(f"{experiment.model_dump_json(indent=4)}")
    print("--------")

    experiment.run()
    print("+++++++++++++++")

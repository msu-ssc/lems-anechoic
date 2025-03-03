from pathlib import Path
from typing import Literal

import pydantic
from msu_ssc import path_util

from msu_anechoic import AzElTurntable

EXPERIMENTS_FOLDER_PATH = Path("./experiments")


class Grid(pydantic.BaseModel):
    min_azimuth: float
    max_azimuth: float
    aziumuth_step_size: float
    min_elevation: float
    max_elevation: float
    elevation_step_size: float
    orientation: Literal["horizontal", "vertical"]


class SpecAnConfig(pydantic.BaseModel):
    initial_center_frequency: float
    spans_when_searching: list[float]
    reference_level: float = -10


class SigGenConfig(pydantic.BaseModel):
    center_frequency: float
    power: float
    vernier_power: float


class ExperimentParameters(pydantic.BaseModel):
    short_description: str = "default"
    long_description: str = "default"

    relative_folder_path: Path | None = None
    raw_data_csv_path: Path | None = None
    metadata_json_path: Path | None = None
    log_jsonl_path: Path | None = None
    log_plaintext_path: Path | None = None

    grid: Grid | None = None
    points: list[AzElTurntable] | None = None

    desired_sig_gen_config: SigGenConfig | None = None
    actual_start_sig_gen_config: SigGenConfig | None = None
    actual_finish_sig_gen_config: SigGenConfig | None = None

    desired_spec_an_config: SpecAnConfig | None = None
    actual_start_spec_an_config: SpecAnConfig | None = None
    actual_finish_spec_an_config: SpecAnConfig | None = None

    # experiment_start_time_utc: datetime.datetime | None = None
    # experiment_finish_time_utc: datetime.datetime | None = None
    points: dict[int, AzElTurntable] | None = None
    # az_el_cls: Literal["AzElSpherical", "AzElTurntable"] | None = None

    @pydantic.model_validator(mode="after")
    def _after_validator(self) -> None:
        if self.relative_folder_path is None:
            self.relative_folder_path = path_util.clean_path(EXPERIMENTS_FOLDER_PATH / self.short_description)
        if self.raw_data_csv_path is None:
            self.raw_data_csv_path = self.relative_folder_path / "raw_data.csv"
        if self.metadata_json_path is None:
            self.metadata_json_path = self.relative_folder_path / "experiment_metadata.json"
        if self.log_jsonl_path is None:
            self.log_jsonl_path = self.relative_folder_path / "logs" / "log.jsonl"
        if self.log_plaintext_path is None:
            self.log_plaintext_path = self.relative_folder_path / "logs" / "log.txt"

        if self.grid is not None and self.points is not None:
            raise ValueError("Cannot have both `grid` and `points`")
        elif self.grid is None and self.points is None:
            raise ValueError("Must have either `grid` or `points`")

    # @property
    # def experiment_folder_path(self) -> Path:
    #     return path_util.clean_path(EXPERIMENTS_FOLDER_PATH / self.short_description).expanduser().resolve()

    def write_metadata(self) -> None:
        parent = self.metadata_json_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        self.metadata_json_path.write_text(self.model_dump_json(indent=4))


def run_experiment(
    *,
    parameters: ExperimentParameters,
) -> None:
    from msu_anechoic.spec_an import SpectrumAnalyzerHP8563E
    from msu_anechoic.turn_table import Turntable

    # TODO: Make log params part of the config
    # isort: off
    from msu_ssc import ssc_log

    ssc_log.init(
        level="DEBUG",
        plain_text_file_path=parameters.log_plaintext_path,
        jsonl_file_path=parameters.log_jsonl_path,
    )
    logger = ssc_log.logger.getChild("experiment")
    # isort: on

    # CONNECT TO TURNTABLE
    turn_table = Turntable.find(
        logger=logger.getChild("turntable"),
    )
    if turn_table is None:
        raise ValueError("Could not find turn table")

    # CONNECT TO SPECTRUM ANALYZER
    spec_an = SpectrumAnalyzerHP8563E.find(
        logger=logger.getChild("spec_an"),
    )
    if spec_an is None:
        raise ValueError("Could not find spectrum analyzer")

    # CONFIGURE SPEC AN
    # TODO: Write this method
    spec_an.configure(parameters.desired_spec_an_config)
    center_frequency = spec_an.move_center_to_peak(
        center_frequency=parameters.desired_spec_an_config.initial_center_frequency,
        spans=parameters.desired_spec_an_config.spans_when_searching,
    )
    spec_an.set_reference_level(-10)

    # CONFIGURE SIG GEN
    # This is manual for now
    print("Configure the signal generator manually")
    print(f"{parameters.desired_sig_gen_config.model_dump_json(indent=4)}")

    # CONFIGURE TURNTABLE
    turn_table.interactively_center()

    # RUN EXPERIMENT
    # TODO


if __name__ == "__main__":
    spec_an_config = SpecAnConfig(initial_center_frequency=8_450_000_000, spans_when_searching=1_000)
    sig_gen_config = SigGenConfig(center_frequency=8_450_000_000, power=-10, vernier_power=0)
    # points = {
    #     0: AzElTurntable(azimuth=-5, elevation=5),
    #     1: AzElTurntable(azimuth=5, elevation=5),
    #     # 2: AzElTurntable(azimuth=-5, elevation=-5),
    #     # 3: AzElTurntable(azimuth=5, elevation=-5),
    # }
    grid = Grid(
        min_azimuth=-10,
        max_azimuth=10,
        aziumuth_step_size=1,
        min_elevation=-2,
        max_elevation=2,
        elevation_step_size=1,
        orientation="horizontal",
    )
    experiment = ExperimentParameters(
        short_description="3x3 8.45 GHz",
        long_description="Initial test of a 3x3 grid at 8.45 GHz",
        desired_spec_an_config=spec_an_config,
        desired_sig_gen_config=sig_gen_config,
        # points=points,
        grid=grid,
        # folder=Path("./experiments/mayo01"),
        # az_el_cls="AzElSpherical",
    )
    print(f"{experiment=}")
    print(experiment.model_dump_json(indent=4))

    experiment_2 = ExperimentParameters.model_validate_json(experiment.model_dump_json())
    print(f"{experiment_2=}")

    experiment.write_metadata()

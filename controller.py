"""
Code originally written by Jody Caudill.

Unknown (as of January 2025) what the original purpose of this code was, or what precisely the dependencies are.
"""

import dataclasses
import datetime
import json
import sys
from pathlib import Path
from typing import Literal
from typing import NamedTuple
from typing import Sequence

import pyvisa
import serial
from msu_ssc import ssc_log

spectrum_analyzer: pyvisa.resources.messagebased.MessageBasedResource | None = None
turn_table: serial.Serial | None = None


# CONFIGURATION
# Make changes in the `config.json` file, not here.
@dataclasses.dataclass
class AnechoicConfig:
    """Container for script config."""

    SPEC_AN_GPIB_ADDRESS: str
    TURN_TABLE_SERIAL_PORT: str
    TURN_TABLE_BAUD_RATE: int
    AZIMUTH_MARGIN: float
    ELEVATION_MARGIN: float
    LOG_FOLDER_PATH_STR: str
    DATA_FOLDER_PATH_STR: str
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    @property
    def log_folder_path(self) -> Path:
        return Path(self.LOG_FOLDER_PATH_STR).expanduser().resolve()

    @property
    def data_folder_path(self) -> Path:
        return Path(self.DATA_FOLDER_PATH_STR).expanduser().resolve()

    def to_json(self, path: Path) -> None:
        """Save the config to a JSON file."""
        comment = "Modify the things in 'config' to change the configuration. This file should be in the same directory as the controller script."
        data = {
            "comment": comment,
            "config": dataclasses.asdict(self),
        }
        path.write_text(json.dumps(data, indent=4))

    @classmethod
    def from_json(cls, path: Path = Path("./config.json")) -> "AnechoicConfig":
        """Load a config from a JSON file."""
        path = Path(path).expanduser().resolve()

        # Log as a warning because we likely haven't initialized the logger yet, and it won't be visible if it's `info` or `debug`.
        ssc_log.warning(f"Loading config from {path}")
        json_dict = json.loads(path.read_text())
        config_dict = json_dict["config"]
        return AnechoicConfig(**config_dict)

    def asdict(self) -> dict[str, str | int | float]:
        return dataclasses.asdict(self)


class AzEl(NamedTuple):
    """Azimuth and elevation in degrees."""

    azimuth: float
    elevation: float


def get_turn_table_location(
    turn_table: serial.Serial = turn_table,
) -> AzEl | None:
    """Get the current azimuth and elevation of the turn table.

    This is a blocking operation."""
    ssc_log.debug("Getting turn table location")
    try:
        turn_table_data = turn_table.read(1000)
        location = parse_az_el(turn_table_data)
        ssc_log.debug(f"Got turn table location: {location!r}")
        return location
    except Exception as exc:
        ssc_log.warning(f"Failed to get turn table location", exc_info=exc)
        return None


def move_command(azimuth: float, elevation: float) -> bytes:
    return f"CMD:MOV:{azimuth:.3f},{elevation:.3f};".encode(encoding="ascii")


def move_to(
    *,
    azimuth: float,
    elevation: float,
    azimuth_margin: float = 0.5,
    elevation_margin: float = 0.5,
    turn_table: serial.Serial = turn_table,
) -> AzEl:
    """Move to some given location, with a margin of error for both azimuth and elevation in degrees.

    Return the actual azimuth and elevation that the turn table ended up at."""
    command = move_command(azimuth, elevation)
    turn_table.write(command)

    while True:
        location = get_turn_table_location()
        delta_az = abs(location.azimuth - azimuth)
        delta_el = abs(location.elevation - elevation)
        if delta_az < azimuth_margin and delta_el < elevation_margin:
            ssc_log.debug(f"Arrived at {location!r}")
            return location
        else:
            ssc_log.debug(f"Still moving to {AzEl(azimuth, elevation)}; currently at {location!r}")


def gather_data(
    points: Sequence[AzEl],
    turn_table: serial.Serial = turn_table,
    spectrum_analyzer: pyvisa.resources.messagebased.MessageBasedResource = spectrum_analyzer,
):
    """Move to each point in `points` and gather data."""
    collected_data = []

    for index, commanded_point in enumerate(points):
        actual_point = move_to(
            azimuth=commanded_point.azimuth,
            elevation=commanded_point.elevation,
            azimuth_margin=config.AZIMUTH_MARGIN,
            elevation_margin=config.ELEVATION_MARGIN,
            turn_table=turn_table,
        )

        # TODO: Need to find trace min/max frequencies so we can set the span
        # I know this is in some of Christo's code

        trace_data_raw: str = spectrum_analyzer.query("TRA?").split(",")
        timestamp = datetime.datetime.now(tz=datetime.timezone.utc)
        trace_data_values = [float(point) for point in trace_data_raw.split(",")]
        ssc_log.debug(f"Collected data for {commanded_point}. Max value: {max(trace_data_values)}")
        collected_data.append(
            {
                "commanded_azimuth": commanded_point.azimuth,
                "commanded_elevation": commanded_point.elevation,
                "actual_azimuth": actual_point.azimuth,
                "actual_elevation": actual_point.elevation,
                "timestamp": timestamp,
                "trace_data": trace_data_values,
            }
        )


def parse_az_el(data: bytes) -> AzEl:
    """Parse the azimuth and elevation from the given data.

    `data` should be a bytestring like `b"blah blah \r\nEl: -12.345, Az: -98.765\r\nblah blah"`

    NOTE: The data lists elevation first, but the return of this function will be the more common `(azimuth, elevation)`"""
    data_str = str(data, "ascii")  # Like "blah blah \r\nEl: -12.345, Az: -98.765\r\nblah blah"
    begin_el_az_index = data_str.index("El:")
    end_el_az_index = data_str.index("\r", begin_el_az_index)
    substring = data_str[begin_el_az_index:end_el_az_index]  # Like "El: -12.345, Az: -98.765"
    parts = [i.strip() for i in substring.split(",")]  # Like ["El: -12.345", "Az: -98.765"]
    values = [float(i.split(" ")[1]) for i in parts]  # Like [-12.345, -98.765]
    return AzEl(azimuth=values[1], elevation=values[0])


if __name__ == "__main__":
    config = AnechoicConfig.from_json(Path("config.json"))

    # Log to a file and also to the screen
    ssc_log.init(
        plain_text_file_path=config.log_folder_path / ssc_log.utc_filename_timestamp(prefix="anechoic"),
        level=config.LOG_LEVEL,
    )
    ssc_log.debug(f"Python info: {sys.executable=}")
    ssc_log.debug(f"Python info: {sys.version=}")
    ssc_log.debug(f"Python info: {sys.argv=}")
    ssc_log.debug(f"Config info: {config.SPEC_AN_GPIB_ADDRESS=}")
    ssc_log.debug(f"Config info: {config.TURN_TABLE_SERIAL_PORT=}")
    ssc_log.debug(f"Config info: {config.TURN_TABLE_BAUD_RATE=}")
    ssc_log.debug(f"Config info: {config.AZIMUTH_MARGIN=}")
    ssc_log.debug(f"Config info: {config.ELEVATION_MARGIN=}")
    ssc_log.debug(f"Config info: {config.LOG_FOLDER_PATH_STR=}")
    ssc_log.debug(f"Config info: {config.LOG_LEVEL=}")
    ssc_log.debug(f"Config info: {config.log_folder_path=}")

    try:
        resource_manager = pyvisa.ResourceManager()
        spectrum_analyzer = resource_manager.open_resource(config.SPEC_AN_GPIB_ADDRESS)
        turn_table = serial.Serial(config.TURN_TABLE_SERIAL_PORT, config.TURN_TABLE_BAUD_RATE)
    except Exception as exc:
        ssc_log.critical(f"Exception: {exc=}", exc_info=exc)
        sys.exit(1)

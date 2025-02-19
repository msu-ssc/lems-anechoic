import re
import time
from typing import TYPE_CHECKING

import serial

from msu_anechoic import AzEl
from msu_anechoic import create_null_logger

if TYPE_CHECKING:
    import logging


azimuth_elevation_regex = re.compile(r"Pos\s*=\s*El:\s*(?P<elevation>[-\d\.]+)\s*,\s*Az:\s*(?P<azimuth>[-\d\.]+)")
"""Should match a string like `"Pos= El: -0.03 , Az: -0.03\\r\\n"`"""

# def parse_az_el(data: bytes) -> AzEl:
#     """Parse the azimuth and elevation from the given data."""
#     az_el_str = data.decode(encoding="ascii")
#     data.split("\n")
#     return AzEl(azimuth=-98.765, elevation=-12.345)  # TODO: Implement this

# def attempt_parse_az_el(data: bytes) -> AzEl | None:
#     """Attempt to parse the azimuth and elevation from the given data. Return `None` on any failure."""
#     try:
#         return parse_az_el(data)
#     except Exception:
#         return None


def parse_az_el(data: bytes) -> AzEl | None:
    """Parse azimuth and elevation from a byte string.

    Will return the most recent data in the byte string. Assumes that the data is in the format
    `b'Pos= El: -0.03 , Az: -0.03\\r\\n'`, although the regex is permissive about whitespace and
    number formatting.
    """

    # Split data into individual lines so that a corrupt line
    # doesn't cause the whole parse to fail.
    lines = data.split(b"\n")

    # Iterate over lines in reverse order so that we get the most recent data.
    for line in lines[::-1]:
        # Convert as ASCII. This will fail if RS-232 data was corrupted.
        try:
            string = line.decode(encoding="ascii")
        except UnicodeDecodeError:
            continue

        # Try to match the regex. If it doesn't match, continue.
        # Every line should match, unless it is corrupted or truncated.
        match = azimuth_elevation_regex.search(string)
        if not match:
            continue

        # At this point, we have a match. Parse it
        groupdict = match.groupdict()
        azimuth_string = groupdict["azimuth"]
        elevation_string = groupdict["elevation"]

        # There are things that match the regex that are not valid floats, like "123.456" or 98-76".
        # So put them in a try/except.
        try:
            rv = AzEl(azimuth=float(azimuth_string), elevation=float(elevation_string))
            return rv
        except ValueError:
            continue

    # If we get here, we didn't find any valid data.
    return None


class Turntable:
    AZIMUTH_BOUNDS = (-175, 175)
    ELEVATION_BOUNDS = (-85, 45)
    DEAD_TIME = 10.0

    def __init__(
        self,
        *,
        port: str,
        baudrate: int = 9600,
        timeout: float | None = None,
        logger: "logging.Logger | None" = None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.logger = logger or create_null_logger()
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
        )
        self.most_recent_communication_time = float("-inf")
        """The most recent time that we successfully communicated with the turntable, as `time.monotonic()`."""

        self.has_been_set: bool = False

    def time_since_last_communication(self) -> float:
        """The time since we last successfully communicated with the turntable, in seconds."""
        return time.monotonic() - self.most_recent_communication_time

    def read(self, size: int = 1000) -> bytes:
        """Read data from the turntable.

        Allow exceptions to propagate.

        Args:
            size (int): The number of bytes to read. Defaults to 1000.

        Returns:
            bytes: The data read from the turntable.
        """
        self.logger.debug(f"Attempting to read {size:,} bytes from turntable")
        data = self._serial.read(size)
        self.logger.debug(f"Read {len(data):,} bytes from turntable")
        return data

    def attempt_read(self, size: int = 1000) -> bytes | None:
        """
        Attempt to read data from the turntable, returning None if no data is available
        or there is an exception reading from serial.

        Args:
            size (int): The number of bytes to read. Defaults to 1000.

        Returns:
            bytes | None: The data read from the turntable, or None if no data is available.
        """
        self.logger.debug(f"Attempting to read {size:,} bytes from turntable")
        try:
            data = self._serial.read(size)
        except Exception as exc:
            self.logger.debug(f"Failed to read from turntable: {exc}", exc_info=exc)
        if data:
            self.logger.debug(f"Read {len(data):,} bytes from turntable")
            return data
        else:
            self.logger.debug("No data read from turntable")
            return None

    def get_position(self) -> AzEl | None:
        """Get the current azimuth and elevation of the turn table. Return `None` on any failure.

        Also, update the `most_recent_communication_time` attribute."""
        data = self.attempt_read()
        if not data:
            return None

        parsed_data = parse_az_el(data)
        if not parsed_data:
            return None

        # If we get here, we successfully communicated with the turntable. Update the time.
        self.logger.debug(
            f"Successfully communicated with turntable; updating time. Was {self.most_recent_communication_time}"
        )
        self.most_recent_communication_time = time.monotonic()
        self.logger.debug(f"Updated time to {self.most_recent_communication_time}")

        return parsed_data

    def _validate_bounds(self, azimuth: float, elevation: float) -> None:
        """Validate that the given azimuth and elevation are within the valid range for the turntable."""
        # Validate azimuth within bounds
        if not self.AZIMUTH_BOUNDS[0] <= azimuth <= self.AZIMUTH_BOUNDS[1]:
            self.logger.error(f"Azimuth {azimuth} is out of bounds {self.AZIMUTH_BOUNDS}")
            return False

        # Validate elevation within bounds
        if not self.ELEVATION_BOUNDS[0] <= elevation <= self.ELEVATION_BOUNDS[1]:
            self.logger.error(f"Elevation {elevation} is out of bounds {self.ELEVATION_BOUNDS}")
            return False

        # Assume good
        self.logger.debug(f"Azimuth {azimuth} and elevation {elevation} are within bounds.")
        return True

    def _validate_open_communication(self) -> None:
        """Validate that we have heard from the turntable recently enough."""
        time_since_last_communication = self.time_since_last_communication()
        if time_since_last_communication > self.DEAD_TIME:
            self.logger.error(
                f"Turntable has not been heard from in {time_since_last_communication} seconds, which is more than the allowable {self.DEAD_TIME} seconds"
            )
            self.has_been_set = False
            return False
        else:
            return True

    def validate_set_command(self, azimuth: float, elevation: float) -> None:
        """Validate that the given azimuth and elevation are within the valid range for the turntable."""
        valid_bounds = self._validate_bounds(azimuth, elevation)
        if not valid_bounds:
            return False

        self.logger.debug(f"Set command {azimuth=}, {elevation=} is valid.")
        return True

    def validate_move_command(self, azimuth: float, elevation: float) -> None:
        """Validate that the given azimuth and elevation are within the valid range for the turntable."""

        valid_bounds = self._validate_bounds(azimuth, elevation)
        if not valid_bounds:
            return False

        # Validate that we have heard from the turntable recently enough.
        time_since_last_communication = self.time_since_last_communication()
        if time_since_last_communication > self.DEAD_TIME:
            self.logger.error(
                f"Turntable has not been heard from in {time_since_last_communication} seconds, which is more than the allowable {self.DEAD_TIME} seconds"
            )
            return False

        # Validate that the turntable has had a SET command sent during the current comm session.
        if not self.has_been_set:
            self.logger.error("Turntable has not been set during the current comm session")
            return False

        # Assume good
        self.logger.debug(f"Move command {azimuth=}, {elevation=} is valid.")
        return True

    def send_move_command(self, azimuth: float, elevation: float) -> None:
        """Send a move command to the turntable."""
        command = f"CMD:MOV:{azimuth:.3f},{elevation:.3f};".encode(encoding="ascii")

        if not self.validate_move_command(azimuth, elevation):
            self.logger.error(f"Move command {azimuth=}, {elevation=} is invalid and WILL NOT BE SENT!")
            return

        self.logger.info(f"Sending move command to turntable: {command!r}")
        self._serial.write(command)

    def send_set_command(self, azimuth: float, elevation: float) -> None:
        """Send a set command to the turntable."""

        if not self.validate_set_command(azimuth, elevation):
            self.logger.error(f"Set command {azimuth=}, {elevation=} is invalid and WILL NOT BE SENT!")
            return

        command = f"CMD:SET:{azimuth:.3f},{elevation:.3f};".encode(encoding="ascii")
        self.logger.info(f"Sending set command to turntable: {command!r}")
        self._serial.write(command)

    def move_to(
        self,
        *,
        azimuth: float,
        elevation: float,
        azimuth_margin: float = 0.1,
        elevation_margin: float = 0.1,
        delay: float = 0.05,
    ) -> AzEl:
        """Move to the given azimuth and elevation. Return the final position."""
        if not self.validate_move_command(azimuth, elevation):
            self.logger.error(f"Move command {azimuth=}, {elevation=} is invalid and WILL NOT BE SENT!")

        starting_position = self.get_position()
        if not starting_position:
            self.logger.error("Failed to get current position. Will not send MOVE command.")
            return None

        self.send_move_command(azimuth, elevation)

        target_position = AzEl(azimuth=azimuth, elevation=elevation)

        while True:
            current_position = self.get_position()
            if not current_position:
                continue
            azimuth_delta = abs(current_position.azimuth - azimuth)
            elevation_delta = abs(current_position.elevation - elevation)
            if azimuth_delta <= azimuth_margin and elevation_delta <= elevation_margin:
                self.logger.info(f"Successfully moved to {current_position=} from {starting_position=}")
                break
            else:
                self.logger.debug(
                    f"Still moving... {current_position=} {target_position=} {starting_position=} {azimuth_delta=}, {elevation_delta=}"
                )
            time.sleep(delay)

        return current_position


if __name__ == "__main__":
    from msu_ssc import ssc_log

    ssc_log.init(level="DEBUG")
    logger = ssc_log.logger.getChild("turntable")
    tt = Turntable(port="COM5", logger=logger)

    while True:
        position = tt.get_position()
        print(position)
        time.sleep(0.1)
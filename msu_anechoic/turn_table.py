import csv
import datetime
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import serial

from msu_anechoic import AzEl
from msu_anechoic import Coordinate
from msu_anechoic import _turn_table_elevation_regime as _regime
from msu_anechoic import create_null_logger

if TYPE_CHECKING:
    import logging

# NOTE: This is slightly greater than 0.10 (what is hardcoded into firmware) to handle the fact that the firmware
# rounds to 2 decimal places.
# See issue #6 for more details. https://github.com/msu-ssc/lems-anechoic/issues/6
ALLOWABLE_DISCREPANCY_DEG = 0.11
"""The allowable difference between the commanded and actual position along tilt or pan, in degrees."""


class TurntableError(Exception):
    """Some kind of error with turntable communication."""


# NOTE: The line in the firmware code is:
# snprintf(sendbuffer,42,"Pos= El: %.2f , Az: %.2f \r\n",El_pos_deg,Az_pos_deg);
#
# Which results in a string like
# "Pos= El: -0.03 , Az: -0.03\r\n"

# More lax regex:
# azimuth_elevation_regex = re.compile(r"Pos= El: (?P<elevation>[-\d\.]+)\s*,\s*Az:\s*(?P<azimuth>[-\d\.]+)")

# Much stricter regex. This only allows exact matches.
azimuth_elevation_regex = re.compile(r"Pos= El: (?P<elevation>-?\d{1,3}\.\d{2}) , Az: (?P<azimuth>-?\d{1,3}\.\d{2})")


class Turntable:
    ABSOLUTE_AZIMUTH_BOUNDS = (-180, 180)
    ABSOLUTE_ELEVATION_BOUNDS = (-90, 45)
    REGIME_ELEVATION_BOUNDS = (-29.5, 29.5)
    """The bounds of the turntable's elevation regime, in degrees.
    
    Moving outside this range will require a regime change."""

    DEAD_TIME = 1000.0
    csv_field_names = ["timestamp", "azimuth", "elevation"]

    def __init__(
        self,
        *,
        port: str,
        baudrate: int = 9600,
        timeout: float | None = None,
        logger: "logging.Logger | None" = None,
        csv_file_path: str | Path | None = None,
        show_move_debug: bool = False,
        neutral_elevation: float = 0.0,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._show_move_debug = show_move_debug
        self.neutral_elevation = neutral_elevation
        self.logger = logger or create_null_logger()
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
        )

        self.csv_file_path = csv_file_path
        if self.csv_file_path:
            self.csv_file_path = Path(self.csv_file_path).expanduser().resolve()
            self.csv_file_path.parent.mkdir(parents=True, exist_ok=True)

            with self.csv_file_path.open(mode="w", newline="") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self.csv_field_names, dialect="unix")
                writer.writeheader()

        self.most_recent_communication_time = float("-inf")
        """The most recent time that we successfully communicated with the turntable, as `time.monotonic()`."""

        self.has_been_set: bool = False
        self._current_regime: _regime.TurnTableElevationRegime | None = None
        """The current elevation regime of the turntable.
        
        Will be `None` until it is explicitly set."""

        self._regime_elevation_offset: float | None = None
        """The elevation offset of table between its reported ."""

    @classmethod
    def find(
        cls,
        *,
        baudrate: int = 9600,
        timeout: float | None = None,
        logger: "logging.Logger | None" = None,
        csv_file_path: str | Path | None = None,
        show_move_debug: bool = False,
        neutral_elevation: float = 0.0,
    ) -> "Turntable":
        """Attempt to find a turntable by iterating over all available serial ports.

        Raise `TurntableError` if none are successful. This probably means that you are not connected to the turntable,
        or that the turntable is powered off.

        Args:
            baudrate (int, optional): _description_. Defaults to 9600.
            timeout (float | None, optional): _description_. Defaults to None.
            logger (logging.Logger | None, optional): _description_. Defaults to None.
            csv_file_path (str | Path | None, optional): _description_. Defaults to None.
            show_move_debug (bool, optional): _description_. Defaults to False.
            neutral_elevation (float, optional): _description_. Defaults to 0.0.

        Returns:
            Turntable: _description_
        """
        from serial.tools.list_ports import comports

        logger = logger or create_null_logger()
        logger.info("Finding serial connection to turntable...")
        ports = list(comports())
        logger.debug(f"Found {len(ports)} serial ports")
        for port in ports:
            try:
                logger.debug(f"Trying port {port.device}: {port.description}")
                rv = Turntable(
                    port=port.device,
                    baudrate=baudrate,
                    timeout=timeout,
                    logger=logger,
                    csv_file_path=csv_file_path,
                    show_move_debug=show_move_debug,
                    neutral_elevation=neutral_elevation,
                )
                for _ in range(10):
                    position = rv.get_position()
                    if position:
                        logger.info(f"Found turntable at port {port.device}")
                        return rv
                    else:
                        logger.debug(f"Failed to get position from turntable at port {port.device}")
                    time.sleep(0.1)
            except Exception as exc:
                logger.debug(f"Failed to connect to turntable at port {port.device}: {exc}", exc_info=exc)
                continue

        # At this point, we have failed to find the turntable.
        message = "Failed to find turntable."
        logger.error(message)
        raise TurntableError(message)

    def parse_az_el(
        self,
        data: bytes,
    ) -> AzEl | None:
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
            # Line might be partially/completely junk. This removes most of that.
            if b"Pos" not in line:
                continue

            # Line might have garbage before b'Pos'.
            # Example: b'\x00\xbc\x08\x00 \x10\x00\x00\x00\x00\x00Pos= El: -90.00 , Az: 236.66 \r'
            # So split on b'Pos' and take the last part.
            pos_index = line.index(b"Pos")
            line = line[pos_index:]

            # Decode as ASCII. This will fail if RS-232 data was corrupted, which should be rare.
            try:
                string = line.decode(encoding="ascii")
            except UnicodeDecodeError:
                self.logger.debug(f"Failed to decode line {line!r} as ASCII")
                continue

            # Try to match the regex. If it doesn't match, continue.
            # Every line should match, unless it is corrupted or truncated.
            match = azimuth_elevation_regex.search(string)
            if not match:
                # self.logger.debug(f"Failed to match line {string!r} with regex")
                continue

            # At this point, we have a match. Parse it
            groupdict = match.groupdict()
            azimuth_string = groupdict["azimuth"]
            elevation_string = groupdict["elevation"]

            # There are strings that match the regex that are not valid floats, like "123.456" or 98-76".
            # So put them in a try/except.
            try:
                rv = AzEl(azimuth=float(azimuth_string), elevation=float(elevation_string))
                return rv
            except ValueError:
                continue

        # If we get here, we didn't find any valid data.
        return None

    def time_since_last_communication(self) -> float:
        """The time since we last successfully communicated with the turntable, in seconds."""
        return time.monotonic() - self.most_recent_communication_time

    def attempt_read(self) -> bytes | None:
        """
        Attempt to read data from the turntable, returning None if no data is available
        or there is an exception reading from serial.

        Args:
            size (int): The number of bytes to read. Defaults to 1000.

        Returns:
            bytes | None: The data read from the turntable, or None if no data is available.
        """
        # self.logger.debug(f"Attempting to read {size:,} bytes from turntable")
        try:
            in_waiting = self._serial.in_waiting
            if in_waiting < 100:
                # self.logger.debug(f"Only {in_waiting:,} bytes available to read from turntable, below minimum threshold of 100 bytes")
                return None
            else:
                size = in_waiting
                # data = self.read(size)
                data = self._serial.read(size)
        except Exception as exc:
            self.logger.debug(f"Failed to read from turntable: {exc}", exc_info=exc)
        if data:
            # self.logger.debug(f"Read {len(data):,} bytes from turntable")
            return data
        else:
            self.logger.debug("No data read from turntable")
            return None

    def _get_within_regime_position(self) -> AzEl | None:
        """Get the reported azimuth and elevation of the turn table.

        "Reported" here means what the turntable itself reports,
        which is BEFORE the regime offset is applied.

        Return `None` on any failure."""
        data = self.attempt_read()
        if not data:
            return None

        parsed_data = self.parse_az_el(data)
        if not parsed_data:
            return None

        # If we get here, we successfully communicated with the turntable. Update the time.
        # self.logger.debug(
        #     f"Successfully communicated with turntable; updating time. Was {self.most_recent_communication_time}"
        # )
        self.most_recent_communication_time = time.monotonic()

        # if self.csv_file_path:
        #     with self.csv_file_path.open(mode="a", newline="") as csvfile:
        #         writer = csv.DictWriter(csvfile, fieldnames=self.csv_field_names, dialect="unix")
        #         writer.writerow(
        #             {
        #                 "timestamp": datetime.datetime.now(tz=datetime.timezone.utc),
        #                 "azimuth": parsed_data.azimuth,
        #                 "elevation": parsed_data.elevation,
        #             }
        #         )
        # self.logger.debug(f"Updated time to {self.most_recent_communication_time}")

        return parsed_data

    def _wait_for_within_regime_position(self, delay: float = 0.05) -> AzEl:
        """Wait for the turntable to report a position. This is a blocking operation,
        so it could spin forever."""
        while True:
            reported_position = self._get_within_regime_position()
            if reported_position:
                return reported_position
            time.sleep(delay)

    def get_position(self) -> Coordinate | None:
        """Get the current azimuth and elevation of the turn table. Return `None` on any failure.

        Also, update the `most_recent_communication_time` attribute."""
        reported_position = self._get_within_regime_position()
        if not reported_position:
            return None

        actual_position = reported_position
        if not self._current_regime:
            self.logger.warning(f"Regime is not set. Assuming internal elevation is correct.")
            # return reported_position
        else:
            # raise RuntimeError("Current regime is not set. Cannot get a position without a regime.")

            # Apply the regime offset to the reported elevation
            elevation = self._convert_from_regime_elevation(reported_position.elevation)
            actual_position = AzEl(
                azimuth=reported_position.azimuth,
                elevation=elevation,
            )

        # Write to CSV if desired
        if self.csv_file_path:
            with self.csv_file_path.open(mode="a", newline="") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self.csv_field_names, dialect="unix")
                writer.writerow(
                    {
                        "timestamp": datetime.datetime.now(tz=datetime.timezone.utc),
                        "azimuth": actual_position.azimuth,
                        "elevation": actual_position.elevation,
                    }
                )

        rv = Coordinate.from_turntable(
            azimuth=actual_position.azimuth,
            elevation=actual_position.elevation,
            neutral_elevation=self.neutral_elevation,
        )
        return rv

    def wait_for_position(self, delay: float = 0.05) -> Coordinate:
        """Wait for the turntable to report a position. This is a blocking operation,
        so it could spin forever."""
        while True:
            position = self.get_position()
            if position:
                return position
            time.sleep(delay)

    def _validate_elevation_regime_bounds(
        self,
        *,
        absolute_elevation: float | None = None,
        within_regime_elevation: float | None = None,
    ) -> bool:
        """Validate that the given elevation is within the valid range for the turntable's current regime."""
        self.logger.debug(f"Validating elevation regime bounds {absolute_elevation=} {within_regime_elevation=}")
        if absolute_elevation is None and within_regime_elevation is None:
            raise ValueError("Must provide either absolute elevation or within regime elevation.")
        if absolute_elevation is not None and within_regime_elevation is not None:
            raise ValueError("Cannot provide both absolute elevation and within regime elevation.")

        if not self._current_regime:
            raise RuntimeError("Current regime is not set. Cannot validate position without a regime.")

        if within_regime_elevation is None:
            within_regime_elevation = self._convert_to_regime_elevation(absolute_elevation)

        if self.REGIME_ELEVATION_BOUNDS[0] <= within_regime_elevation <= self.REGIME_ELEVATION_BOUNDS[1]:
            pass
        else:
            self.logger.error(
                f"Within regime elevation {within_regime_elevation} is NOT inside within-regime bounds {self.REGIME_ELEVATION_BOUNDS}"
            )
            return False

        return True

    def _validate_absolute_bounds(
        self,
        *,
        absolute_azimuth: float | None = None,
        within_regime_elevation: float | None = None,
        absolute_elevation: float,
    ) -> bool:
        """Validate that the given azimuth and elevation are within the valid physical range for the turntable.

        Approximately -90 to +45 elevation and -175 to +175 azimuth."""
        if absolute_elevation is None:
            absolute_elevation = self._convert_from_regime_elevation(within_regime_elevation)

        # Handle the absolute elevation offset
        if self.neutral_elevation:
            absolute_elevation += self.neutral_elevation

        # Validate azimuth within bounds
        if not self.ABSOLUTE_AZIMUTH_BOUNDS[0] <= absolute_azimuth <= self.ABSOLUTE_AZIMUTH_BOUNDS[1]:
            self.logger.error(f"Azimuth {absolute_azimuth} is out of bounds {self.ABSOLUTE_AZIMUTH_BOUNDS}")
            return False

        # Validate elevation within bounds
        if not self.ABSOLUTE_ELEVATION_BOUNDS[0] <= absolute_elevation <= self.ABSOLUTE_ELEVATION_BOUNDS[1]:
            self.logger.error(f"Elevation {absolute_elevation} is out of bounds {self.ABSOLUTE_ELEVATION_BOUNDS}")
            return False

        # Assume good
        self.logger.debug(f"Azimuth {absolute_azimuth} and elevation {absolute_elevation} are within physical bounds.")
        return True

    def _validate_open_communication(self) -> None:
        """Validate that we have heard from the turntable recently enough."""
        time_since_last_communication = self.time_since_last_communication()
        if time_since_last_communication > self.DEAD_TIME:
            self.logger.error(
                f"Turntable has not been heard from in {time_since_last_communication} seconds, which is more than the allowable {self.DEAD_TIME} seconds"
            )
            self.has_been_set = False
            self._current_regime = None
            return False
        else:
            return True

    def validate_set_command(self, azimuth: float, elevation: float) -> None:
        """Validate that the given azimuth and elevation are both zero. Despite the way the command
        is structured and interpreted, the internal code within the firmware will accept any value,
        but it will always set azimuth and elevation to zero.
        """
        if azimuth == 0 and elevation == 0:
            self.logger.debug(f"Set command {azimuth=}, {elevation=} is valid.")
            return True
        else:
            self.logger.warning(
                f"Set command {azimuth=}, {elevation=} is NOT valid. Azimuth and elevation must both be"
            )
            return False
        # valid_bounds = self._validate_absolute_bounds(
        #     absolute_azimuth=azimuth,
        #     absolute_elevation=elevation,
        # )
        # if not valid_bounds:
        #     return False

        # self.logger.debug(f"Set command {azimuth=}, {elevation=} is valid.")
        # return True

    def _convert_to_regime_elevation(self, elevation: float) -> float:
        """Convert the given elevation to the turntable's internal conception of elevation.

        This will apply the current regime offset to the given elevation."""
        if self._regime_elevation_offset is None:
            raise RuntimeError("Regime elevation offset is not set. Cannot convert elevation.")
        return elevation - self._regime_elevation_offset

    def _convert_from_regime_elevation(self, elevation: float) -> float:
        """Convert the given elevation from the turntable's internal conception of elevation.

        This will apply the current regime offset to the given elevation."""
        if self._regime_elevation_offset is None:
            raise RuntimeError("Regime elevation offset is not set. Cannot convert elevation.")
        return elevation + self._regime_elevation_offset

    def validate_move_command(
        self,
        *,
        azimuth: float,
        absolute_elevation: float | None = None,
        within_regime_elevation: float | None = None,
    ) -> None:
        """Validate that the given azimuth and elevation are within the valid range for the turntable."""

        self.logger.debug(f"Validating move command {azimuth=}, {absolute_elevation=}, {within_regime_elevation=}")
        valid_absolute = self._validate_absolute_bounds(
            absolute_azimuth=azimuth,
            absolute_elevation=absolute_elevation,
            within_regime_elevation=within_regime_elevation,
        )
        if not valid_absolute:
            return False

        valid_regime = self._validate_elevation_regime_bounds(
            absolute_elevation=absolute_elevation,
            within_regime_elevation=within_regime_elevation,
        )
        if not valid_regime:
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
        self.logger.debug(f"Move command {azimuth=}, {absolute_elevation=} is valid.")
        return True

    def _send_move_command(self, azimuth: float, elevation: float, reps: int = 3) -> None:
        """Send a move command to the turntable.
        This elevation should be a regime elevation."""
        command = f"CMD:MOV:{azimuth:.3f},{elevation:.3f};".encode(encoding="ascii")

        if not self.validate_move_command(
            azimuth=azimuth,
            within_regime_elevation=elevation,
        ):
            self.logger.error(f"Move command {azimuth=}, {elevation=} is invalid and WILL NOT BE SENT!")
            return

        self.logger.info(f"Sending move command to turntable: {command!r}")
        for _ in range(reps):
            self._serial.write(command)
            time.sleep(0.05)

    def send_set_command(
        self,
        azimuth: float,
        elevation: float,
        _set_regime: bool = True,
        reps: int = 3,
    ) -> AzEl:
        """Send a set command to the turntable.

        NOTE: Azimuth and elevation both MUST be zero, or the command will be rejected.

        If `_set_regime` is `True`, then set the current elevation regime to the one that contains the given elevation.
        In other words, you should ALWAYS set this if you are setting the turntable to a real elevation, which users should
        generally speaking always be doing. It should only be set to `False` by internal processes.
        """

        if not self.validate_set_command(azimuth, elevation):
            self.logger.error(f"Set command {azimuth=}, {elevation=} is invalid and WILL NOT BE SENT!")
            return

        command = f"CMD:SET:{azimuth:.3f},{elevation:.3f};".encode(encoding="ascii")
        self.logger.info(f"Sending set command to turntable: {command!r} ")
        for _ in range(reps):
            self._serial.write(command)
            time.sleep(0.1)

        # Wait here until we get a response from the turntable. This is a blocking operation.
        set_position = AzEl(azimuth=azimuth, elevation=elevation)
        while True:
            time.sleep(0.10)
            reported_position = self._get_within_regime_position()
            if not reported_position:
                continue

            # Verify that actual_position is within 0.1 degrees of set_position. If so, we're good. If not, keep waiting.
            if abs(reported_position.azimuth - set_position.azimuth) > ALLOWABLE_DISCREPANCY_DEG:
                if self._show_move_debug:
                    self.logger.debug(
                        f"Waiting for reported azimuth to match set azimuth... Azimuth {reported_position.azimuth} is not within {ALLOWABLE_DISCREPANCY_DEG} degrees of {set_position.azimuth}"
                    )
                continue
            if abs(reported_position.elevation - set_position.elevation) > ALLOWABLE_DISCREPANCY_DEG:
                if self._show_move_debug:
                    self.logger.debug(
                        f"Waiting for reported elevation to match set elevation... Elevation {reported_position.elevation} is not within {ALLOWABLE_DISCREPANCY_DEG} degrees of {set_position.elevation}"
                    )
                continue

            self.logger.info(f"Successfully set turntable to {set_position=} {reported_position=}")
            self.has_been_set = True

            if _set_regime:
                self._current_regime = _regime.find_best_regime(reported_position.elevation)
                if self._regime_elevation_offset is None:
                    self._regime_elevation_offset = 0.0
                self.logger.info(f"Set current regime to {self._current_regime}")

            return set_position

    def _move_to_next_regime(
        self,
        *,
        azimuth: float,
        elevation: float,
        azimuth_margin: float = ALLOWABLE_DISCREPANCY_DEG,
        elevation_margin: float = ALLOWABLE_DISCREPANCY_DEG,
        delay: float = 0.05,
    ) -> None:
        assert self._current_regime is not None

        next_regime = _regime.find_next_regime(
            destination_angle=elevation,
            current_regime=self._current_regime,
        )

        # The way regimes are defined, this point will always be in the current regime...
        next_regime_center_elevation = next_regime.center_angle
        self.logger.info(f"Moving to closest waypoint {next_regime_center_elevation} in next regime {next_regime}")

        # ...but lets check it anyway
        assert next_regime_center_elevation in self._current_regime, (
            f"{next_regime_center_elevation=} {self._current_regime=}"
        )

        # Move to the closest waypoint in the neighboring regime.
        self.move_to(
            azimuth=azimuth,
            elevation=next_regime_center_elevation,
            azimuth_margin=azimuth_margin,
            elevation_margin=elevation_margin,
            delay=delay,
        )

        within_regime_position = self._wait_for_within_regime_position()

        # Let's sanity check that the current point (very near a waypoint)
        # is within both of its neighbors regimes
        # within_regime_position.elevation = within_regime_position.elevation
        real_elevation = self._convert_from_regime_elevation(within_regime_position.elevation)
        assert real_elevation in self._current_regime, (
            f"{within_regime_position.elevation=} {real_elevation=} {self._current_regime=}"
        )
        assert real_elevation in next_regime, f"{within_regime_position.elevation=} {real_elevation=} {next_regime=}"

        # Do the elevation offset math now. This is a fiddly thing, so be careful.
        if self._regime_elevation_offset is None:
            new_regime_elevation_offset = within_regime_position.elevation
            self.logger.info(
                f"Setting regime elevation offset to {within_regime_position.elevation}. Was previously None."
            )
            self._regime_elevation_offset = new_regime_elevation_offset
        else:
            new_regime_elevation_offset = self._regime_elevation_offset + within_regime_position.elevation
            self.logger.info(
                f"Setting regime elevation offset to {new_regime_elevation_offset}. Was previously {self._regime_elevation_offset}. This is being set by {within_regime_position.elevation=}"
            )
            self._regime_elevation_offset = new_regime_elevation_offset

        # Set the position to the same azimuth, but elevation 0
        # VERY IMPORTANT!!!: Do NOT set the regime here, since there is now divergence
        # between the table's internal conception of its elevation and its actual elevation.
        self.send_set_command(
            azimuth=azimuth,
            elevation=0.0,
            _set_regime=False,
        )

        self.logger.warning(
            f"Moved from regime {self._current_regime} to next regime {next_regime} with elevation offset {self._regime_elevation_offset}"
        )
        self._current_regime = next_regime

    def move_to(
        self,
        *,
        azimuth: float,
        elevation: float,
        azimuth_margin: float = ALLOWABLE_DISCREPANCY_DEG,
        elevation_margin: float = ALLOWABLE_DISCREPANCY_DEG,
        delay: float = 0.05,
    ) -> AzEl:
        """Move to the given azimuth and elevation. Return the final position."""

        # Determine if this proposed movement
        # will require a regime change.
        if not self._current_regime:
            raise RuntimeError("Current regime is not set. Cannot move to a position without a regime.")
        while elevation not in self._current_regime:
            self.logger.warning(
                f"Current regime {self._current_regime} does not contain elevation {elevation}. Moving regimes."
            )
            self._move_to_next_regime(
                azimuth=azimuth,
                elevation=elevation,
                azimuth_margin=azimuth_margin,
                elevation_margin=elevation_margin,
                delay=delay,
            )

        # User will have specified this in real elevation, so convert it to regime elevation.
        within_regime_elevation = self._convert_to_regime_elevation(elevation)

        return self._move_to_within_regime(
            azimuth=azimuth,
            within_regime_elevation=within_regime_elevation,
            azimuth_margin=azimuth_margin,
            elevation_margin=elevation_margin,
            delay=delay,
        )

    def _move_to_within_regime(
        self,
        *,
        azimuth: float,
        within_regime_elevation: float,
        azimuth_margin: float = 0.1,
        elevation_margin: float = 0.1,
        delay: float = 0.05,
    ) -> AzEl:
        """"""
        if not self.validate_move_command(
            azimuth=azimuth,
            within_regime_elevation=within_regime_elevation,
        ):
            message = f"Move command {azimuth=}, {within_regime_elevation=} is invalid and WILL NOT BE SENT!"
            self.logger.error(message)
            raise ValueError(message)

        starting_position = self.wait_for_position()
        if not starting_position:
            self.logger.error("Failed to get current position. Will not send MOVE command.")
            return None

        self._send_move_command(azimuth, within_regime_elevation)

        target_position = AzEl(azimuth=azimuth, elevation=within_regime_elevation)

        while True:
            current_position = self._wait_for_within_regime_position()
            azimuth_delta = abs(current_position.azimuth - azimuth)
            elevation_delta = abs(current_position.elevation - within_regime_elevation)
            if azimuth_delta <= azimuth_margin and elevation_delta <= elevation_margin:
                display_current_az = current_position.azimuth
                display_current_el = current_position.elevation
                display_starting_az = starting_position.azimuth
                display_starting_el = starting_position.elevation
                if self._current_regime is not None:
                    try:
                        display_current_el = self._convert_from_regime_elevation(display_current_el)
                        display_starting_el = self._convert_from_regime_elevation(display_starting_el)
                    except Exception:
                        pass
                display_current_position = AzEl(azimuth=display_current_az, elevation=display_current_el)
                display_starting_position = AzEl(azimuth=display_starting_az, elevation=display_starting_el)
                self.logger.info(f"Successfully moved to {display_current_position} from {display_starting_position}")
                break
            else:
                if self._show_move_debug:
                    display_current_az = current_position.azimuth
                    display_current_el = current_position.elevation
                    display_target_az = target_position.azimuth
                    display_target_el = target_position.elevation
                    if self._current_regime is not None:
                        try:
                            display_current_el = self._convert_from_regime_elevation(display_current_el)
                            display_target_el = self._convert_from_regime_elevation(display_target_el)
                        except Exception:
                            pass

                    self.logger.debug(
                        f"TT moving. cur_az={display_current_az:.2f}, cur_el={display_current_el:.2f}; target_az={display_target_az:.2f}, target_el={display_target_el:.2f}"
                    )
            time.sleep(delay)

        return current_position

    def interactively_center(self) -> None:
        """Manually center the turntable interactively.

        This will clobber the turntable's current understanding of its position,
        and thus it is intended to be the very first thing done when powering the
        table on."""
        print(f"+------------------------------+")
        print(f"|  INTERACTIVE CENTERING MODE  |")
        print(f"+------------------------------+")
        while True:
            _current_regime_position = self._wait_for_within_regime_position()
            _current_regime_azimuth = _current_regime_position.azimuth
            _current_regime_elevation = _current_regime_position.elevation

            _current_absolute_position = None
            try:
                _absolute_azimuth = _current_regime_azimuth
                _absolute_elevation = self._convert_from_regime_elevation(_current_regime_elevation)
                _current_absolute_position = AzEl(azimuth=_absolute_azimuth, elevation=_absolute_elevation)
            except Exception:
                # print(f"Failed to convert to absolute position: {exc}")
                pass
            print(f"[The following numbers may or may not be correct, and they may or may not be meaningful.]")
            print(
                f"Current regime position: {_current_regime_position}. Current absolute position: {_current_absolute_position or 'NOT YET SET'}."
            )
            print(f"self.has_been_set: {self.has_been_set}. Current elevation regime: {self._current_regime}.")
            print(f"What would you like to do? ['HELP' for options]")
            user_input = input("> ").strip()

            input_tokens = [token for token in user_input.split() if token]
            first_token = input_tokens[0]
            if first_token.lower() == "help":
                print("+-----------+")
                print("|  OPTIONS  |")
                print("+-----------+")
                print("")
                print(f"  You can move in a relative way:")
                print(f"MOVE UP 5")
                print(f"MOVE DOWN 5")
                print(f"MOVE LEFT 5")
                print(f"MOVE RIGHT 5")
                print(f"")
                print(f"  You can move in an absolute way:")
                print(f"ABSOLUTE 123.45 -65.432")
                print(f"")
                print(f"  You can SET the current position (azimuth FIRST):")
                print(f"SET 123.45 -65,432")
                print(f"")
                print(f"  You can be DONE with this process")
                print(f"DONE")
                print("")
                continue
            elif first_token.lower() == "done":
                # print("Exiting interactive centering mode.")
                # self.logger.debug("Exiting interactive centering mode.")
                break
            elif first_token.lower() == "absolute":
                try:
                    _absolute_azimuth = float(input_tokens[1])
                    _absolute_elevation = float(input_tokens[2])
                except Exception:
                    print("Invalid input for ABSOLUTE command. Try again.")
                    continue

                user_input = input(
                    f"About to move to azimuth={_absolute_azimuth}, elevation={_absolute_elevation}. Continue [y/n]?\n> "
                ).strip()
                if user_input.lower() != "y":
                    print("User did not confirm.")
                    continue
                self.move_to(azimuth=_absolute_azimuth, elevation=_absolute_elevation)
            elif first_token.lower() == "move":
                if not self.has_been_set:
                    print("\nERROR!! Cannot move until the turntable has been set. Please do a 'SET' command.\n")
                    continue
                try:
                    direction = input_tokens[1].lower()
                    assert direction in ["up", "down", "left", "right"]
                    distance = float(input_tokens[2])
                    assert distance >= 0
                    azimuth_delta = 0
                    if direction == "left":
                        azimuth_delta = -distance
                    elif direction == "right":
                        azimuth_delta = distance
                    elevation_delta = 0
                    if direction == "up":
                        elevation_delta = distance
                    elif direction == "down":
                        elevation_delta = -distance
                except Exception:
                    print(f"Invalid input for MOVE command. Try again.")
                    continue

                if _current_absolute_position is None:
                    _current_absolute_position = self.wait_for_position()

                new_azimuth = _current_absolute_position.azimuth + azimuth_delta
                new_elevation = _current_absolute_position.elevation + elevation_delta
                target_position = AzEl(azimuth=new_azimuth, elevation=new_elevation)

                message = f"About to move"
                if azimuth_delta < 0:
                    message += f" {abs(azimuth_delta)}° LEFT"
                elif azimuth_delta > 0:
                    message += f" {abs(azimuth_delta)}° RIGHT"

                if elevation_delta < 0:
                    message += f" {abs(elevation_delta)}° DOWN"
                elif elevation_delta > 0:
                    message += f" {abs(elevation_delta)}° UP"

                message += f" [Current absolute: {_current_absolute_position}. Target absolute: {target_position}]"

                user_input = input(f"{message}\nContinue [y/n]?\n> ").strip()
                if user_input.lower() != "y":
                    print("User did not confirm.")
                    continue
                self.move_to(azimuth=new_azimuth, elevation=new_elevation)
            elif first_token.lower() == "set":
                try:
                    azimuth = float(input_tokens[1])
                    elevation = float(input_tokens[2])
                except Exception:
                    print("Invalid input for SET command. Try again.")
                    continue

                user_input = input(
                    f"About to SET azimuth={azimuth}, elevation={elevation}. Continue [y/n]?\n> "
                ).strip()
                if user_input.lower() != "y":
                    print("User did not confirm.")
                    continue

                self.send_set_command(azimuth=azimuth, elevation=elevation)
                continue

        print("Exiting interactive centering mode.")
        self.logger.debug("Exiting interactive centering mode.")

    def send_stop_command(
        self,
        *,
        repeat: int = 5,
        delay: float = 0.2,
    ):
        """Send a stop command to the turntable. Repeat the given number of times with the given delay.

        Default is to repeat 5 times with a 0.2 second delay between each command."""
        command = b"p"
        self.logger.warning(f"Sending emergency stop command to turntable: {command!r}")
        for _ in range(repeat):
            self._serial.write(command)
            time.sleep(delay)
        self.logger.warning(f"Sent emergency stop command to turntable: {command!r}")

    def send_emergency_move_command(
        self,
        *,
        azimuth: float = 0.0,
        elevation: float = 0.0,
        reps: int = 3,
    ) -> None:
        """Move to the given azimuth and elevation immediately, without checking if the turntable is ready.

        Intent is that this will be called if the turntable is not responding to commands/the program is suffering
        some fatal error"""
        command = f"CMD:MOV:{azimuth:.3f},{elevation:.3f};".encode(encoding="ascii")
        self.logger.warning(f"Sending emergency move command to turntable: {command!r}")
        for _ in range(reps):
            self._serial.write(command)
            time.sleep(0.2)
        self.logger.warning(f"Sent emergency move command to turntable: {command!r}")


if __name__ == "__main__":
    from msu_ssc import ssc_log

    ssc_log.init(level="DEBUG")
    logger = ssc_log.logger.getChild("turntable")

    tt = Turntable.find(
        logger=logger,
        timeout=1.0,
    )
    tt.interactively_center()

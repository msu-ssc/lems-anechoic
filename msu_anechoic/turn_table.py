import csv
import datetime
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import serial

from msu_anechoic import AzEl
from msu_anechoic import _turn_table_elevation_regime as _regime
from msu_anechoic import create_null_logger

if TYPE_CHECKING:
    import logging


azimuth_elevation_regex = re.compile(r"Pos\s*=\s*El:\s*(?P<elevation>[-\d\.]+)\s*,\s*Az:\s*(?P<azimuth>[-\d\.]+)")
"""Should match a string like `"Pos= El: -0.03 , Az: -0.03\\r\\n"`"""


class Turntable:
    AZIMUTH_BOUNDS = (-175, 175)
    # ELEVATION_BOUNDS = (-85, 45)
    ELEVATION_BOUNDS = (-29.5, 29.5)
    DEAD_TIME = 10.0
    csv_field_names = ["timestamp", "azimuth", "elevation"]

    def __init__(
        self,
        *,
        port: str,
        baudrate: int = 9600,
        timeout: float | None = None,
        logger: "logging.Logger | None" = None,
        csv_file_path: str | Path | None = None,
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

    def read(self, size: int = 1000) -> bytes:
        """Read data from the turntable.

        Allow exceptions to propagate.

        Args:
            size (int): The number of bytes to read. Defaults to 1000.

        Returns:
            bytes: The data read from the turntable.
        """
        # self.logger.debug(f"Attempting to read {size:,} bytes from turntable")
        data = self._serial.read(size)
        # self.logger.debug(f"Read {len(data):,} bytes from turntable")
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
        # self.logger.debug(f"Attempting to read {size:,} bytes from turntable")
        try:
            data = self.read(size)
        except Exception as exc:
            self.logger.debug(f"Failed to read from turntable: {exc}", exc_info=exc)
        if data:
            # self.logger.debug(f"Read {len(data):,} bytes from turntable")
            return data
        else:
            self.logger.debug("No data read from turntable")
            return None

    def _get_reported_position(self) -> AzEl | None:
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

        if self.csv_file_path:
            with self.csv_file_path.open(mode="a", newline="") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self.csv_field_names, dialect="unix")
                writer.writerow(
                    {
                        "timestamp": datetime.datetime.now(tz=datetime.timezone.utc),
                        "azimuth": parsed_data.azimuth,
                        "elevation": parsed_data.elevation,
                    }
                )
        # self.logger.debug(f"Updated time to {self.most_recent_communication_time}")

        return parsed_data

    def _wait_for_reported_position(self, delay: float = 0.05) -> AzEl:
        """Wait for the turntable to report a position. This is a blocking operation,
        so it could spin forever."""
        while True:
            reported_position = self._get_reported_position()
            if reported_position:
                return reported_position
            time.sleep(delay)

    def get_position(self) -> AzEl | None:
        """Get the current azimuth and elevation of the turn table. Return `None` on any failure.

        Also, update the `most_recent_communication_time` attribute."""
        reported_position = self._get_reported_position()
        if not reported_position:
            return None
        
        #TODO: Handle regimes
        return reported_position
    
    def wait_for_position(self, delay: float = 0.05) -> AzEl:
        """Wait for the turntable to report a position. This is a blocking operation,
        so it could spin forever."""
        while True:
            position = self.get_position()
            if position:
                return position
            time.sleep(delay)

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
            self._current_regime = None
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

    def send_set_command(
        self,
        azimuth: float,
        elevation: float,
        _set_regime: bool = True,
    ) -> AzEl:
        """Send a set command to the turntable.

        If `_set_regime` is `True`, then set the current elevation regime to the one that contains the given elevation.
        In other words, you should ALWAYS set this if you are setting the turntable to a real elevation, which users should
        generally speaking always be doing. It should only be set to `False` by internal processes.
        """

        if not self.validate_set_command(azimuth, elevation):
            self.logger.error(f"Set command {azimuth=}, {elevation=} is invalid and WILL NOT BE SENT!")
            return

        command = f"CMD:SET:{azimuth:.3f},{elevation:.3f};".encode(encoding="ascii")
        self.logger.info(f"Sending set command to turntable: {command!r}")
        self._serial.write(command)

        # Wait here until we get a response from the turntable. This is a blocking operation.
        set_position = AzEl(azimuth=azimuth, elevation=elevation)
        while True:
            time.sleep(0.05)
            actual_position = self.get_position()
            if not actual_position:
                continue

            # Verify that actual_position is within 0.1 degrees of set_position. If so, we're good. If not, keep waiting.
            if abs(actual_position.azimuth - set_position.azimuth) > 0.1:
                # self.logger.debug(
                #     f"Waiting for reported azimuth to match set azimuth... Azimuth {actual_position.azimuth} is not within 0.1 degrees of {set_position.azimuth}"
                # )
                continue
            if abs(actual_position.elevation - set_position.elevation) > 0.1:
                # self.logger.debug(
                #     f"Waiting for reported elevation to match set elevation... Elevation {actual_position.elevation} is not within 0.1 degrees of {set_position.elevation}"
                # )
                continue

            self.logger.info(f"Successfully set turntable to {set_position=} {actual_position=}")
            self.has_been_set = True

            if _set_regime:
                self._current_regime = _regime.find_best_regime(actual_position.elevation)
                self.logger.info(f"Set current regime to {self._current_regime}")

            return set_position

    def _move_to_next_regime(
        self,
        *,
        azimuth: float,
        elevation: float,
        azimuth_margin: float = 0.1,
        elevation_margin: float = 0.1,
        delay: float = 0.05,
    ) -> None:
        assert self._current_regime is not None
        
        next_regime = _regime.find_next_regime(
            destination_angle=elevation,
            current_regime=self._current_regime,
        )

        # Find the closest waypoint in the next regime to the current elevation.
        # The way regimes are defined, this point will always be in the current regime...
        waypoint_elevation = next_regime.get_closest_waypoint(elevation)
        self.logger.info(f"Moving to closest waypoint {waypoint_elevation} in next regime {next_regime}")

        # ...but lets check it anyway
        assert waypoint_elevation in self._current_regime, f"{waypoint_elevation=} {self._current_regime=}"

        # Move to the closest waypoint in the neighboring regime.
        self.move_to(
            azimuth=azimuth,
            elevation=waypoint_elevation,
            azimuth_margin=azimuth_margin,
            elevation_margin=elevation_margin,
            delay=delay,
        )

        reported_position = self.wait_for_position()

        # Let's sanity check that the current point (nery near a waypoint)
        # is within both of its neighbors regimes
        assert reported_position.elevation in self._current_regime
        assert reported_position.elevation in next_regime

        # Do the elevation offset math now. This is a fiddly thing, so be careful.
        if self._regime_elevation_offset is None:
            self.logger.info(f"Setting regime elevation offset to {reported_position.elevation}. Was previously None.")
            new_regime_elevation_offset = -reported_position.elevation
            self._regime_elevation_offset = new_regime_elevation_offset
        else:
            new_regime_elevation_offset = self._regime_elevation_offset - reported_position.elevation
            self.logger.info(f"Adjusting regime elevation offset by {new_regime_elevation_offset}. Was previously {self._regime_elevation_offset}")
            self._regime_elevation_offset = new_regime_elevation_offset

        # Set the position to the same azimuth, but elevation 0
        self.send_set_command(azimuth=azimuth, elevation=0.0, _set_regime=False,)

        self.logger.warning(f"Moved from regime {self._current_regime} to next regime {next_regime} with elevation offset {self._regime_elevation_offset}")
        self._current_regime = next_regime

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

        # Determine if this is requires a regime change.
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

        if not self.validate_move_command(azimuth, elevation):
            self.logger.error(f"Move command {azimuth=}, {elevation=} is invalid and WILL NOT BE SENT!")
            return None

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

    def interactively_center(self) -> AzEl:
        """Manually center the turntable interactively.

        This will clobber the turntable's current understanding of its position,
        and thus it is intended to be the very first thing done when powering the
        table on."""
        print(f"+------------------------------+")
        print(f"|  INTERACTIVE CENTERING MODE  |")
        print(f"+------------------------------+")
        while True:
            time.sleep(0.1)
            position = self.get_position()
            if not position:
                continue
            print(f"Current position: {position}")
            user_input = input("Enter azimuth and elevation deltas, separated by a comma, or DONE to finish: ").strip()
            if user_input.lower() == "done":
                print(f"Done. Setting current position to (0, 0)")
                self.send_set_command(azimuth=0.0, elevation=0.0)
                print(f"Successfully completed interactive centering.")
                break
            try:
                azimuth_delta, elevation_delta = user_input.split(",")
                azimuth_delta = float(azimuth_delta)
                elevation_delta = float(elevation_delta)
            except Exception:
                print("Invalid input. Try again.")
                continue

            az_direction = "CLOCKWISE" if azimuth_delta >= 0 else "COUNTERCLOCKWISE"
            el_direction = "UP" if elevation_delta >= 0 else "DOWN"

            user_input = input(
                f"About to move {az_direction} {abs(azimuth_delta)} degrees and {el_direction} {abs(elevation_delta)} degrees.\nContinue [y/n]?"
            )
            if user_input.lower() != "y":
                print("User did not confirm.")
                continue

            print(f"Setting position to (0, 0)")
            self.send_set_command(azimuth=0.0, elevation=0.0)

            print(f"Moving to azimuth={azimuth_delta=}, elevation={elevation_delta=}")
            self.move_to(azimuth=azimuth_delta, elevation=elevation_delta)

        position = self.send_set_command(azimuth=0.0, elevation=0.0)
        return position

    def send_emergency_stop_command(
        self,
        *,
        repeat: int = 5,
        delay: float = 0.2,
    ):
        """Send an emergency stop command to the turntable. Repeat the given number of times with the given delay.

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
    ) -> None:
        """Move to the given azimuth and elevation immediately, without checking if the turntable is ready.

        Intent is that this will be called if the turntable is not responding to commands/the program is suffering
        some fatal error"""
        command = f"CMD:MOV:{azimuth:.3f},{elevation:.3f};".encode(encoding="ascii")
        self.logger.warning(f"Sending emergency move command to turntable: {command!r}")
        self._serial.write(command)
        self.logger.warning(f"Sent emergency move command to turntable: {command!r}")


if __name__ == "__main__":
    from msu_ssc import ssc_log

    ssc_log.init(level="INFO")
    logger = ssc_log.logger.getChild("turntable")
    try:
        tt = Turntable(port="COM5", logger=logger, timeout=1.0)

        while True:
            position = tt.get_position()
            print(
                f"{position=} {tt.time_since_last_communication()=} {tt.most_recent_communication_time=} {tt.has_been_set=}"
            )
            time.sleep(0.1)

            if position:
                break
            # tt.move_to(azimuth=170.0, elevation=-30.0)

            # tt.move_to(azimuth=236, elevation=0.0)

        response = tt.send_set_command(
            azimuth=0.0,
            elevation=0.0,
        )
        print(f"{response=}")

        # response = tt.move_to(azimuth=15.0, elevation=0.0)
        # response = tt.move_to(azimuth=0.0, elevation=0.0)
        # while True:
        #     position = tt.get_position()
        #     print(
        #         f"{position=} {tt.time_since_last_communication()=} {tt.most_recent_communication_time=} {tt.has_been_set=}"
        #     )
        #     time.sleep(0.1)

        for distance in [
            # 0.25,
            # 0.50,
            # 0.75,
            # 1.00,
            # 1.25,
            # 1.50,
            # 1.75,
            # 2.00,
            # 2.25,
            # 2.50,
            # 3.00,
            # 4.00,
            # 5.00,
            # 6.00,
            # 7.00,
            # 8.00,
            # 9.00,
            # 10.00,
            15.00,
            20.00,
            25.00,
            30.00,
        ]:
            tt.move_to(azimuth=0.0, elevation=0.0)
            start = time.monotonic()
            tt.move_to(azimuth=distance, elevation=0.0)
            stop = time.monotonic()
            with open("turntable_move_times.txt", "a") as f:
                f.write(f"+AZIMUTH,{distance}, {stop - start}\n")

            tt.move_to(azimuth=0.0, elevation=0.0)
            start = time.monotonic()
            tt.move_to(azimuth=-distance, elevation=0.0)
            stop = time.monotonic()
            with open("turntable_move_times.txt", "a") as f:
                f.write(f"-AZIMUTH,{distance}, {stop - start}\n")

            tt.move_to(azimuth=0.0, elevation=0.0)
            start = time.monotonic()
            tt.move_to(azimuth=0.0, elevation=distance)
            stop = time.monotonic()
            with open("turntable_move_times.txt", "a") as f:
                f.write(f"+ELEVATION,{distance}, {stop - start}\n")

            tt.move_to(azimuth=0.0, elevation=0.0)
            start = time.monotonic()
            tt.move_to(azimuth=0.0, elevation=-distance)
            stop = time.monotonic()
            with open("turntable_move_times.txt", "a") as f:
                f.write(f"-ELEVATION,{distance}, {stop - start}\n")

            tt.move_to(azimuth=0.0, elevation=0.0)
            start = time.monotonic()
            tt.move_to(azimuth=distance, elevation=distance)
            stop = time.monotonic()
            with open("turntable_move_times.txt", "a") as f:
                f.write(f"+BOTH,{distance}, {stop - start}\n")

            tt.move_to(azimuth=0.0, elevation=0.0)
            start = time.monotonic()
            tt.move_to(azimuth=-distance, elevation=-distance)
            stop = time.monotonic()
            with open("turntable_move_times.txt", "a") as f:
                f.write(f"-BOTH,{distance}, {stop - start}\n")

        # start = time.monotonic()
        # for azimuth in np.arange(0.25, 20.25, 0.25):
        #     tt.move_to(azimuth=azimuth, elevation=0.0)
        # stop = time.monotonic()
        # print(f"Took {stop - start} seconds to move 20 degrees RIGHT in 0.25 degree increments")

        # # 1/0  # Force an exception to test emergency move command.

        # start = time.monotonic()
        # tt.move_to(azimuth=0.0, elevation=0.0)
        # stop = time.monotonic()
        # print(f"Took {stop - start} seconds to move 10 degrees DOWN at slew speeds")
    except (KeyboardInterrupt, Exception):
        pass
    finally:
        # logger.error(f"Exception: {exc}", exc_info=exc)
        logger.error("Moving to emergency position")
        tt.send_emergency_move_command(azimuth=0.0, elevation=0.0)

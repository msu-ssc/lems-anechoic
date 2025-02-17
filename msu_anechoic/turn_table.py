from __future__ import annotations

import csv
import datetime
import time
from pathlib import Path
from typing import TYPE_CHECKING

import serial

from msu_anechoic import AzEl
from msu_anechoic import create_null_logger

if TYPE_CHECKING:
    import logging

__all__ = [
    "AzEl",
    "TurnTable",
]


def _parse_az_el(data: bytes) -> AzEl:
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


class TurnTable:
    """Class for interacting with the MSU SSC anechoic chamber turn-table.

    The turn-table controller is a custom thing created by Jody Caudill circa 2023/2024. There is no documentation for it."""

    CSV_FIELDS = ("timestamp", "azimuth", "elevation")

    def __init__(
        self,
        *,
        port: str | None = None,
        baudrate: int | None = None,
        timeout: float | None = None,
        logger: "logging.Logger | None" = None,
        csv_path: Path | None = None,
        allow_clobber_csv: bool = False,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.logger = logger or create_null_logger()

        # Initialize the CSV file
        self.csv_path = csv_path
        if self.csv_path:
            self.csv_path = Path(self.csv_path).expanduser().resolve()
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            if self.csv_path.exists() and not allow_clobber_csv:
                raise FileExistsError(f"CSV file already exists: {self.csv_path}")
            with open(self.csv_path, "w", encoding="utf-8", newline="") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=self.CSV_FIELDS, dialect="unix")
                writer.writeheader()

        # Initialize the serial connection
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
        )

        self._move_number = 0

    def _write_csv_line(
        self,
        location: AzEl,
        timestamp: "datetime.datetime | None" = None,
    ) -> None:
        if not self.csv_path:
            return
        timestamp = timestamp or datetime.datetime.now(tz=datetime.timezone.utc)
        data = {
            "timestamp": timestamp,
            "azimuth": location.azimuth,
            "elevation": location.elevation,
        }
        with open(self.csv_path, "a", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=self.CSV_FIELDS, dialect="unix")
            writer.writerow(data)

    def move_to(
        self,
        *,
        azimuth: float,
        elevation: float,
        azimuth_margin: float = 0.5,
        elevation_margin: float = 0.5,
        delay: float = 0.1,
    ):
        """Move to some given location. On any failure, raise an exception."""
        self._move_number += 1
        command = f"CMD:MOV:{azimuth:.3f},{elevation:.3f};".encode(encoding="ascii")
        self._serial.write(command)
        while True:
            location = self.get_location()
            delta_az = abs(location.azimuth - azimuth)
            delta_el = abs(location.elevation - elevation)
            if delta_az < azimuth_margin and delta_el < elevation_margin:
                return location
            else:
                # self.logger.debug(f"Still moving to {AzEl(azimuth, elevation)}; currently at {location!r}")
                time.sleep(delay)

    def attempt_move_to(
        self,
        *,
        azimuth: float,
        elevation: float,
        azimuth_margin: float = 0.5,
        elevation_margin: float = 0.5,
        delay: float = 0.1,
    ) -> AzEl | None:
        """Attempt to move to some given location. On any failure, returns None."""
        try:
            return self.move_to(
                azimuth=azimuth,
                elevation=elevation,
                azimuth_margin=azimuth_margin,
                elevation_margin=elevation_margin,
                delay=delay,
            )
        except RuntimeError:
            return None

    def get_location(
        self,
    ) -> AzEl:
        """Get the current azimuth and elevation of the turn table. Raise an exception on any failure.

        This is a blocking operation."""
        self.logger.debug("Getting turn table location")
        try:
            turn_table_data = self._serial.read(1000)
            location = _parse_az_el(turn_table_data)
            self.logger.debug(f"Got turn table location: {location!r}")
            self._write_csv_line(location)
            return location
        except Exception as exc:
            message = f"Failed to get turn table location"
            self.logger.error(f"Failed to get turn table location: {exc}", exc_info=exc)
            raise RuntimeError(message) from exc

    def attempt_get_location(self) -> AzEl | None:
        """Attempt to get the current azimuth and elevation of the turn table. Return `None` on any failure."""
        try:
            return self.get_location()
        except RuntimeError:
            return None

    def __repr__(self):
        return f"{self.__class__.__name__}<serial_open={self._serial.is_open}>({self.port=}, {self.baudrate=}, {self.timeout=})"


if __name__ == "__main__":
    from msu_ssc import ssc_log

    ssc_log.init(level="DEBUG")
    logger = ssc_log.logger.getChild("turntable")

    turntable = TurnTable(
        port="COM2",
        baudrate=9600,
        # timeout=0.01,
        logger=logger,
    )
    print(f"{turntable=}")
    print(f"{turntable._serial=}")

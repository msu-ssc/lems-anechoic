import time
from typing import NamedTuple

import serial
from msu_ssc import ssc_log

__all__ = [
    "AzEl",
    "TurnTable",
]


class AzEl(NamedTuple):
    """Azimuth and elevation in degrees."""

    azimuth: float
    elevation: float


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


class TurnTable(serial.Serial):
    """Class for interacting with the MSU SSC anechoic chamber turn-table.

    The turn-table controller is a custom thing created by Jody Caudill circa 2023/2024. There is no documentation for it."""

    def move_to(
        self,
        *,
        azimuth: float,
        elevation: float,
        azimuth_margin: float = 0.5,
        elevation_margin: float = 0.5,
        delay: float = 0.1,
    ):
        """Move to some given location."""
        command = f"CMD:MOV:{azimuth:.3f},{elevation:.3f};".encode(encoding="ascii")
        self.write(command)
        while True:
            location = self.get_location()
            delta_az = abs(location.azimuth - azimuth)
            delta_el = abs(location.elevation - elevation)
            if delta_az < azimuth_margin and delta_el < elevation_margin:
                return location
            else:
                # ssc_log.debug(f"Still moving to {AzEl(azimuth, elevation)}; currently at {location!r}")
                time.sleep(delay)

    def get_location(
        self,
    ) -> AzEl | None:
        """Get the current azimuth and elevation of the turn table.

        This is a blocking operation."""
        ssc_log.debug("Getting turn table location")
        try:
            turn_table_data = self.read(1000)
            location = _parse_az_el(turn_table_data)
            ssc_log.debug(f"Got turn table location: {location!r}")
            return location
        except Exception as exc:
            message = f"Failed to get turn table location"
            ssc_log.error(f"Failed to get turn table location: {exc}", exc_info=exc)
            raise RuntimeError(message) from exc


if __name__ == "__main__":
    turntable = TurnTable(
        port="COM2",
        baudrate=9600,
        # timeout=0.01,
    )
    print(f"{turntable=}")

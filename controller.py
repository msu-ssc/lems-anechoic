"""
Code originally written by Jody Caudill.

Unknown (as of January 2025) what the original purpose of this code was, or what precisely the dependencies are.
"""

import datetime
import pickle
import winsound
from pathlib import Path
from typing import NamedTuple
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
import pyvisa
import serial
from msu_ssc import ssc_log

# CONFIGURATION
# Change these constants to match your actual setup
SPEC_AN_GPIB_ADDRESS = "GPIB1::18::INSTR"
TURN_TABLE_SERIAL_PORT = "COM7"
TURN_TABLE_BAUD_RATE = 9600
AZIMUTH_MARGIN = 0.5
ELEVATION_MARGIN = 0.5
LOG_FOLDER = (
    Path(__file__).parent / "./logs/"
)  # This will be a folder called `logs` in the same directory as this script


# Log to a file and also to the screen
ssc_log.init(
    plain_text_file_path=LOG_FOLDER / ssc_log.utc_filename_timestamp(prefix="anechoic"),
    level="DEBUG",
)
ssc_log.debug(f"{SPEC_AN_GPIB_ADDRESS=}")
ssc_log.debug(f"{TURN_TABLE_SERIAL_PORT=}")
ssc_log.debug(f"{TURN_TABLE_BAUD_RATE=}")


class AzEl(NamedTuple):
    """Azimuth and elevation in degrees."""

    azimuth: float
    elevation: float


def get_turn_table_location() -> AzEl | None:
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
) -> AzEl:
    """Move to some given location, with a margin of error for both azimuth and elevation.

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


collected_data = []


def gather_data(
    points: Sequence[AzEl],
):
    """Move to each point in `points` and gather data."""
    for index, commanded_point in enumerate(points):
        actual_point = move_to(
            azimuth=commanded_point.azimuth,
            elevation=commanded_point.elevation,
            azimuth_margin=AZIMUTH_MARGIN,
            elevation_margin=ELEVATION_MARGIN,
        )

        # TODO: Need to find trace min/max frequencies so we can set the span
        # I know this is in some of Christo's code

        trace_data_raw: str = spectrum_analyzer.query("TRA?").split(",")
        timestamp = datetime.datetime.now(tz=datetime.timezone.utc)
        trace_data_values = [float(point) for point in trace_data_raw.split(",")]
        ssc_log.debug(f"Collected data for {commanded_point}. Max value: {max(trace_data_values)}")
        collected_data.append({
            "commanded_azimuth": commanded_point.azimuth,
            "commanded_elevation": commanded_point.elevation,
            "actual_azimuth": actual_point.azimuth,
            "actual_elevation": actual_point.elevation,
            "timestamp": timestamp,
            "trace_data": trace_data_values,
        })


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


resource_manager = pyvisa.ResourceManager()

spectrum_analyzer = resource_manager.open_resource(SPEC_AN_GPIB_ADDRESS)

turn_table = serial.Serial(TURN_TABLE_SERIAL_PORT, TURN_TABLE_BAUD_RATE)

# # ORIGINAL CODE BELOW
# exit()


# values = [0, 0]

# # def move_command(azimuth: float, elevation: float) -> bytes:
# #     return f"CMD:MOV:{azimuth:.3f},{elevation:.3f};".encode()

# # def move_to(
# #     azimuth: float,
# #     elevation: float,
# #     azimuth_margin: float = 0.5,
# #     elevation_margin: float = 0.5,
# # ):
# #     command = move_command(azimuth, elevation)
# #     turn_table.write(command)
# #     while True:
# #         pass

# print("Initialized")
# print("Moving to initial point")
# # for i in range(100):
# while values[1] > -177.5:
#     try:
#         a = turn_table.read(1000)
#         b = str(a, "ascii")
#         point1 = b.index("El:")
#         point2 = b.index("\r", point1)
#         parts = [i.strip() for i in b[point1:point2].split(",")]
#         values = [float(i.split(" ")[1]) for i in parts]
#         print(values)
#         # print(values)
#     except ValueError:
#         continue
# print("Setup Ready")
# turn_table.write(b"CMD:MOV:180.000,0.000;")

# az = []
# val = []
# print("Collecting Data")
# while values[1] < 179.5:
#     try:
#         a = turn_table.read(1000)
#         b = str(a, "ascii")
#         point1 = b.index("El:")
#         point2 = b.index("\r", point1)
#         parts = [i.strip() for i in b[point1:point2].split(",")]
#         values = [float(i.split(" ")[1]) for i in parts]

#         traceDataRaw = spectrum_analyzer.query("TRA?").split(",")
#         maxVal = max([float(i) for i in traceDataRaw])
#         val.append(maxVal)
#         az.append(values[1])
#         print("Gathered Data Point")
#         print(values)
#     except ValueError:
#         continue
#     except KeyboardInterrupt:
#         break
# print("Data Collected")
# az = np.array(az)
# az = np.deg2rad(az)
# val = np.array(val)
# print(az)
# print(val)

# data = {"az": az, "mag": val}
# with open("ANT1_Rolled-8.16625_360_90Pol.pkl", "wb") as outFile:
#     pickle.dump(data, outFile)


# print("Output File Created")
# print("Plotting")
# fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
# ax.plot(az, val)
# # ax.set_rmax(2)
# # ax.set_rticks([0.5, 1, 1.5, 2])  # Less radial ticks
# ax.set_rlabel_position(-22.5)  # Move radial labels away from plotted line
# ax.grid(True)

# ax.set_title("AUT Pattern", va="bottom")
# winsound.Beep(2500, 250)
# plt.show()
# print("Complete")


# # for i in range()

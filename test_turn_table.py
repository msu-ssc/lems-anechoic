"""Test that the turntable is working."""

import datetime
import time
import serial
from msu_ssc import ssc_log

from controller import AzEl  # noqa: F401
from controller import get_turn_table_location  # noqa: F401
from controller import move_to  # noqa: F401

if __name__ == "__main__":
    ssc_log.init(level="DEBUG")

    # TODO: Determine what (if any) other points should be tested.
    # These values are from Jody's original code.
    target_points = [
        AzEl(azimuth=-178.0, elevation=0),
        AzEl(azimuth=180, elevation=0),
    ]
    com_port = "COM7"
    baud_rate = 9600

    ssc_log.info(f"Opening serial port {com_port} at {baud_rate} baud")
    try:
        turn_table = serial.Serial("COM7", 9600)
    except serial.SerialException as exc:
        ssc_log.error(f"Failed to open serial port: {exc}")
        turn_table = None
        import random

        random.seed(40351)

    ssc_log.info(f"{turn_table=} {type(turn_table)=}")

    try:
        start_location = get_turn_table_location(turn_table)
        assert start_location is not None, "Failed to get turn table location"
    except Exception as exc:
        ssc_log.error(f"Failed to get turn table location: {exc}")
        start_location = AzEl(azimuth=float("nan"), elevation=float("nan"))

    ssc_log.info(f"Starting at {start_location!r}")
    overall_start_time = time.monotonic()

    for target_point in target_points:
        movement_start_time = time.monotonic()
        ssc_log.info(f"Moving to {target_point!r} . . . ")
        if turn_table:
            actual_point = move_to(
                azimuth=target_point.azimuth,
                elevation=target_point.elevation,
                turn_table=turn_table,
            )
        else:
            actual_point = AzEl(
                azimuth=target_point.azimuth + random.random(), elevation=target_point.elevation + random.random()
            )
            time.sleep(random.random() * 5)

        movement_end_time = time.monotonic()
        movement_elapsed_time = movement_end_time - movement_start_time
        ssc_log.info(f"Moved to {actual_point!r} in {movement_elapsed_time:.2f} seconds")
        # location = get_turn_table_location(turn_table)
        # ssc_log.debug(f"Arrived at {location!r}")

"""Script to test that the turntable controller is working.

Written by David Mayo, 2025-02-06"""

import csv
import getpass
import os
import platform
import sys
import time
from pathlib import Path

import serial
from msu_ssc import ssc_log
from serial.tools import list_ports

from controller import AnechoicConfig
from controller import AzEl
from controller import get_turn_table_location
from controller import move_to


def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    ssc_log.critical(
        f"Fatal exception occurred, killing the program immediately.", exc_info=(exc_type, exc_value, exc_traceback)
    )


sys.excepthook = handle_exception


if __name__ == "__main__":
    log_file_name = ssc_log.utc_filename_timestamp(prefix="test_turn_table")
    log_file_path = Path(f"./logs/{log_file_name}").expanduser().resolve()
    ssc_log.init(level="DEBUG", plain_text_file_path=log_file_path)
    ssc_log.warning(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    ssc_log.warning(f"!!                                                                                    !!")
    ssc_log.warning(f"!!           If you do NOT make it to 'Attempting to connect to turn table',          !!")
    ssc_log.warning(f"!!  then there's something wrong with this program/your computer, NOT the turn table. !!")
    ssc_log.warning(f"!!                                                                                    !!")
    ssc_log.warning(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

    ssc_log.info("")
    ssc_log.info("==================== DEBUG INFO ====================")
    ssc_log.info(f"Running script {__file__!r}")
    ssc_log.info(f"Python info: sys.version={sys.version!r}")
    ssc_log.info(f"Python info: sys.executable={sys.executable!r}")
    ssc_log.debug(f"Invocation info: sys.argv={sys.argv!r}")
    ssc_log.info(f"Invocation info: os.getcwd()={os.getcwd()!r}")
    ssc_log.debug(f"Platform info: platform.platform()={platform.platform()!r}")
    ssc_log.debug(f"Platform info: platform.node()={platform.node()!r}")
    ssc_log.debug(f"Platform info: getpass.getuser()={getpass.getuser()!r}")

    ssc_log.info("")
    ssc_log.info("==================== FIND SERIAL PORTS ====================")
    ports = list_ports.comports()
    com_port_names = [port.device for port in ports]
    ssc_log.info(f"Found {len(ports)} serial ports:")
    for port in ports:
        ssc_log.info(f"  {port.device}: {port.description}")

    ssc_log.info("")
    ssc_log.info("==================== LOAD CONFIG ====================")
    config = AnechoicConfig.from_json()
    ssc_log.init(level=config.LOG_LEVEL)
    ssc_log.info(f"Config loaded. {config.TURN_TABLE_SERIAL_PORT=} {config.TURN_TABLE_BAUD_RATE=}")

    for key, value in config.asdict().items():
        ssc_log.debug(f"  Config entry: {key!r}={value!r}")
        pass

    ssc_log.info("")
    ssc_log.info("==================== CONNECT TO TURN-TABLE ====================")
    ssc_log.info(f"Opening serial port {config.TURN_TABLE_SERIAL_PORT} at {config.TURN_TABLE_BAUD_RATE} baud")
    turn_table = None
    try:
        turn_table = serial.Serial(config.TURN_TABLE_SERIAL_PORT, config.TURN_TABLE_BAUD_RATE)
    except serial.SerialException as exc:
        ssc_log.error(f"Failed to open serial port. {exc}", exc_info=exc)
        ssc_log.critical(f"Fatal error, program will terminate immediately.")
        sys.exit(1)

    ssc_log.info(f"{turn_table=} {type(turn_table)=}")

    ssc_log.info("")
    ssc_log.info("==================== QUERYING TURN-TABLE ====================")
    try:
        start_location = get_turn_table_location(turn_table)
        assert start_location is not None, "Failed to get initial turn table location."
    except Exception as exc:
        ssc_log.error(f"Failed to get initial turn table location: {exc}")
        start_location = AzEl(azimuth=float("nan"), elevation=float("nan"))

    ssc_log.info("")
    ssc_log.info("==================== MOVING TURN-TABLE ====================")
    # TODO: Determine what (if any) other points should be tested.
    # The endpoints of -178 and +180 were in Jody's original code.
    step_points = [AzEl(azimuth=azimuth, elevation=0) for azimuth in range(-170, 180, 10)]

    target_points = [AzEl(azimuth=-178.0, elevation=0)] + step_points + [AzEl(azimuth=180.0, elevation=0)]
    ssc_log.info(f"Starting at {start_location!r}")
    overall_start_time = time.monotonic()
    ssc_log.debug(f"Starting test at {overall_start_time} (time.monotonic())")

    data_file_path = config.data_folder_path / f"test_turn_table_{ssc_log.file_timestamp()}.csv"
    ssc_log.info(f"Writing data to {data_file_path!r}")
    if not data_file_path.exists():
        ssc_log.debug(f"Creating folder {data_file_path.parent}")
        data_file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(data_file_path, "w", newline="") as data_file:
        csv_dict_writer = csv.DictWriter(
            data_file,
            fieldnames=[
                "commanded_azimuth",
                "commanded_elevation",
                "actual_azimuth",
                "actual_elevation",
                "azimuth_error",
                "elevation_error",
                "movement_start_time",
                "movement_end_time",
            ],
            dialect="unix",
        )
        csv_dict_writer.writeheader()

        for target_point_index, target_point in enumerate(target_points, start=1):
            movement_start_time = time.monotonic()
            ssc_log.info(
                f"Moving to target point {target_point_index} of {len(target_points)}: {target_point!r} . . . "
            )
            try:
                actual_point = move_to(
                    azimuth=target_point.azimuth,
                    elevation=target_point.elevation,
                    turn_table=turn_table,
                )
            except Exception:
                # # NOTE: This commented out code is some code to simulate the turn table moving to a random point
                # # by adding some random az/el error, and delaying a random amount of time.
                # #
                # # The point of that is to allow me to test this script, even without a working turn-table.
                # # -David Mayo, 2025-02-06

                # import random
                # import time
                #
                # time.sleep(random.random())   # Delay a random time between 0 and 1 seconds
                # actual_point = AzEl(
                #     azimuth=target_point.azimuth + (random.random() - 0.5) * 2 * config.AZIMUTH_MARGIN,
                #     elevation=target_point.elevation + (random.random() - 0.5) * 2 * config.ELEVATION_MARGIN,
                # )

                raise  # If using the random error code, comment out this line.

            movement_end_time = time.monotonic()
            movement_elapsed_time = movement_end_time - movement_start_time
            azimuth_error = actual_point.azimuth - target_point.azimuth
            elevation_error = actual_point.elevation - target_point.elevation
            ssc_log.info(
                f"  Moved to az={actual_point.azimuth:.3f} el={actual_point.azimuth:.3f} [error: az={azimuth_error:.3f}, el={elevation_error:.3f}] in {movement_elapsed_time:.3f} seconds"
            )

            data = {
                "commanded_azimuth": target_point.azimuth,
                "commanded_elevation": target_point.elevation,
                "actual_azimuth": actual_point.azimuth,
                "actual_elevation": actual_point.elevation,
                "azimuth_error": azimuth_error,
                "elevation_error": elevation_error,
                "movement_start_time": movement_start_time,
                "movement_end_time": movement_end_time,
            }
            ssc_log.debug(f"Writing data to CSV: {data!r}")
            csv_dict_writer.writerow(data)

    ssc_log.info("")
    ssc_log.info("==================== FINISHED ====================")
    ssc_log.info(f"Test finished successfully!")
    ssc_log.info(f"Data written to {data_file_path}.")
    ssc_log.info(f"Log written to  {log_file_path}")
    ssc_log.info(f"Script {__file__} exiting.")
    sys.exit(0)

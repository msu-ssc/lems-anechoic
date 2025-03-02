R"""
This is a script for the SSE 442L demo.

Quick start guide:

```
# You have to be on a Windows computer.

# Install `git` and `python` on your computer
# Figure this out yourself.

# Install PyVISA/GPIB requirements
# This is for the Spectrum Analyzer
# This is a manual process, which we have another document for. Ask David Mayo for it.

# Copy this repository and its code
cd C:\path\to\where\you\want\this\code
git clone https://github.com/msu-ssc/lems-anechoic.git
cd lems-anechoic

# Get the correct branch
git checkout mayo-experiment
git pull

# Make a Python virtual environment
python -m venv .venv
source .venv\bin\activate

# Install the requirements
.venv\Scripts\python -m pip install .

# Physically connect the spectrum analyzer and turntable to your computer via USB

# Determine the COM port of the turntable
# Find this in Windows Device Manager

# Run this script
.venv\Scripts\python lab.py
```
"""

# Import things

import csv
import datetime

import numpy as np
import rich.progress

# `msu_ssc` is a package of generic Python utilities. It's on GitHub.
from msu_ssc import ssc_log

# `msu_anechoic` is the stuff in this repository, in the `msu_anechoic` folder.
from msu_anechoic.spec_an import SpectrumAnalyzerHP8563E
from msu_anechoic.turn_table import Turntable

# Set up logging
# I (David Mayo) am going to make this a lot easier to do for people who don't know about
# Python logging. But this is how it is now.
ssc_log.init(
    level="DEBUG",
    plain_text_file_path="lab.log",
    jsonl_file_path="lab.jsonl",
)
lab_logger = ssc_log.logger.getChild("lab")
spec_an_logger = ssc_log.logger.getChild("spec_an")
turntable_logger = ssc_log.logger.getChild("turntable")

# Constants (capital letters)
NOMINAL_CENTER_FREQUENCY = 8_450_000_000
"""Actual center frequency will vary by ~500 Hz"""

SPEC_AN_REFERENCE_LEVEL = -30

TURNTABLE_COM_PORT = "COM5"
"""This will be different on your computer. Find it in Windows Device Manager."""

LAB_DATA_PATH = "lab_data.csv"
LAB_DATA_FIELDS = [
    "timestamp_utc",
    "commanded_azimuth",
    "commanded_elevation",
    "actual_azimuth",
    "actual_elevation",
    "center_frequency",
    "center_amplitude",
    "peak_frequency",
    "peak_amplitude",
    "cut_id",
]

# Connect to the spectrum analyzer
spectrum_analyzer = SpectrumAnalyzerHP8563E.find(
    logger=spec_an_logger,
    log_query_messages=False,
)
if not spectrum_analyzer:
    raise ValueError("No spectrum analyzer found")

# Configure the spectrum analyzer
# Move the center frequency to the peak, starting with a 1 MHz span and going down to 1 kHz in steps
spectrum_analyzer.set_reference_level(SPEC_AN_REFERENCE_LEVEL)
center_frequency = spectrum_analyzer.move_center_to_peak(
    center_frequency=NOMINAL_CENTER_FREQUENCY,
    spans=(
        1_000_000,
        100_000,
        10_000,
        1_000,
    ),
    delay=3,
)

spec_an_logger.setLevel("INFO")

# Connect to the turntable
turntable = Turntable(
    port=TURNTABLE_COM_PORT,
    logger=turntable_logger,
    timeout=1.0,
    csv_file_path="lab_turntable.csv",
)

# Turntable must be monitored by a person at all times!
# It is "dumb", and it will happily destroy itself if you tell it to.
# So, we put the whole test in this `try...except` block where, if there is any error
# OR if the user presses Ctrl+C, we will send an emergency stop command to
# the turntable.
#
# THIS SCHEME IS NOT FOOLPROOF!! YOU MUST BE WATCHING THE TURNTABLE AT ALL TIMES!!!
try:
    # Center the turntable as best you can, visually.
    # This method will print some stuff on the screen and ask you to type in some numbers
    # to guide you to the center.
    center_location = turntable.interactively_center()

    # Center the turntable using the spectrum analyzer
    # NOTE: For the lab, we'll skip this because it's slow and doesn't yet work well.
    # For the AUT, the center is very close to the actual center, so this is fine.
    #
    # center_location = user_guided_box_scan(
    #     turntable=turntable,
    #     spectrum_analyzer=spectrum_analyzer,
    # )

    # Move to the center location
    turntable.move_to(azimuth=center_location.azimuth, elevation=center_location.elevation)

    # Set current position to be center
    turntable.send_set_command(azimuth=0, elevation=0)

    ##########################################
    #                                        #
    #     YOUR TEST CODE GOES BELOW HERE     #
    #                                        #
    ##########################################

    # Make the CSV file to store results
    with open(LAB_DATA_PATH, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LAB_DATA_FIELDS, dialect="unix")
        writer.writeheader()

    # Iterate over all the points you care about
    points: list[tuple[float, float, str]] = []

    # PROTIP: When using np.linspace, the center point will be included if and only if
    # you use an odd number of points.
    # for azimuth in np.linspace(-150, 150, 301):
    #     points.append((azimuth, 0, "azimuth-cut"))
    for elevation in np.arange(-85, 42.5, 2.5):
        points.append((0, elevation, "elevation-cut"))

    # Give used a very rough estimate of how long this will take,
    # based on the assumption that each point will take 4 seconds.
    seconds = len(points) * 4
    print(f"You are sampling {len(points):,} points. This will take about {seconds:0.2f} seconds = {seconds/60:0.2f} minutes = {seconds/3600:0.2f} hours.")
    user_input = input("Continue? [y/n]: ")
    if user_input.lower() != "y":
        raise KeyboardInterrupt("User aborted test")

    with rich.progress.Progress() as progress:
        task_id = progress.add_task(f"Collecting data ({len(points):,} points)", total=len(points))
        for point_index, (azimuth, elevation, cut_id) in enumerate(points):
            # Move the turntable to the correct point
            turntable.move_to(azimuth=azimuth, elevation=elevation)

            # Make a Python dictionary to store the data for this point
            data = {}
            data["timestamp_utc"] = datetime.datetime.now(datetime.timezone.utc)
            data["cut_id"] = cut_id

            # Get the actual position of the turntable, which should
            # be within 0.1 degrees of the commanded position
            actual_azimuth, actual_elevation = turntable.get_position()
            data["commanded_azimuth"] = azimuth
            data["commanded_elevation"] = elevation
            data["actual_azimuth"] = actual_azimuth
            data["actual_elevation"] = actual_elevation

            # Collect data from the spec_an
            data["center_frequency"] = center_frequency
            data["center_amplitude"] = spectrum_analyzer.get_center_frequency_amplitude()
            peak_frequency, peak_amplitude = spectrum_analyzer.get_peak_frequency_and_amplitude()
            data["peak_frequency"] = peak_frequency
            data["peak_amplitude"] = peak_amplitude
            lab_logger.info(f"Collected datapoint: {data}")

            # Write this data as a line in the csv
            with open(LAB_DATA_PATH, "a", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=LAB_DATA_FIELDS, dialect="unix")
                writer.writerow(data)

            progress.update(
                task_id,
                completed=point_index + 1,
                description=f"Collecting data ({point_index + 1:,} of {len(points)} points)",
            )

    ##########################################
    #                                        #
    #     YOUR TEST CODE GOES ABOVE HERE     #
    #                                        #
    ##########################################

    # Test is done. Congrats!
    lab_logger.info(f"Test complete. Output saved to {LAB_DATA_PATH}")

    # Try to move turntable back to the center
    turntable.move_to(azimuth=0, elevation=0)
except (Exception, KeyboardInterrupt) as exc:
    ssc_log.logger.exception(exc, exc_info=exc)

    # If anything went wrong, attempt to stop the turntable.
    turntable.send_stop_command()

lab_logger.info("Lab script complete. Exiting.")

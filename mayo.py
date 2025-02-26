import os
import threading
import time

from msu_ssc import ssc_log

from msu_anechoic.spec_an import SpectrumAnalyzerHP8563E
from msu_anechoic.turn_table import Turntable

plaintext_file_path = "mayo.log"
jsonl_file_path = "mayo.jsonl"

# DELETE FILES IF THEY EXIST
if os.path.exists(plaintext_file_path):
    os.remove(plaintext_file_path)

if os.path.exists(jsonl_file_path):
    os.remove(jsonl_file_path)

ssc_log.init(level="DEBUG", plain_text_file_path="mayo.log", jsonl_file_path="mayo.jsonl")

INITIAL_CENTER_FREQUENCY = 8_450_000_000


# CREATE SPEC AN OBJECT
spec_an = SpectrumAnalyzerHP8563E.find(
    log_query_messages=False,
    logger=ssc_log.logger.getChild("spec_an"),
)
if not spec_an:
    raise ValueError("No Spectrum Analyzer found.")


# INITIAL SPEC AN CONFIG
spec_an.set_center_frequency(INITIAL_CENTER_FREQUENCY)
span = 1_000_000

for span in [1_000_000, 100_000, 10_000, 1_000]:
    time.sleep(3)
    peak_freq, peak_amp = spec_an.get_peak_frequency_and_amplitude()
    spec_an.set_center_frequency(peak_freq)
    time.sleep(3)
    spec_an.set_span(span)
    time.sleep(3)

center_frequency = spec_an.get_center_frequency()
span = spec_an.get_span()
spec_an.set_marker_frequency(center_frequency)
print(f"CF: {center_frequency:,} Hz, Span: {span:,} Hz")


# BEGIN SPEC AN CONTINUOUS SCAN
thread = threading.Thread(
    target=spec_an.scan_continuously,
    daemon=True,
    kwargs={
        "scan_cf_amplitude": True,
        "scan_peak": True,
        "csv_file_path": "./spec_an.csv",
        "delay_between_observations": 0.0,
    },
)
thread.start()


# CREATE TURNTABLE OBJECT
turn_table = Turntable(
    port="COM5",
    timeout=5,
    logger=ssc_log.logger.getChild("turn_table"),
    csv_file_path="turntable.csv",
)

# SET TURNTABLE TO 0, 0
turn_table.send_set_command(azimuth=0, elevation=0)

# MOVE TURNTABLE
try:
    time.sleep(5)
    turn_table.move_to(azimuth=0, elevation=-70)
    # time.sleep(5)
    turn_table.move_to(azimuth=0, elevation=40)
    # time.sleep(5)
    turn_table.move_to(azimuth=0, elevation=0)

finally:
    turn_table.send_emergency_move_command(azimuth=0, elevation=0)

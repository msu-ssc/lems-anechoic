from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Literal
from typing import Sequence

import pyvisa

import msu_anechoic

try:
    import numpy as np
except ImportError:
    from msu_anechoic.util import _numpy as np

if TYPE_CHECKING:
    import logging
    from msu_anechoic.experiment import SpecAnConfig

__all__ = ["GpibDevice", "SpectrumAnalyzerHP8563E"]


class GpibError(Exception):
    """Some error in GPIB communication happened."""


class GpibDevice:
    """A base class for GPIB devices at the MSU Space Science Center."""

    # This is what's called when you do `SpecAnHP8563E("GPIB0::18::INSTR")`.
    def __init__(
        self,
        gpib_address: str,
        *,
        open_immediately: bool = True,
        resource_manager: pyvisa.highlevel.ResourceManager | None = None,
        logger: logging.Logger | None = None,
        log_query_messages: bool = False,
    ):
        self.logger = logger or msu_anechoic.create_null_logger()
        self.gpib_address = gpib_address
        self.resource_manager = resource_manager or pyvisa.ResourceManager()
        self.log_every_message = log_query_messages

        self.logger.debug(f"SpecAn object created at {self.gpib_address=} and {self.resource_manager=}")

        self.resource: pyvisa.resources.MessageBasedResource | None = None

        if open_immediately:
            self.open()

    def query(self, command: str, sweep: bool = False) -> str:
        """Query the spectrum analyzer.

        Return the response, which will be a string, usually with trailing `'\\n'`."""
        if sweep:
            command = "TS;" + command
            response = self.resource.query(command)
            
        if self.log_every_message:
            self.logger.debug(f"Querying {self.gpib_address!r} with {command=}")
        if self.resource is None:
            message = f"Connection to {self.__class__.__name__} is not open."
            self.logger.error(message)
            raise GpibError(message)
        response = self.resource.query(command)
        if self.log_every_message:
            self.logger.debug(f"Response from {self.gpib_address!r} to {command=} is {response=}")
        return response

    def write(self, command: str) -> int:
        """Write to the spectrum analyzer.

        Return the number of bytes written."""
        if self.log_every_message:
            self.logger.debug(f"Writing {command=} to {self.gpib_address!r}")
        if self.resource is None:
            message = f"Connection to {self.__class__.__name__} is not open."
            self.logger.error(message)
            raise GpibError(message)
        response = self.resource.write(command)
        if self.log_every_message:
            self.logger.debug(f"{command=} written to {self.gpib_address!r} with {response=}")
        return response

    def open(self):
        """Open the connection to the spectrum analyzer."""
        self.logger.info(f"Attempting to open GPIB connection to {self.gpib_address!r}")
        try:
            self.resource = self.resource_manager.open_resource(self.gpib_address)
            self.logger.info(f"Connection to {self.gpib_address!r} opened. {self.resource=}")
        except Exception as exc:
            self.logger.error(f"Error opening {self!r}. {exc}", exc_info=True)
            raise

    def close_connection(self):
        """Close the connection to the GPIB device."""

        # This is currently a no-op, for reasons explained in the comments below.
        # Old code with explanatory comments is kept, and might someday be restored.
        return
        self.logger.debug(f"Closing connection to {self.gpib_address!r}")
        if self.resource:
            try:
                # NOTE: Do not call `close()`!
                #
                # Calling "close()" on a resource seems to mark it as unusable somewhere within VISA (not PyVisa)
                # in a way that I (David Mayo) don't understand.
                #
                # The way this manifests is that this code fails:
                # ```
                # rm = pyvisa.ResourceManager()
                # resource = rm.open_resource("GPIB0::18::INSTR")
                # resource.close()
                #
                # rm = pyvisa.ResourceManager()
                # # The above line will hang here for exactly 4 minutes. Why? No one knows. Here's a GitHub issue about it:
                # # https://github.com/pyvisa/pyvisa/issues/197
                #
                # After 4 minutes, the ResourceManager WILL open, but it will be in a weird state where it can't do anything.
                # rm.list_resources()   # Will hang forever
                # rm.open_resource("GPIB0::18::INSTR")  # Will hang forever and/or fail with weird error messages
                # ```

                # self.resource.close()

                # TO BE DETERMINED: Is it necessary to clear the resource? Will it break things?
                # Unknown to me (David Mayo) as of March 2025, so we're not doing it.
                # self.resource.clear()

                self.logger.info(f"Connection to {self.gpib_address!r} closed.")
            except Exception as exc:
                self.logger.error(f"Error closing {self!r}. {exc}", exc_info=True)

    @classmethod
    def find(
        cls,
        *,
        logger: logging.Logger | None = None,
        resource_manager: pyvisa.highlevel.ResourceManager | None = None,
        open_immediately: bool = True,
        log_query_messages: bool = False,
    ) -> "GpibDevice":
        raise NotImplementedError(f"This method must be implemented in a subclass")

    # This is a method to make this a context manager. (with ... as ...).
    # Don't worry about this.
    def __enter__(self):
        return self

    # This is a method to make this a context manager. (with ... as ...).
    # Don't worry about this.
    def __exit__(self, exc_type, exc_value, traceback):
        self.close_connection()

    # This makes the object more readable when printed.
    def __repr__(self):
        return f"{self.__class__.__name__}(gpib_address={self.gpib_address!r})"

    pass


class SpectrumAnalyzerHP8563E(GpibDevice):
    """Class for interacting with a Hewlett Packard 8563E Spectrum Analyzer via GPIB.

    This class only implements a few commands. There are many more available. Detailed information for this model is
    in "User's Guide Agilent Technologies 8560 E-Series and EC-Series Spectrum Analyzers", which you can Google. As of
    2025-02-13, you can find it at
    https://testworld.com/wp-content/uploads/user-guide-keysight-agilent-8561e-8562e-8563e-8564e-8565e-8561ec-8562ec-8563ec-8564ec-8565ec-spectrum-analyzers.pdf
    """

    @classmethod
    def find(
        cls,
        *,
        logger: logging.Logger | None = None,
        resource_manager: pyvisa.highlevel.ResourceManager | None = None,
        open_immediately: bool = True,
        log_query_messages: bool = False,
    ) -> "SpectrumAnalyzerHP8563E":
        """Find an HP 8563E spectrum analyzer on the GPIB bus.

        Return a `SpectrumAnalyzerHP8563E` object if one is found, otherwise raise a `GpibError`.


        Example:
        ```python
        with SpectrumAnalyzerHP8563E.find() as spectrum_analyzer:
            center_frequency = spectrum_analyzer.get_center_frequency()
            ...
        ```
        """
        logger = logger or msu_anechoic.create_null_logger()
        resource_manager = resource_manager or pyvisa.ResourceManager()
        resources = resource_manager.list_resources()
        for resource_name in resources:
            if logger:
                logger.debug(f"Checking {resource_name=}")

            if "GPIB" not in resource_name:
                logger.debug(f"Skipping {resource_name=}, because it is not a GPIB device.")
                continue
            try:
                resource: pyvisa.resources.MessageBasedResource = resource_manager.open_resource(resource_name)

                # NOTE: 8563E doesn't respond to "*IDN?", so we have to use something else.
                # Of the GPIB devices at MSU Space Science Center, this is the only one that responds to "CF?".
                response = resource.query("CF?")
            except Exception as exc:
                if logger:
                    logger.debug(f"Error checking {resource_name=}. {exc}")
                continue
            if response:
                if logger:
                    logger.info(f"Found HP 8563E spectrum analyzer at {resource_name=}")
                return SpectrumAnalyzerHP8563E(
                    gpib_address=resource.resource_name,
                    logger=logger,
                    resource_manager=resource_manager,
                    open_immediately=open_immediately,
                    log_query_messages=log_query_messages,
                )

        # If we get here, we didn't find any HP 8563E spectrum analyzers.
        message = "No HP 8563E spectrum analyzer found."
        logger.error(message)
        raise GpibError(message)

    def get_config(self) -> "SpecAnConfig":
        """Get the config"""
        from msu_anechoic import experiment
        return experiment.SpecAnConfig.from_spec_an(self)

    def apply_config(self, config: "SpecAnConfig") -> None:
        """Apply the config"""
        config.apply_to(self)

    def move_center_to_peak(
        self,
        center_frequency: float,
        spans: Sequence[float],
        delay: float = 3.0,
    ) -> float:
        """Center this spectrum analyzer on a frequency and scan for the peak amplitude, recursively narrowing the span.

        `delay` is the time to wait between each command, in seconds.

        All frequencies are in Hertz.

        Return value is the final center frequency, in Hertz."""
        self.logger.debug(f"Centering to peak on {center_frequency=} with {spans=}")
        time.sleep(delay)
        self.set_center_frequency(center_frequency)
        for span in spans:
            time.sleep(delay)
            self.set_span(span)
            time.sleep(delay)
            self.set_marker_to_highest_amplitude()
            center_frequency = self.get_marker_frequency()
            self.set_center_frequency(center_frequency)
        self.set_marker_frequency(center_frequency)
        return center_frequency

    def get_sweep_time(self, sweep: bool = False) -> float:
        """Get the sweep time of the spectrum analyzer in seconds."""
        self.logger.debug(f"Getting sweep time from {self.gpib_address!r}")
        response = self.query("ST?", sweep=sweep)
        return float(response)
        # return float(self.query("ST?").strip())
    
    def set_sweep_time(self, time: float) -> None:
        """Set the sweep time of the spectrum analyzer in seconds."""
        self.logger.debug(f"Setting sweep time of {self.gpib_address!r} to {time=:_} s")
        self.write(f"ST {time}")

    def set_center_frequency(self, frequency: float):
        """Set the center frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Setting center frequency of {self.gpib_address!r} to {frequency=}")
        self.write(f"CF {frequency}")

    def get_center_frequency(self, sweep: bool = False) -> float:
        """Get the center frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Getting center frequency of {self.gpib_address!r}")
        response = self.query("CF?", sweep=sweep)
        return float(response)

    def set_span(self, span: float):
        """Set the span of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Setting span of {self.gpib_address!r} to {span=:_}")
        self.write(f"SP {span}")

    def get_gpib_timeout_ms(self) -> float | None:
        """Get the timeout of the spectrum analyzer in milliseconds."""
        if self.resource is None:
            return None

        return self.resource.timeout
    
    def set_gpib_timeout_ms(self, timeout: float) -> None:
        """Set the timeout of the spectrum analyzer in milliseconds."""
        if self.resource is None:
            raise GpibError(f"Cannot set timeout on resource because it is not open.")
        self.logger.debug(f"Setting timeout of {self.gpib_address!r} to {timeout=:_} ms.")
        self.resource.timeout = timeout

    def get_span(self, sweep: bool = False) -> float:
        """Get the span of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Getting span of {self.gpib_address!r}")
        return float(self.query("SP?", sweep=sweep).strip())

    def get_lower_frequency(self, sweep: bool = False) -> float:
        """Get the lower frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Getting lower frequency of {self.gpib_address!r}")
        return float(self.query("FA?", sweep=sweep))

    def get_upper_frequency(self, sweep: bool = False) -> float:
        """Get the upper frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Getting upper frequency of {self.gpib_address!r}")
        return float(self.query("FB?", sweep=sweep))

    def set_lower_frequency(self, frequency: float):
        """Set the lower frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Setting lower frequency of {self.gpib_address!r} to {frequency=}")
        self.write(f"FA {frequency}")

    def set_upper_frequency(self, frequency: float):
        """Set the upper frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Setting upper frequency of {self.gpib_address!r} to {frequency=}")
        self.write(f"FB {frequency}")

    def get_trace(self, trace: Literal["A", "B"] = "A", *, sweep: bool = False) -> list[float]:
        """Get the trace from the spectrum analyzer."""
        self.logger.debug(f"Getting trace {trace} from {self.gpib_address!r}")
        response = self.query(f"TR{trace}?", sweep=sweep)
        return [float(x) for x in response.split(",")]

    def get_trace_frequencies_and_amplitudes(self, sweep: bool = False,trace: Literal["A", "B"] = "A") -> tuple[list[float], list[float]]:
        """Get the frequencies and amplitudes of the trace from the spectrum analyzer.

        Response will be a tuple of Numpy arrays: `(frequencies, amplitudes)`."""
        self.logger.debug(f"Getting trace frequencies and amplitudes {trace} from {self.gpib_address!r}")
        amplitudes = self.get_trace(trace, sweep=sweep)
        # Have to manually calculate the frequencies because the spectrum analyzer doesn't provide them.
        frequencies = [
            float(x) for x in np.linspace(self.get_lower_frequency(sweep=sweep), self.get_upper_frequency(sweep=sweep), len(amplitudes))
        ]
        return frequencies, amplitudes

    def get_marker_frequency(self, sweep: bool = False) -> float:
        """Get the frequency of the marker in Hertz."""
        self.logger.debug(f"Getting marker frequency from {self.gpib_address!r}")
        return float(self.query(f"MKF?", sweep=sweep))

    def set_marker_frequency(self, frequency: float):
        """Set the frequency of the marker in Hertz."""
        self.logger.debug(f"Setting marker frequency of {self.gpib_address!r} to {frequency=}")
        self.write(f"MKF {frequency}")

    def get_marker_amplitude(self, sweep: bool = False) -> float:
        """Get the amplitude of the marker."""
        self.logger.debug(f"Getting marker amplitude from {self.gpib_address!r}")
        return float(self.query(f"MKA?", sweep=sweep))

    def get_center_frequency_amplitude(self, sweep: bool = False) -> float:
        """Get the amplitude at the center frequency of the spectrum analyzer.

        Does three things:
        1. Gets the center frequency.
        2. Sets the marker frequency to the center frequency.
        3. Gets the marker amplitude."""
        self.logger.debug(f"Getting center frequency amplitude from {self.gpib_address!r}")
        center_frequency = self.get_center_frequency()
        self.set_marker_frequency(center_frequency)
        return self.get_marker_amplitude(sweep=sweep)

    def get_highest_amplitude(self, sweep: bool = False) -> float:
        """Get the highest amplitude from the trace."""
        self.logger.debug(f"Getting highest amplitude from {self.gpib_address!r}")
        return max(self.get_trace(sweep=sweep))

    def set_marker_to_highest_amplitude(self) -> None:
        """Set the marker to the highest amplitude.

        This is "Peak Search" on the front panel."""
        self.logger.debug(f"Setting marker to highest amplitude from {self.gpib_address!r}")
        self.write("MKPK")

    def get_peak_frequency_and_amplitude(self, sweep: bool = False) -> tuple[float, float]:
        """Do a peak search and get the peak frequency and amplitude.

        Returns `(frequency, amplitude)`."""
        self.logger.debug(f"Getting highest amplitude from {self.gpib_address!r}")
        self.set_marker_to_highest_amplitude()
        marker_frequency = self.get_marker_frequency()
        marker_amplitude = self.get_marker_amplitude(sweep=sweep)
        self.logger.debug(f"Marker at {marker_frequency=} with {marker_amplitude=}")
        return marker_frequency, marker_amplitude

    def get_reference_level(self, sweep: bool = False) -> float:
        """Get the reference level of the spectrum analyzer."""
        self.logger.debug(f"Getting reference level from {self.gpib_address!r}")
        return float(self.query("RL?", sweep=sweep))

    def set_reference_level(self, level: float) -> None:
        """Set the reference level of the spectrum analyzer."""
        self.logger.debug(f"Setting reference level of {self.gpib_address!r} to {level=}")
        self.write(f"RL {level:0.2f}")

    def get_serial_number(self, sweep: bool = False) -> str:
        """Get the serial number of the spectrum analyzer."""
        self.logger.debug(f"Getting serial number from {self.gpib_address!r}")
        return self.query("SER?", sweep=sweep).strip()
    
    def get_video_bandwidth(self, sweep: bool = False) -> float:
        """Get the video bandwidth of the spectrum analyzer."""
        self.logger.debug(f"Getting video bandwidth from {self.gpib_address!r}")
        return float(self.query("VB?", sweep=sweep).strip())
    
    def set_video_bandwidth(self, bandwidth: float) -> None:
        """Set the video bandwidth of the spectrum analyzer."""
        bandwidth_int = int(bandwidth)
        self.logger.debug(f"Setting video bandwidth of {self.gpib_address!r} to {bandwidth_int=}")
        self.write(f"VB {int(bandwidth_int)}")

    def get_resolution_bandwidth(self, sweep: bool = False) -> float:
        """Get the resolution bandwidth of the spectrum analyzer."""
        self.logger.debug(f"Getting resolution bandwidth from {self.gpib_address!r}")
        return float(self.query("RB?", sweep=sweep).strip())
    
    def set_resolution_bandwidth(self, bandwidth: float) -> None:
        """Set the resolution bandwidth of the spectrum analyzer."""
        bandwidth_int = int(bandwidth)
        self.logger.debug(f"Setting resolution bandwidth of {self.gpib_address!r} to {bandwidth_int=}")
        self.write(f"RB {int(bandwidth_int)}")

    def get_amplitude_units(self, sweep: bool = False) -> str:
        """Get the units of the spectrum analyzer."""
        self.logger.debug(f"Getting units from {self.gpib_address!r}")
        return self.query("AUNITS?", sweep=sweep).strip()
    
    def set_amplitude_units(self, units: str) -> None:
        """Set the units of the spectrum analyzer."""
        valid = {"dbm", "dbuv", "dbmv", "auto", "man", "v", "w", "dm"}
        if units.lower() not in valid:
            raise ValueError(f"Invalid units: {units}. Must be one of {valid}.")
        self.logger.debug(f"Setting units of {self.gpib_address!r} to {units=}")
        self.write(f"AUNITS {units}")

    def enable_continuous_mode(self) -> None:
        """Enable continuous mode."""
        self.logger.debug(f"Enabling continuous mode on {self.gpib_address!r}")
        self.write("CONTS")

    def enable_single_sweep_mode(self) -> None:
        """Enable single sweep mode."""
        self.logger.debug(f"Enabling single sweep mode on {self.gpib_address!r}")
        self.write("SNGLS")

    def reset_all(self) -> None:
        """Reset all configs to preset, same as power cycling the spec an."""
        self.logger.debug(f"Resetting all configs on {self.gpib_address!r}")
        self.write("IP")

    def take_sweep(self) -> None:
        """Take a full sweep."""
        self.logger.debug(f"Taking sweep on {self.gpib_address!r}")
        self.query("TS;DONE?")

    def scan_continuously(
        self,
        *,
        scan_cf_amplitude: bool = True,
        scan_peak: bool = True,
        csv_file_path: str | Path,
        delay_between_observations: float = 0.05,
    ) -> None:
        """Scan continuously for different things.

        This method should be a valid target for a `threading.Thread` or `multiprocessing.Process`."""
        import csv
        import time

        csv_file_path = Path(csv_file_path).expanduser().resolve()
        self.logger.info(
            f"Starting continuous scan on {self.gpib_address!r}. Saving to {csv_file_path} {scan_cf_amplitude=} {scan_peak=}"
        )

        csv_file_path.parent.mkdir(parents=True, exist_ok=True)
        filenames = []
        if scan_cf_amplitude:
            filenames.extend(
                [
                    "center_frequency_amplitude",
                    "center_frequency_amplitude_timestamp_before",
                    "center_frequency_amplitude_timestamp_after",
                ]
            )
        if scan_peak:
            filenames.extend(["peak_frequency", "peak_amplitude", "peak_timestamp_before", "peak_timestamp_after"])

        with open(csv_file_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=filenames, dialect="unix")
            writer.writeheader()

        while True:
            if scan_cf_amplitude:
                center_frequency_amplitude_timestamp_before = datetime.datetime.now(tz=datetime.timezone.utc)
                center_frequency_amplitude = self.get_center_frequency_amplitude()
                center_frequency_amplitude_timestamp_after = datetime.datetime.now(tz=datetime.timezone.utc)
                # self.logger.debug(f"Center frequency amplitude: {center_frequency_amplitude=}")
            if scan_peak:
                peak_timestamp_before = datetime.datetime.now(tz=datetime.timezone.utc)
                peak_frequency, peak_amplitude = self.get_peak_frequency_and_amplitude()
                peak_timestamp_after = datetime.datetime.now(tz=datetime.timezone.utc)
                # self.logger.debug(f"Highest amplitude: {peak_amplitude} at {peak_frequency} Hz")

                with open(csv_file_path, "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=filenames, dialect="unix")
                    row = {}
                    if scan_cf_amplitude:
                        row["center_frequency_amplitude"] = center_frequency_amplitude
                        row["center_frequency_amplitude_timestamp_before"] = (
                            center_frequency_amplitude_timestamp_before.isoformat(timespec="microseconds")
                        )
                        row["center_frequency_amplitude_timestamp_after"] = (
                            center_frequency_amplitude_timestamp_after.isoformat(timespec="microseconds")
                        )
                    if scan_peak:
                        row["peak_frequency"] = peak_frequency
                        row["peak_amplitude"] = peak_amplitude
                        row["peak_timestamp_before"] = peak_timestamp_before.isoformat(timespec="microseconds")
                        row["peak_timestamp_after"] = peak_timestamp_after.isoformat(timespec="microseconds")
                    writer.writerow(row)

            time.sleep(delay_between_observations)


find = SpectrumAnalyzerHP8563E.find

if __name__ == "__main__":
    from msu_ssc import ssc_log

    # Configure logging first of all
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    ssc_log.init(
        level="DEBUG",
        # plain_text_level="INFO",
        plain_text_file_path=f"logs/{ssc_log.utc_filename_timestamp(timestamp=now, prefix='spec_an', extension='.log')}",
        jsonl_level="DEBUG",
        jsonl_file_path=f"logs/{ssc_log.utc_filename_timestamp(timestamp=now, prefix='spec_an', extension='.jsonl')}",
    )
    spec_an_logger = ssc_log.logger.getChild("spec_an")
    spec_an_logger.info(f"Starting {__file__}")

    with SpectrumAnalyzerHP8563E.find(
        logger=spec_an_logger,
    ) as spectrum_analyzer:
        print(f"{spectrum_analyzer=} {type(spectrum_analyzer)=} {bool(spectrum_analyzer)=}")
        if not spectrum_analyzer:
            spec_an_logger.error("No spectrum analyzer found.")
            sys.exit(1)

        print(f"{spectrum_analyzer.get_reference_level()=}")
        print(f"{spectrum_analyzer.set_reference_level(-30)=}")
        print(f"{spectrum_analyzer.get_reference_level()=}")
        # # # with SpectrumAnalyzerHP8563E(
        # # #     gpib_address="GPIB0::18::INSTR",
        # # #     logger=spec_an_logger,
        # # # ) as spectrum_analyzer:
        # # # spectrum_analyzer.open()

        # # print(spectrum_analyzer.query("CF?"))
        # # print(spectrum_analyzer.write("CF 287000000"))
        # # print(spectrum_analyzer.query("CF?"))

        # # print(f"{spectrum_analyzer.resource.query_delay=}")

        # # print(spectrum_analyzer.get_center_frequency())
        # # print(spectrum_analyzer.get_span())
        # # import time
        # # for _ in range(10):
        # #     start = time.monotonic()
        # #     spectrum_analyzer.set_center_frequency(287_000_000)
        # #     spectrum_analyzer.set_span(100_000_000)
        # #     stop = time.monotonic()
        # #     print(f"Time to set center frequency and span: {stop - start:.2f}s")

        # # # exit()
        # # print(spectrum_analyzer.get_center_frequency())
        # # print(spectrum_analyzer.get_span())

        # # print(spectrum_analyzer.query("FA?"))
        # # print(spectrum_analyzer.query("FB?"))

        # # spectrum_analyzer.set_lower_frequency(287_000_000)
        # # spectrum_analyzer.set_upper_frequency(487_000_000)
        # # print(spectrum_analyzer.get_lower_frequency())
        # # print(spectrum_analyzer.get_upper_frequency())
        # # print(spectrum_analyzer.get_span())
        # # print(spectrum_analyzer.get_center_frequency())

        # # # print(spectrum_analyzer.get_trace("A"))

        # # # trace = spectrum_analyzer.get_trace("A")
        # # # numbers = [float(x) for x in trace.split(",")]
        # # # print(numbers)
        # # # print(len(numbers))

        # # print("MARKER:", spectrum_analyzer.get_marker_frequency())
        # # # spectrum_analyzer.set_center_frequency(300_000_000)
        # # print("MARKER:", spectrum_analyzer.get_marker_frequency())
        # # spectrum_analyzer.write("CF 300000000")
        # # spectrum_analyzer.write("MKF 400000000")
        # # spectrum_analyzer.write("MKCF")
        # # print("MARKER:", spectrum_analyzer.get_marker_frequency())
        # # print("CENTER:", spectrum_analyzer.get_center_frequency())

        # # print("MARKER AMPLITUDE:", spectrum_analyzer.get_marker_amplitude())
        # # print("CENTER AMPLITUDE:", spectrum_analyzer.get_center_frequency_amplitude())

        # # xs, ys = spectrum_analyzer.get_trace_frequencies_and_amplitudes("A")

        # # print(f"{spectrum_analyzer.query('AUNITS?')}")

        # # import time

        # # for _ in range(10):
        # #     start_time = time.monotonic()

        # #     # cf = spectrum_analyzer.get_center_frequency()
        # #     # cf_power = spectrum_analyzer.get_center_frequency_amplitude()

        # #     spectrum_analyzer.set_marker_frequency(300_000_000)
        # #     # marker_power = spectrum_analyzer.get_marker_amplitude()
        # #     max_power_freq, max_power_amp = spectrum_analyzer.get_peak_frequency_and_amplitude()
        # #     stop_time = time.monotonic()
        # #     print(f"Time to get data: {stop_time - start_time:.2f}s {max_power_freq=} {max_power_amp=}")

        # import threading

        # spectrum_analyzer.set_center_frequency(8_450_000_000)
        # spectrum_analyzer.set_span(2_000)

        # import time

        # time.sleep(5)

        # peak_freq, peak_amp = spectrum_analyzer.get_peak_frequency_and_amplitude()
        # spectrum_analyzer.set_center_frequency(peak_freq)

        # time.sleep(5)

        # from msu_anechoic.turn_table import Turntable

        # tt = Turntable(
        #     port="COM5",
        #     timeout=1,
        #     logger=spec_an_logger,
        # )
        # tt.send_set_command(azimuth=0, elevation=0)
        # # tt.move_to(azimuth=-5, elevation=0)

        # thread = threading.Thread(
        #     target=spectrum_analyzer.scan_continuously,
        #     daemon=True,
        #     kwargs={
        #         "scan_cf_amplitude": True,
        #         "scan_peak": True,
        #         "csv_file_path": "./test.csv",
        #         "delay_between_observations": 0.0,
        #     },
        # )

        # print("Starting thread")
        # thread.start()
        # print("Thread started")
        # import time

        # time.sleep(5)
        # tt.move_to(azimuth=0, elevation=10)
        # time.sleep(5)
        # tt.move_to(azimuth=0, elevation=-10)
        # time.sleep(5)
        # tt.send_emergency_move_command(azimuth=0, elevation=0)
        # time.sleep(60)
        # print("Stopping thread")
        # thread.join()

        # import matplotlib.pyplot as plt

        # fig, ax = plt.subplots()
        # ax.plot(xs, ys)
        # ax.set_xlabel("Frequency (Hz)")
        # ax.set_ylabel("Amplitude (dBm)")
        # plt.show()

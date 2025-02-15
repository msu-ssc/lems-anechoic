from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING
from typing import Literal

import numpy as np
import pyvisa

sys.path.append(os.path.abspath("."))   # SO STUPID!

import msu_anechoic

if TYPE_CHECKING:
    import logging


__all__ = ["SpectrumAnalyzerHP8563E"]


class SpectrumAnalyzerHP8563E:
    """Class for interacting with a Hewlett Packard 8563E Spectrum Analyzer via GPIB.

    This class only implements a few commands. There are many more available. Detailed information for this model is
    in "User's Guide Agilent Technologies 8560 E-Series and EC-Series Spectrum Analyzers", which you can Google. As of
    2025-02-13, you can find it at
    https://testworld.com/wp-content/uploads/user-guide-keysight-agilent-8561e-8562e-8563e-8564e-8565e-8561ec-8562ec-8563ec-8564ec-8565ec-spectrum-analyzers.pdf
    """

    # This is what's called when you do `SpecAnHP8563E("GPIB0::18::INSTR")`.
    def __init__(
        self,
        gpib_address: str,
        *,
        open_immediately: bool = True,
        resource_manager: pyvisa.highlevel.ResourceManager | None = None,
        logger: logging.Logger | None = None,
    ):
        self.logger = logger or msu_anechoic._create_null_logger()
        self.gpib_address = gpib_address
        self.resource_manager = resource_manager or pyvisa.ResourceManager()

        self.logger.debug(f"SpecAn object created at {self.gpib_address=} and {self.resource_manager=}")

        self.resource: pyvisa.resources.MessageBasedResource | None = None

        if open_immediately:
            self.open()

    def query(self, command: str) -> str:
        """Query the spectrum analyzer.

        Return the response, which will be a string, usually with trailing `'\\n'`."""
        # self.logger.debug(f"Querying {self.gpib_address=} with {command=}")
        if self.resource is None:
            raise ValueError("Connection to the spectrum analyzer is not open.")
        response = self.resource.query(command)
        # self.logger.debug(f"Response from {self.gpib_address=} to {command=} is {response=}")
        return response

    def write(self, command: str) -> int:
        """Write to the spectrum analyzer.

        Return the number of bytes written."""
        # self.logger.debug(f"Writing {command=} to {self.gpib_address=}")
        if self.resource is None:
            raise ValueError("Connection to the spectrum analyzer is not open.")
        response = self.resource.write(command)
        # self.logger.debug(f"{command=} written to {self.gpib_address=} with {response=}")
        return response

    @classmethod
    def find(cls) -> "SpectrumAnalyzerHP8563E | None":
        """Find the spectrum analyzer."""
        resource_manager = pyvisa.ResourceManager()
        resources = resource_manager.list_resources()
        for resource in resources:
            try:
                resource: pyvisa.resources.MessageBasedResource = resource_manager.open_resource(resource)
                response = resource.query("CF?")
            except Exception as exc:
                continue
            if response:
                return SpectrumAnalyzerHP8563E(
                    gpib_address=resource.resource_name,
                )
        return None

    def set_center_frequency(self, frequency: float):
        """Set the center frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Setting center frequency of {self.gpib_address=} to {frequency=}")
        self.write(f"CF {frequency}")

    def get_center_frequency(self) -> float:
        """Get the center frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Getting center frequency of {self.gpib_address=}")
        response = self.query("CF?")
        return float(response)

    def set_span(self, span: float):
        """Set the span of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Setting span of {self.gpib_address=} to {span=}")
        self.write(f"SP {span}")

    def get_span(self) -> float:
        """Get the span of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Getting span of {self.gpib_address=}")
        return float(self.query("SP?").strip())

    def get_lower_frequency(self) -> float:
        """Get the lower frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Getting lower frequency of {self.gpib_address=}")
        return float(self.query("FA?"))

    def get_upper_frequency(self) -> float:
        """Get the upper frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Getting upper frequency of {self.gpib_address=}")
        return float(self.query("FB?"))

    def set_lower_frequency(self, frequency: float):
        """Set the lower frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Setting lower frequency of {self.gpib_address=} to {frequency=}")
        self.write(f"FA {frequency}")

    def set_upper_frequency(self, frequency: float):
        """Set the upper frequency of the spectrum analyzer in Hertz."""
        self.logger.debug(f"Setting upper frequency of {self.gpib_address=} to {frequency=}")
        self.write(f"FB {frequency}")

    def get_trace(self, trace: Literal["A", "B"] = "A") -> np.ndarray[np.float64]:
        """Get the trace from the spectrum analyzer."""
        self.logger.debug(f"Getting trace {trace} from {self.gpib_address=}")
        response = self.query(f"TR{trace}?")
        return np.array([float(x) for x in response.split(",")])

    def get_trace_frequencies_and_amplitudes(self, trace: Literal["A", "B"] = "A") -> tuple[np.ndarray[np.float64], np.ndarray[np.float64]]:
        """Get the frequencies and amplitudes of the trace from the spectrum analyzer.
        
        Response will be a tuple of Numpy arrays: `(frequencies, amplitudes)`."""
        import numpy as np
        self.logger.debug(f"Getting trace frequencies and amplitudes {trace} from {self.gpib_address=}")
        amplitudes = self.get_trace(trace)
        # Have to manually calculate the frequencies because the spectrum analyzer doesn't provide them.
        frequencies = np.linspace(self.get_lower_frequency(), self.get_upper_frequency(), len(amplitudes))
        return frequencies, amplitudes

    def get_marker_frequency(self) -> float:
        """Get the frequency of the marker in Hertz."""
        self.logger.debug(f"Getting marker frequency from {self.gpib_address=}")
        return float(self.query(f"MKF?"))

    def set_marker_frequency(self, frequency: float):
        """Set the frequency of the marker in Hertz."""
        self.logger.debug(f"Setting marker frequency of {self.gpib_address=} to {frequency=}")
        self.write(f"MKF {frequency}")

    def get_marker_amplitude(self) -> float:
        """Get the amplitude of the marker."""
        self.logger.debug(f"Getting marker amplitude from {self.gpib_address=}")
        return float(self.query(f"MKA?"))

    def get_center_frequency_amplitude(self) -> float:
        """Get the amplitude at the center frequency of the spectrum analyzer.

        Does three things:
        1. Gets the center frequency.
        2. Sets the marker frequency to the center frequency.
        3. Gets the marker amplitude."""
        self.logger.debug(f"Getting center frequency amplitude from {self.gpib_address=}")
        center_frequency = self.get_center_frequency()
        self.set_marker_frequency(center_frequency)
        return self.get_marker_amplitude()

    def open(self):
        """Open the connection to the spectrum analyzer."""
        self.logger.info(f"Attempting to open GPIB connection to {self.gpib_address=}")
        try:
            self.resource = self.resource_manager.open_resource(self.gpib_address)
            self.logger.info(f"Connection to {self.gpib_address=} opened. {self.resource=}")
        except Exception as exc:
            self.logger.error(f"Error opening {self!r}. {exc}", exc_info=True)
            raise

    def close(self):
        """Close the connection to the spectrum analyzer."""
        self.logger.debug(f"Closing connection to {self.gpib_address=}")
        if self.resource:
            try:
                self.resource.close()
                self.logger.info(f"Connection to {self.gpib_address=} closed.")
            except Exception as exc:
                self.logger.error(f"Error closing {self!r}. {exc}", exc_info=True)

    # This is a method to make this a context manager. (with ... as ...).
    # Don't worry about this.
    def __enter__(self):
        return self

    # This is a method to make this a context manager. (with ... as ...).
    # Don't worry about this.
    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    # This makes the object more readable when printed.
    def __repr__(self):
        return f"{self.__class__.__name__}(gpib_address={self.gpib_address!r})"


if __name__ == "__main__":
    import datetime

    from msu_ssc import ssc_log

    # Configure logging first of all
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    ssc_log.init(
        plain_text_level="DEBUG",
        plain_text_file_path=f"logs/{ssc_log.utc_filename_timestamp(timestamp=now, prefix='spec_an', extension='.log')}",
        jsonl_level="DEBUG",
        jsonl_file_path=f"logs/{ssc_log.utc_filename_timestamp(timestamp=now, prefix='spec_an', extension='.jsonl')}",
    )
    spec_an_logger = ssc_log.logger.getChild("spec_an")
    spec_an_logger.info(f"Starting {__file__}")

    if True:
        spectrum_analyzer = SpectrumAnalyzerHP8563E.find()

    # with SpectrumAnalyzerHP8563E(
    #     gpib_address="GPIB0::18::INSTR",
    #     logger=spec_an_logger,
    # ) as spectrum_analyzer:
        # spectrum_analyzer.open()

        print(spectrum_analyzer.query("CF?"))
        print(spectrum_analyzer.write("CF 287000000"))
        print(spectrum_analyzer.query("CF?"))

        print(f"{spectrum_analyzer.resource.query_delay=}")

        print(spectrum_analyzer.get_center_frequency())
        print(spectrum_analyzer.get_span())

        spectrum_analyzer.set_center_frequency(287_000_000)
        spectrum_analyzer.set_span(100_000_000)

        print(spectrum_analyzer.get_center_frequency())
        print(spectrum_analyzer.get_span())

        print(spectrum_analyzer.query("FA?"))
        print(spectrum_analyzer.query("FB?"))

        spectrum_analyzer.set_lower_frequency(287_000_000)
        spectrum_analyzer.set_upper_frequency(487_000_000)
        print(spectrum_analyzer.get_lower_frequency())
        print(spectrum_analyzer.get_upper_frequency())
        print(spectrum_analyzer.get_span())
        print(spectrum_analyzer.get_center_frequency())

        # print(spectrum_analyzer.get_trace("A"))

        # trace = spectrum_analyzer.get_trace("A")
        # numbers = [float(x) for x in trace.split(",")]
        # print(numbers)
        # print(len(numbers))

        print("MARKER:", spectrum_analyzer.get_marker_frequency())
        # spectrum_analyzer.set_center_frequency(300_000_000)
        print("MARKER:", spectrum_analyzer.get_marker_frequency())
        spectrum_analyzer.write("CF 300000000")
        spectrum_analyzer.write("MKF 400000000")
        spectrum_analyzer.write("MKCF")
        print("MARKER:", spectrum_analyzer.get_marker_frequency())
        print("CENTER:", spectrum_analyzer.get_center_frequency())

        print("MARKER AMPLITUDE:", spectrum_analyzer.get_marker_amplitude())
        print("CENTER AMPLITUDE:", spectrum_analyzer.get_center_frequency_amplitude())

        xs, ys = spectrum_analyzer.get_trace_frequencies_and_amplitudes("A")

        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.plot(xs, ys)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Amplitude (dBm)")
        plt.show()